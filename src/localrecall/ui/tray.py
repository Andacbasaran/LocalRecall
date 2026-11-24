"""Cross-platform System Tray manager with localized EN/TR menu & timed pause actions."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from localrecall.i18n import LanguageManager

from .widgets import create_app_icon


class SystemTrayManager(QObject):
    """Background system tray icon and quick-access menu."""

    open_requested = pyqtSignal()
    toggle_pause_requested = pyqtSignal()
    pause_timed_requested = pyqtSignal(int)
    capture_now_requested = pyqtSignal()
    purge_recent_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, i18n: LanguageManager | None = None, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n or LanguageManager("en")
        self._paused = False
        self.tray = QSystemTrayIcon(create_app_icon(paused=False), parent)

        self.menu = QMenu()
        self.open_action = QAction(self.menu)
        self.open_action.triggered.connect(self.open_requested.emit)
        self.menu.addAction(self.open_action)

        self.menu.addSeparator()

        self.pause_action = QAction(self.menu)
        self.pause_action.triggered.connect(self.toggle_pause_requested.emit)
        self.menu.addAction(self.pause_action)

        self.pause_15_action = QAction(self.menu)
        self.pause_15_action.triggered.connect(lambda: self.pause_timed_requested.emit(15))
        self.menu.addAction(self.pause_15_action)

        self.pause_60_action = QAction(self.menu)
        self.pause_60_action.triggered.connect(lambda: self.pause_timed_requested.emit(60))
        self.menu.addAction(self.pause_60_action)

        self.capture_now_action = QAction(self.menu)
        self.capture_now_action.triggered.connect(self.capture_now_requested.emit)
        self.menu.addAction(self.capture_now_action)

        self.purge_recent_action = QAction(self.menu)
        self.purge_recent_action.triggered.connect(self.purge_recent_requested.emit)
        self.menu.addAction(self.purge_recent_action)

        self.menu.addSeparator()

        self.settings_action = QAction(self.menu)
        self.settings_action.triggered.connect(self.settings_requested.emit)
        self.menu.addAction(self.settings_action)

        self.menu.addSeparator()

        self.quit_action = QAction(self.menu)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self.retranslate()

    @property
    def is_available(self) -> bool:
        try:
            return bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            return False

    def retranslate(self) -> None:
        t = self.i18n.t
        self.open_action.setText(t("tray_open"))
        self.pause_action.setText(t("tray_resume") if self._paused else t("tray_pause"))
        self.pause_15_action.setText(t("tray_pause_15"))
        self.pause_60_action.setText(t("tray_pause_60"))
        self.capture_now_action.setText(t("tray_capture"))
        self.purge_recent_action.setText(t("tray_purge_15"))
        self.settings_action.setText(t("tray_settings"))
        self.quit_action.setText(t("tray_quit"))
        self.tray.setToolTip(t("tray_tip_paused") if self._paused else t("tray_tip_recording"))

    def show(self) -> None:
        if self.is_available:
            self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self.tray.setIcon(create_app_icon(paused=self._paused))
        self.retranslate()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()
