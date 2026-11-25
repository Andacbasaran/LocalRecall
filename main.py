"""LocalRecall v1.0.0 — Application Entry Point with Single-Instance Lock & Crash Logger."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from localrecall import __app_name__, __version__
from localrecall.capture.monitor import CaptureService
from localrecall.config import AppConfig
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore
from localrecall.ui.hotkey import GlobalHotkeyManager
from localrecall.ui.main_window import MainWindow
from localrecall.ui.theme import build_studio_stylesheet
from localrecall.ui.tray import SystemTrayManager
from localrecall.ui.widgets import create_app_icon

SINGLE_INSTANCE_KEY = "com.andacbasaran.localrecall.v1"
_MAX_CRASH_LOG_BYTES = 512 * 1024


def get_single_instance_key() -> str:
    """Return a per-user scoped QLocalServer name to prevent multi-user /tmp collisions."""
    if hasattr(os, "getuid"):
        ident = f"uid{os.getuid()}"
    else:
        user = getpass.getuser() or "default"
        ident = hashlib.sha256(user.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{SINGLE_INSTANCE_KEY}.{ident}"


def _append_crash_log(crash_log_path: Path, header: str, body: str) -> None:
    try:
        crash_log_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                os.chmod(crash_log_path.parent, 0o700)
            except OSError:
                pass
        if crash_log_path.exists() and crash_log_path.stat().st_size > _MAX_CRASH_LOG_BYTES:
            tail = crash_log_path.read_bytes()[-(_MAX_CRASH_LOG_BYTES // 2) :]
            crash_log_path.write_bytes(tail)
        with open(crash_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{header}\n{body}\n")
        if os.name == "posix":
            try:
                os.chmod(crash_log_path, 0o600)
            except OSError:
                pass
    except Exception:
        pass


def _install_crash_logger(crash_log_path: Path) -> None:
    def _handle_exception(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _append_crash_log(crash_log_path, f"=== Crash {stamp} (LocalRecall v{__version__}) ===", body)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        tname = args.thread.name if args.thread is not None else "unknown"
        body = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        _append_crash_log(
            crash_log_path,
            f"=== Thread Crash ({tname}) {stamp} (LocalRecall v{__version__}) ===",
            body,
        )
        threading.__excepthook__(args)

    sys.excepthook = _handle_exception
    threading.excepthook = _handle_thread_exception


def _notify_running_instance(socket_name: str | None = None) -> bool:
    """Returns True if an existing LocalRecall instance is already running and was signaled."""
    key = socket_name or get_single_instance_key()
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(250):
        sock.write(b"SHOW")
        sock.flush()
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def _start_instance_server(on_show_callback, socket_name: str | None = None) -> QLocalServer:
    key = socket_name or get_single_instance_key()
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(key):
        if not _notify_running_instance(key):
            QLocalServer.removeServer(key)
            server.listen(key)
    if server.isListening():
        def _on_new_connection() -> None:
            client = server.nextPendingConnection()
            if client is not None:
                client.waitForReadyRead(200)
                client.readAll()
                client.disconnectFromServer()
                client.deleteLater()
                on_show_callback()

        server.newConnection.connect(_on_new_connection)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LocalRecall v1.0.0 — 100% Offline, Privacy-First Smart Screen Memory"
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start minimized in the system tray without opening the main window.",
    )
    parser.add_argument(
        "--allow-multiple",
        action="store_true",
        help="Bypass the single-instance lock (useful for testing).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__app_name__} {__version__}",
    )
    args, qt_args = parser.parse_known_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = AppConfig.load()
    _install_crash_logger(config.crash_log_path)

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setStyleSheet(build_studio_stylesheet())
    app.setWindowIcon(create_app_icon(paused=config.pause_on_start))

    if not args.allow_multiple and _notify_running_instance():
        logging.info("Another LocalRecall instance is already active; signaled it to focus.")
        return 0

    db = Database(config.db_path)
    media = MediaStore(
        captures_dir=config.captures_dir,
        quality=config.webp_quality,
        max_width=config.max_image_width,
    )

    window_holder: list[MainWindow] = []

    def on_capture(capture_id: int) -> None:
        if window_holder:
            window_holder[0].capture_updated.emit(capture_id)

    def on_status(message: str) -> None:
        if window_holder:
            window_holder[0].status_updated.emit(message)

    def on_pause_changed(paused: bool) -> None:
        if window_holder:
            window_holder[0].external_pause_changed.emit(paused)

    capture_service = CaptureService(
        config=config,
        db=db,
        media=media,
        on_capture=on_capture,
        on_status=on_status,
        on_pause_changed=on_pause_changed,
    )

    window = MainWindow(
        config=config,
        db=db,
        media=media,
        capture_service=capture_service,
    )
    window_holder.append(window)

    instance_server = None
    if not args.allow_multiple:
        instance_server = _start_instance_server(window.bring_to_front_and_focus_search)

    # Cross-platform global hotkey
    hotkey_mgr = GlobalHotkeyManager(app, target_widget=window)
    hotkey_mgr.triggered.connect(window.bring_to_front_and_focus_search)

    # System Tray (safe on headless / tray-less Linux)
    tray = SystemTrayManager(i18n=window.i18n)

    def apply_config_hooks(cfg: AppConfig) -> None:
        hotkey_mgr.unregister()
        if cfg.global_hotkey_enabled and cfg.global_hotkey:
            hotkey_mgr.register(cfg.global_hotkey)
        app.setQuitOnLastWindowClosed(not (tray.is_available and cfg.minimize_to_tray))

    apply_config_hooks(config)
    window.config_changed.connect(apply_config_hooks)
    tray.set_paused(capture_service.is_paused)
    tray.open_requested.connect(window.bring_to_front_and_focus_search)
    tray.toggle_pause_requested.connect(window.toggle_pause)
    tray.pause_timed_requested.connect(window.pause_for_minutes)
    tray.capture_now_requested.connect(window.capture_now)
    tray.purge_recent_requested.connect(window.purge_last_15_minutes)
    tray.settings_requested.connect(window.open_settings)
    window.pause_state_changed.connect(tray.set_paused)
    window.language_changed.connect(lambda _lang: tray.retranslate())

    shutting_down = False

    def shutdown(quit_loop: bool = True) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        # Detach window callbacks FIRST so stop() never emits onto a closing/closed SQLite DB
        window_holder.clear()
        hotkey_mgr.unregister()
        capture_service.stop()
        tray.hide()
        if instance_server is not None:
            try:
                instance_server.close()
            except Exception:
                pass
        window.request_quit()
        db.close()
        if quit_loop:
            app.quit()

    tray.quit_requested.connect(lambda: shutdown(quit_loop=True))
    tray.show()

    capture_service.start()
    if not args.minimized or not tray.is_available:
        window.show()

    try:
        exit_code = app.exec()
    finally:
        shutdown(quit_loop=False)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
