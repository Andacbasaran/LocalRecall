"""RapidOCR (ONNX Runtime CPU) sarmalayıcısı, bounding box çıkarımı ve asenkron OCR işçisi."""

from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from localrecall.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OCRBox:
    """Görüntü üzerinde normalize edilmiş [0..1] OCR metin kutusu."""

    text: str
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0


@dataclass(slots=True)
class OCRResult:
    """Bir görüntüden çıkarılan metin ve kutu koordinatları."""

    text: str
    boxes: list[OCRBox]

    def boxes_to_json(self) -> str:
        return json.dumps([asdict(b) for b in self.boxes], ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def parse_boxes(raw_json: str) -> list[OCRBox]:
        if not raw_json:
            return []
        try:
            items = json.loads(raw_json)
            result: list[OCRBox] = []
            for it in items:
                result.append(
                    OCRBox(
                        text=str(it.get("text", "")),
                        x=float(it.get("x", 0.0)),
                        y=float(it.get("y", 0.0)),
                        w=float(it.get("w", 0.0)),
                        h=float(it.get("h", 0.0)),
                        score=float(it.get("score", 1.0)),
                    )
                )
            return result
        except (json.JSONDecodeError, TypeError, ValueError):
            return []


class OCREngine:
    """RapidOCR ONNX CPU motoru (lazy-load, 0 MB VRAM)."""

    def __init__(self, min_confidence: float = 0.45) -> None:
        self.min_confidence = min_confidence
        self._engine = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._engine is not None:
            return
        with self._lock:
            if self._engine is not None:
                return
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
            logger.info("RapidOCR (ONNX CPU) motoru yüklendi.")

    def extract(self, image_source: Path | str | Image.Image | np.ndarray) -> OCRResult:
        """Görüntüden metin ve normalize edilmiş bounding box koordinatlarını çıkarır."""
        self._ensure_loaded()
        assert self._engine is not None

        if isinstance(image_source, Image.Image):
            rgb = image_source.convert("RGB")
            img_w, img_h = rgb.size
            img_input: str | np.ndarray = np.asarray(rgb)
        elif isinstance(image_source, (Path, str)):
            with Image.open(image_source) as opened:
                img_w, img_h = opened.size
            img_input = str(image_source)
        else:
            img_h, img_w = int(image_source.shape[0]), int(image_source.shape[1])
            img_input = image_source

        raw_result, _ = self._engine(img_input)
        if not raw_result or img_w <= 0 or img_h <= 0:
            return OCRResult(text="", boxes=[])

        lines: list[str] = []
        boxes: list[OCRBox] = []
        for item in raw_result:
            # RapidOCR formatı: [polygon_4pts, text, score]
            if len(item) < 2:
                continue
            polygon = item[0]
            text = str(item[1]).strip()
            score = 1.0
            if len(item) >= 3:
                try:
                    score = float(item[2])
                except (TypeError, ValueError):
                    score = 1.0
            if not text or score < self.min_confidence:
                continue

            lines.append(text)
            try:
                xs = [float(pt[0]) for pt in polygon]
                ys = [float(pt[1]) for pt in polygon]
                x0 = max(0.0, min(xs) / img_w)
                y0 = max(0.0, min(ys) / img_h)
                x1 = min(1.0, max(xs) / img_w)
                y1 = min(1.0, max(ys) / img_h)
                boxes.append(
                    OCRBox(
                        text=text,
                        x=round(x0, 4),
                        y=round(y0, 4),
                        w=round(max(0.0, x1 - x0), 4),
                        h=round(max(0.0, y1 - y0), 4),
                        score=round(score, 3),
                    )
                )
            except (TypeError, ValueError, IndexError):
                continue

        return OCRResult(text="\n".join(lines), boxes=boxes)

    def extract_text(self, image_source: Path | str | Image.Image | np.ndarray) -> str:
        """Geriye dönük uyumluluk için yalnızca birleştirilmiş metni döndürür."""
        return self.extract(image_source).text


class OCRWorker:
    """Yakalanan ekran görüntülerini arka plan kuyruğunda asenkron olarak OCR eder."""

    def __init__(
        self,
        db: Database,
        engine: OCREngine,
        on_ocr_complete: Callable[[int, str], None] | None = None,
        max_queue_size: int = 64,
    ) -> None:
        self.db = db
        self.engine = engine
        self.on_ocr_complete = on_ocr_complete
        self._queue: queue.Queue[tuple[int, Path] | None] = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="LocalRecall-OCR", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def enqueue(self, capture_id: int, image_path: Path) -> bool:
        """Yeni bir yakalamayı OCR kuyruğuna ekler. Kuyruk doluysa False döndürür."""
        if self._stop_event.is_set():
            return False
        try:
            self._queue.put_nowait((capture_id, image_path))
            return True
        except queue.Full:
            logger.warning("OCR kuyruğu dolu, kayıt atlandı: id=%s", capture_id)
            return False

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            capture_id, image_path = item
            try:
                if not image_path.exists():
                    continue
                res = self.engine.extract(image_path)
                self.db.update_ocr_text(capture_id, res.text, ocr_boxes=res.boxes_to_json())
                if self.on_ocr_complete:
                    self.on_ocr_complete(capture_id, res.text)
            except Exception:
                logger.exception("OCR işlenirken hata oluştu (capture_id=%s)", capture_id)
            finally:
                self._queue.task_done()
