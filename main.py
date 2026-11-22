"""LocalRecall uygulama giriş noktası."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# src/ dizinini Python arama yoluna ekle
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt6.QtWidgets import QApplication

from localrecall.capture.monitor import CaptureService
from localrecall.config import AppConfig
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore
from localrecall.ui.main_window import MainWindow
from localrecall.ui.theme import DARK_STYLESHEET, create_app_icon
from localrecall.ui.tray import SystemTrayManager


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = AppConfig.load()
    db = Database(config.db_path)
    media = MediaStore(
        captures_dir=config.captures_dir,
        quality=config.webp_quality,
        max_width=config.max_image_width,
    )

    app = QApplication(sys.argv)
    app.setApplicationName("LocalRecall")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(DARK_STYLESHEET)
    app.setWindowIcon(create_app_icon(paused=config.pause_on_start))

    window_holder: list[MainWindow] = []

    def on_capture(capture_id: int) -> None:
        if window_holder:
            window_holder[0].capture_updated.emit(capture_id)

    def on_status(message: str) -> None:
        if window_holder:
            window_holder[0].status_updated.emit(message)

    capture_service = CaptureService(
        config=config,
        db=db,
        media=media,
        on_capture=on_capture,
        on_status=on_status,
    )

    window = MainWindow(
        config=config,
        db=db,
        media=media,
        capture_service=capture_service,
    )
    window_holder.append(window)

    tray = SystemTrayManager()
    tray.set_paused(capture_service.is_paused)
    tray.open_requested.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
    tray.toggle_pause_requested.connect(window.toggle_pause)
    tray.capture_now_requested.connect(window.capture_now)
    tray.settings_requested.connect(lambda: (window.showNormal(), window.open_settings()))
    window.pause_state_changed.connect(tray.set_paused)

    def shutdown() -> None:
        capture_service.stop()
        tray.hide()
        window.request_quit()
        db.close()
        app.quit()

    tray.quit_requested.connect(shutdown)
    tray.show()

    capture_service.start()
    window.show()

    exit_code = app.exec()
    capture_service.stop()
    db.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
