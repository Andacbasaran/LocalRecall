"""RapidOCR (ONNX Runtime CPU) sarmalayıcısı ve asenkron OCR işçisi."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from localrecall.storage.database import Database

logger = logging.getLogger(__name__)


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

    def extract_text(self, image_source: Path | str | Image.Image | np.ndarray) -> str:
        """Verilen görüntüden metin çıkarır ve satır bazlı birleştirerek döndürür."""
        self._ensure_loaded()
        assert self._engine is not None

        if isinstance(image_source, Image.Image):
            img_input = np.asarray(image_source.convert("RGB"))
        elif isinstance(image_source, Path):
            img_input = str(image_source)
        else:
            img_input = image_source

        result, _ = self._engine(img_input)
        if not result:
            return ""

        lines: list[str] = []
        for item in result:
            # RapidOCR item formatı: [box, text, score]
            if len(item) >= 3:
                text = str(item[1]).strip()
                try:
                    score = float(item[2])
                except (TypeError, ValueError):
                    score = 1.0
                if text and score >= self.min_confidence:
                    lines.append(text)
            elif len(item) >= 2:
                text = str(item[1]).strip()
                if text:
                    lines.append(text)

        return "\n".join(lines)


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
                text = self.engine.extract_text(image_path)
                self.db.update_ocr_text(capture_id, text)
                if self.on_ocr_complete:
                    self.on_ocr_complete(capture_id, text)
            except Exception:
                logger.exception("OCR işlenirken hata oluştu (capture_id=%s)", capture_id)
            finally:
                self._queue.task_done()
