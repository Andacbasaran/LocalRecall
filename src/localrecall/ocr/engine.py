"""RapidOCR (ONNX Runtime CPU) wrapper with non-ASCII PIL decoding, thread caps, backfill & PII shield."""

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

from localrecall.capture.pii import (
    PII_MODE_REDACT_AND_BLUR,
    PII_MODE_SKIP,
    PIIRedactor,
)
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OCRBox:
    """Normalized [0..1] OCR bounding box on the capture image."""

    text: str
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0


@dataclass(slots=True)
class OCRResult:
    """Extracted text and normalized bounding boxes from an image."""

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
    """RapidOCR ONNX CPU engine (lazy-load, 0 MB VRAM, thread-capped, Unicode path safe)."""

    def __init__(
        self,
        min_confidence: float = 0.45,
        intra_threads: int = 2,
        inter_threads: int = 1,
    ) -> None:
        self.min_confidence = min_confidence
        self.intra_threads = max(1, int(intra_threads))
        self.inter_threads = max(1, int(inter_threads))
        self._engine = None
        self._lock = threading.Lock()

    def set_threads(self, intra_threads: int, inter_threads: int = 1) -> None:
        intra = max(1, int(intra_threads))
        inter = max(1, int(inter_threads))
        if intra == self.intra_threads and inter == self.inter_threads:
            return
        with self._lock:
            self.intra_threads = intra
            self.inter_threads = inter
            # Re-initialize lazily with new CPU thread budget
            self._engine = None

    def _get_engine(self):
        with self._lock:
            if self._engine is None:
                from rapidocr_onnxruntime import RapidOCR

                try:
                    self._engine = RapidOCR(
                        intra_op_num_threads=self.intra_threads,
                        inter_op_num_threads=self.inter_threads,
                    )
                except TypeError:
                    self._engine = RapidOCR()
                logger.info(
                    "RapidOCR (ONNX CPU) loaded (intra=%d, inter=%d, 0 MB VRAM).",
                    self.intra_threads,
                    self.inter_threads,
                )
            return self._engine

    def _ensure_loaded(self) -> None:
        self._get_engine()

    def extract(self, image_source: Path | str | Image.Image | np.ndarray) -> OCRResult:
        """
        Extracts text and normalized bounding boxes.
        Always decodes file paths via PIL -> RGB NumPy array to prevent Windows non-ASCII
        path crashes in OpenCV/RapidOCR (Bug #3 fix).
        """
        engine = self._get_engine()
        assert engine is not None

        if isinstance(image_source, Image.Image):
            rgb = image_source.convert("RGB")
            img_w, img_h = rgb.size
            img_input: np.ndarray = np.asarray(rgb)
        elif isinstance(image_source, (Path, str)):
            with Image.open(image_source) as opened:
                rgb = opened.convert("RGB")
                img_w, img_h = rgb.size
                img_input = np.asarray(rgb)
        else:
            img_h, img_w = int(image_source.shape[0]), int(image_source.shape[1])
            img_input = image_source

        raw_result, _ = engine(img_input)
        if not raw_result or img_w <= 0 or img_h <= 0:
            return OCRResult(text="", boxes=[])

        lines: list[str] = []
        boxes: list[OCRBox] = []
        for item in raw_result:
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
        return self.extract(image_source).text


class OCRWorker:
    """Asynchronous background OCR queue with startup backfill and automatic PII redaction."""

    def __init__(
        self,
        db: Database,
        engine: OCREngine,
        media: MediaStore | None = None,
        pii_redactor: PIIRedactor | None = None,
        on_ocr_complete: Callable[[int, str], None] | None = None,
        max_queue_size: int = 256,
    ) -> None:
        self.db = db
        self.engine = engine
        self.media = media
        self.pii_redactor = pii_redactor or PIIRedactor()
        self.on_ocr_complete = on_ocr_complete
        self._queue: queue.Queue[tuple[int, Path] | None] = queue.Queue(maxsize=max_queue_size)
        self._queued_ids: set[int] = set()
        self._queued_lock = threading.Lock()
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
        if self._stop_event.is_set():
            return False
        with self._queued_lock:
            if capture_id in self._queued_ids:
                return True
            try:
                self._queue.put_nowait((capture_id, image_path))
                self._queued_ids.add(capture_id)
                return True
            except queue.Full:
                logger.warning("OCR queue full, capture skipped for now: id=%s", capture_id)
                return False

    def backfill_pending(self, resolve_path: Callable[[str], Path], limit: int = 200) -> int:
        """
        Resumes un-OCR'd captures left over from previous sessions or queue drops (Bug #4 fix).
        """
        pending = self.db.get_pending_ocr(limit=limit)
        enqueued = 0
        for rec in pending:
            try:
                img_path = resolve_path(rec.image_path)
            except ValueError:
                self.db.update_ocr_text(rec.id, "", ocr_boxes="[]")
                continue
            if not img_path.exists():
                self.db.update_ocr_text(rec.id, "", ocr_boxes="[]")
                continue
            if self.enqueue(rec.id, img_path):
                enqueued += 1
        if enqueued:
            logger.info("Backfilled %d pending captures into OCR queue.", enqueued)
        return enqueued

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
                    self.db.update_ocr_text(capture_id, "", ocr_boxes="[]")
                    continue

                res = self.engine.extract(image_path)
                final_text = res.text
                final_boxes = res.boxes
                pii_redacted = False
                new_file_size: int | None = None

                if self.pii_redactor and self.pii_redactor.is_enabled:
                    clean_text, text_dets = self.pii_redactor.redact_text(res.text)
                    clean_boxes, blur_boxes, box_dets = self.pii_redactor.redact_ocr_boxes(res.boxes)
                    all_dets = text_dets if len(text_dets) >= len(box_dets) else box_dets

                    if all_dets:
                        self.db.increment_metric("pii_redactions_count", len(all_dets))
                        self.db.increment_metric("privacy_blocks_count", 1)

                        if self.pii_redactor.mode == PII_MODE_SKIP:
                            rel_path = self.db.delete_capture(capture_id)
                            if rel_path and self.media:
                                self.media.delete_image(rel_path)
                            elif image_path.exists():
                                try:
                                    image_path.unlink()
                                except OSError:
                                    pass
                            if self.on_ocr_complete:
                                self.on_ocr_complete(capture_id, "")
                            continue

                        pii_redacted = True
                        final_text = clean_text
                        final_boxes = clean_boxes

                        if (
                            self.pii_redactor.mode == PII_MODE_REDACT_AND_BLUR
                            and blur_boxes
                            and self.media is not None
                        ):
                            rec = self.db.get_capture(capture_id)
                            if rec and rec.image_path:
                                with Image.open(image_path) as opened:
                                    blurred = PIIRedactor.blur_image_regions(opened, blur_boxes)
                                new_file_size = self.media.overwrite_image(rec.image_path, blurred)

                final_result = OCRResult(text=final_text, boxes=final_boxes)
                self.db.update_ocr_text(
                    capture_id,
                    final_result.text,
                    ocr_boxes=final_result.boxes_to_json(),
                    pii_redacted=pii_redacted,
                    file_size_bytes=new_file_size,
                )
                if self.on_ocr_complete:
                    self.on_ocr_complete(capture_id, final_result.text)
            except Exception:
                logger.exception("OCR processing failed (capture_id=%s)", capture_id)
            finally:
                with self._queued_lock:
                    self._queued_ids.discard(capture_id)
                self._queue.task_done()
