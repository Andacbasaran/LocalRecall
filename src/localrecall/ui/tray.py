"""System Tray (Sistem Tepsisi) ikonu ve hızlı erişim menüsü."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .theme import create_app_icon


class SystemTrayManager(QObject):
    """Arka planda çalışan LocalRecall için sistem tepsisi yöneticisi."""

    open_requested = pyqtSignal()
    toggle_pause_requested = pyqtSignal()
    capture_now_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paused = False
        self.tray = QSystemTrayIcon(create_app_icon(paused=False), parent)
        self.tray.setToolTip("LocalRecall — İzleniyor")

        menu = QMenu()
        self.open_action = QAction("LocalRecall'ı Aç", menu)
        self.open_action.triggered.connect(self.open_requested.emit)
        menu.addAction(self.open_action)

        menu.addSeparator()

        self.pause_action = QAction("Yakalamayı Duraklat", menu)
        self.pause_action.triggered.connect(self.toggle_pause_requested.emit)
        menu.addAction(self.pause_action)

        self.capture_now_action = QAction("Şimdi Yakala", menu)
        self.capture_now_action.triggered.connect(self.capture_now_requested.emit)
        menu.addAction(self.capture_now_action)

        self.settings_action = QAction("Ayarlar…", menu)
        self.settings_action.triggered.connect(self.settings_requested.emit)
        menu.addAction(self.settings_action)

        menu.addSeparator()

        self.quit_action = QAction("Çıkış", menu)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(self.quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.tray.setIcon(create_app_icon(paused=paused))
        if paused:
            self.pause_action.setText("Yakalamayı Devam Ettir")
            self.tray.setToolTip("LocalRecall — Duraklatıldı")
        else:
            self.pause_action.setText("Yakalamayı Duraklat")
            self.tray.setToolTip("LocalRecall — İzleniyor")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()
