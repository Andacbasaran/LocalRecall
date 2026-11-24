"""Background capture service: MSS + Idle Sleep + Privacy Shield + Ring-Buffer Diff + OCR + PII."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable

from PIL import Image

from localrecall.config import AppConfig
from localrecall.hardware import (
    apply_thread_env_defaults,
    compute_runtime_tuning,
    detect_hardware_profile,
)
from localrecall.ocr.engine import OCREngine, OCRWorker
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore

from .diff import FrameDiffLock
from .pii import PIIRedactor
from .privacy import PrivacyFilter
from .window_info import (
    get_active_window_info,
    get_idle_seconds,
    has_screen_recording_permission,
    open_mss,
)

logger = logging.getLogger(__name__)


class CaptureService:
    """Monitors the screen at low CPU, filtering private windows, idle periods, and duplicate frames."""

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

        self.hw_profile = detect_hardware_profile()
        self.tuning = compute_runtime_tuning(self.hw_profile, config.cpu_profile)
        apply_thread_env_defaults(self.tuning)

        self.privacy = PrivacyFilter(
            blocked_processes=config.blocked_processes,
            blocked_title_keywords=config.blocked_title_keywords,
            password_manager_guard=config.password_manager_guard,
            incognito_guard=config.incognito_guard,
        )
        self.diff_lock = FrameDiffLock(
            threshold=config.diff_threshold,
            history_size=config.diff_history_size,
        )
        self.pii_redactor = PIIRedactor(mode=config.pii_redaction_mode)
        self.ocr_engine = OCREngine(
            min_confidence=config.ocr_min_confidence,
            intra_threads=self.tuning.ocr_intra_threads,
            inter_threads=self.tuning.ocr_inter_threads,
        )
        self.ocr_worker = OCRWorker(
            db=db,
            engine=self.ocr_engine,
            media=media,
            pii_redactor=self.pii_redactor,
            on_ocr_complete=self._handle_ocr_complete,
        )

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._resume_at_monotonic: float | None = None
        if config.pause_on_start:
            self._pause_event.set()
        self._thread: threading.Thread | None = None
        self._was_idle = False
        self._permission_warned = False
        self._last_maintenance_ts = 0.0

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def pause_remaining_seconds(self) -> int:
        if not self.is_paused or self._resume_at_monotonic is None:
            return 0
        rem = self._resume_at_monotonic - time.monotonic()
        return max(0, int(rem))

    def apply_config(self, config: AppConfig) -> None:
        self.config = config
        self.tuning = compute_runtime_tuning(self.hw_profile, config.cpu_profile)
        apply_thread_env_defaults(self.tuning)
        self.privacy.update_rules(
            config.blocked_processes,
            config.blocked_title_keywords,
            password_manager_guard=config.password_manager_guard,
            incognito_guard=config.incognito_guard,
        )
        self.diff_lock.threshold = config.diff_threshold
        self.diff_lock.set_history_size(config.diff_history_size)
        self.media.quality = config.webp_quality
        self.media.max_width = config.max_image_width
        self.pii_redactor.set_mode(config.pii_redaction_mode)
        self.ocr_engine.min_confidence = config.ocr_min_confidence
        self.ocr_engine.set_threads(self.tuning.ocr_intra_threads, self.tuning.ocr_inter_threads)
        if config.ocr_enabled and self.is_running:
            self.ocr_worker.start()

    def pause(self) -> None:
        self._resume_at_monotonic = None
        self._pause_event.set()
        self._emit_status("Paused")

    def pause_for_minutes(self, minutes: int) -> None:
        self._resume_at_monotonic = time.monotonic() + (max(1, int(minutes)) * 60.0)
        self._pause_event.set()
        self._emit_status(f"Paused for {minutes}m")

    def resume(self) -> None:
        self._resume_at_monotonic = None
        self._pause_event.clear()
        self._emit_status("Recording")

    def toggle_pause(self) -> bool:
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
            # Resume any unfinished OCR items from prior runs (Bug #4 fix)
            self.ocr_worker.backfill_pending(self.media.resolve_path)
        self._thread = threading.Thread(target=self._loop, name="LocalRecall-Capture", daemon=True)
        self._thread.start()
        self._emit_status("Paused" if self.is_paused else "Recording")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.ocr_worker.stop()
        self._emit_status("Stopped")

    def capture_once(self, force: bool = False) -> int | None:
        """Captures a single frame if not idle, blocked by privacy, or perceptually duplicated."""
        if not has_screen_recording_permission():
            if not self._permission_warned:
                self._permission_warned = True
                self._emit_status("Screen Recording permission required")
            return None
        self._permission_warned = False

        if not force and self.config.idle_pause_sec > 0:
            idle_sec = get_idle_seconds()
            if idle_sec >= self.config.idle_pause_sec:
                if not self._was_idle:
                    self._was_idle = True
                    self._emit_status(f"Idle sleep ({int(idle_sec)}s)")
                return None
            self._was_idle = False

        window = get_active_window_info()
        skip, reason = self.privacy.should_skip(window)
        if skip:
            self.db.increment_metric("privacy_blocks_count", 1)
            self._emit_status(f"Privacy Shield blocked ({reason})")
            return None

        with open_mss() as sct:
            monitors = sct.monitors
            idx = self.config.monitor_index
            if idx < 0 or idx >= len(monitors):
                idx = 1 if len(monitors) > 1 else 0
            raw = sct.grab(monitors[idx])
            image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        self.db.increment_metric("dedup_checked_count", 1)
        if not force:
            changed, _score = self.diff_lock.has_changed(image)
            if not changed:
                self.db.increment_metric("dedup_skipped_count", 1)
                return None
        else:
            self.diff_lock.has_changed(image)

        now = datetime.now()
        rel_path, width, height, size_bytes = self.media.save_image_with_size(image, timestamp=now)
        capture_id = self.db.insert_capture(
            image_path=rel_path,
            app_name=window.process_name,
            window_title=window.window_title,
            width=width,
            height=height,
            ocr_text="",
            ocr_done=not self.config.ocr_enabled,
            timestamp=now,
            file_size_bytes=size_bytes,
        )

        if self.config.ocr_enabled:
            self.ocr_worker.enqueue(capture_id, self.media.resolve_path(rel_path))

        if self.on_capture:
            self.on_capture(capture_id)

        self._emit_status(f"Captured: {window.process_name or 'Screen'} ({now.strftime('%H:%M:%S')})")
        return capture_id

    def purge_last_minutes(self, minutes: int = 15) -> int:
        paths = self.db.purge_last_minutes(minutes)
        for rel in paths:
            self.media.delete_image(rel)
        if paths:
            self.diff_lock.reset()
        return len(paths)

    def purge_today(self) -> int:
        paths = self.db.purge_today()
        for rel in paths:
            self.media.delete_image(rel)
        if paths:
            self.diff_lock.reset()
        return len(paths)

    def purge_app(self, app_name: str) -> int:
        paths = self.db.purge_by_app(app_name)
        for rel in paths:
            self.media.delete_image(rel)
        if paths:
            self.diff_lock.reset()
        return len(paths)

    def run_retention_cleanup(self) -> int:
        total_removed = 0
        old_paths = self.db.purge_older_than(self.config.retention_days)
        for rel in old_paths:
            self.media.delete_image(rel)
        total_removed += len(old_paths)

        # Optional OCR-Only Archival Mode
        if self.config.archive_images_after_days > 0:
            archived_paths = self.db.archive_images_older_than(self.config.archive_images_after_days)
            for rel in archived_paths:
                self.media.delete_image(rel)

        # Optional Storage Quota Cap (FIFO)
        if self.config.max_storage_gb > 0:
            max_bytes = int(self.config.max_storage_gb * 1024 * 1024 * 1024)
            quota_paths = self.db.enforce_storage_quota(max_bytes)
            for rel in quota_paths:
                self.media.delete_image(rel)
            total_removed += len(quota_paths)

        return total_removed

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
                logger.info("Retention/quota cleanup removed %d captures.", purged)
            self._last_maintenance_ts = time.monotonic()
        except Exception:
            logger.exception("Startup cleanup error.")

        while not self._stop_event.is_set():
            # Check timed auto-resume
            if self._pause_event.is_set() and self._resume_at_monotonic is not None:
                if time.monotonic() >= self._resume_at_monotonic:
                    self.resume()

            if not self._pause_event.is_set():
                try:
                    self.capture_once(force=False)
                except Exception:
                    logger.exception("Capture loop error.")

            # Run periodic quota/retention maintenance every 10 minutes
            if time.monotonic() - self._last_maintenance_ts >= 600.0:
                try:
                    self.run_retention_cleanup()
                except Exception:
                    logger.exception("Periodic maintenance error.")
                self._last_maintenance_ts = time.monotonic()

            self._stop_event.wait(timeout=max(0.5, float(self.config.capture_interval_sec)))
