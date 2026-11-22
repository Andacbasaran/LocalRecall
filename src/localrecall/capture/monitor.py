"""Arka plan ekran yakalama servisi (mss + Idle Kontrol + PrivacyFilter + FrameDiffLock + OCR)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable

import mss
from PIL import Image

from localrecall.config import AppConfig
from localrecall.ocr.engine import OCREngine, OCRWorker
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore

from .diff import FrameDiffLock
from .privacy import PrivacyFilter
from .window_info import get_active_window_info, get_idle_seconds

logger = logging.getLogger(__name__)


class CaptureService:
    """Belirli aralıklarla ekranı izler; gizlilik, boşta kalma ve Frame Diff Lock kontrolünden geçenleri kaydeder."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        media: MediaStore,
        on_capture: Callable[[int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.media = media
        self.on_capture = on_capture
        self.on_status = on_status

        self.privacy = PrivacyFilter(
            blocked_processes=config.blocked_processes,
            blocked_title_keywords=config.blocked_title_keywords,
        )
        self.diff_lock = FrameDiffLock(threshold=config.diff_threshold)
        self.ocr_engine = OCREngine(min_confidence=config.ocr_min_confidence)
        self.ocr_worker = OCRWorker(
            db=db,
            engine=self.ocr_engine,
            on_ocr_complete=self._handle_ocr_complete,
        )

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        if config.pause_on_start:
            self._pause_event.set()
        self._thread: threading.Thread | None = None
        self._was_idle = False

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def apply_config(self, config: AppConfig) -> None:
        """Güncellenen ayarları canlı olarak uygular."""
        self.config = config
        self.privacy.update_rules(config.blocked_processes, config.blocked_title_keywords)
        self.diff_lock.threshold = config.diff_threshold
        self.media.quality = config.webp_quality
        self.media.max_width = config.max_image_width
        self.ocr_engine.min_confidence = config.ocr_min_confidence
        if config.ocr_enabled and self.is_running:
            self.ocr_worker.start()

    def pause(self) -> None:
        self._pause_event.set()
        self._emit_status("Duraklatıldı")

    def resume(self) -> None:
        self._pause_event.clear()
        self._emit_status("İzleniyor")

    def toggle_pause(self) -> bool:
        """Duraklatma durumunu tersine çevirir ve yeni is_paused değerini döndürür."""
        if self.is_paused:
            self.resume()
        else:
            self.pause()
        return self.is_paused

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        if self.config.ocr_enabled:
            self.ocr_worker.start()
        self._thread = threading.Thread(target=self._loop, name="LocalRecall-Capture", daemon=True)
        self._thread.start()
        self._emit_status("Duraklatıldı" if self.is_paused else "İzleniyor")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.ocr_worker.stop()
        self._emit_status("Durduruldu")

    def capture_once(self, force: bool = False) -> int | None:
        """Tek seferlik yakalama dener. Kaydedilirse capture_id, atlanırsa None döndürür."""
        if not force and self.config.idle_pause_sec > 0:
            idle_sec = get_idle_seconds()
            if idle_sec >= self.config.idle_pause_sec:
                if not self._was_idle:
                    self._was_idle = True
                    self._emit_status(f"Kullanıcı boşta ({int(idle_sec)} sn) — uyku modu")
                return None
            self._was_idle = False

        window = get_active_window_info()
        skip, reason = self.privacy.should_skip(window)
        if skip:
            self._emit_status(f"Gizlilik filtresi aktif ({reason})")
            return None

        with mss.mss() as sct:
            monitors = sct.monitors
            idx = self.config.monitor_index
            if idx < 0 or idx >= len(monitors):
                idx = 1 if len(monitors) > 1 else 0
            raw = sct.grab(monitors[idx])
            image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        if not force:
            changed, _score = self.diff_lock.has_changed(image)
            if not changed:
                return None
        else:
            self.diff_lock.has_changed(image)

        now = datetime.now()
        rel_path, width, height = self.media.save_image(image, timestamp=now)
        capture_id = self.db.insert_capture(
            image_path=rel_path,
            app_name=window.process_name,
            window_title=window.window_title,
            width=width,
            height=height,
            ocr_text="",
            ocr_done=not self.config.ocr_enabled,
            timestamp=now,
        )

        if self.config.ocr_enabled:
            self.ocr_worker.enqueue(capture_id, self.media.resolve_path(rel_path))

        if self.on_capture:
            self.on_capture(capture_id)

        self._emit_status(f"Yakalandı: {window.process_name or 'Ekran'} ({now.strftime('%H:%M:%S')})")
        return capture_id

    def purge_last_minutes(self, minutes: int = 15) -> int:
        """Son N dakikadaki tüm kayıtları veritabanı ve diskten anında siler."""
        paths = self.db.purge_last_minutes(minutes)
        for rel in paths:
            self.media.delete_image(rel)
        if paths:
            self.diff_lock.reset()
        return len(paths)

    def run_retention_cleanup(self) -> int:
        """Saklama süresini aşan eski kayıtları veritabanı ve diskten temizler."""
        old_paths = self.db.purge_older_than(self.config.retention_days)
        for rel in old_paths:
            self.media.delete_image(rel)
        return len(old_paths)

    def _handle_ocr_complete(self, capture_id: int, _text: str) -> None:
        if self.on_capture:
            self.on_capture(capture_id)

    def _emit_status(self, message: str) -> None:
        if self.on_status:
            self.on_status(message)

    def _loop(self) -> None:
        try:
            purged = self.run_retention_cleanup()
            if purged:
                logger.info("Saklama süresi dolan %d kayıt temizlendi.", purged)
        except Exception:
            logger.exception("Başlangıç temizliği sırasında hata.")

        while not self._stop_event.is_set():
            if not self._pause_event.is_set():
                try:
                    self.capture_once(force=False)
                except Exception:
                    logger.exception("Ekran yakalama döngüsünde hata.")
            self._stop_event.wait(timeout=max(0.5, float(self.config.capture_interval_sec)))
