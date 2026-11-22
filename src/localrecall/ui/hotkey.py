"""Windows global kısayol tuşu yöneticisi (Win32 RegisterHotKey + Qt NativeEventFilter)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_KEY_MAP: dict[str, int] = {
    "space": 0x20,
    "return": 0x0D,
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}


def parse_hotkey(shortcut: str) -> tuple[int, int] | None:
    """'Ctrl+Shift+Space' gibi bir kısayolu (modifiers, vk_code) çiftine çevirir."""
    parts = [p.strip().lower() for p in shortcut.split("+") if p.strip()]
    if not parts:
        return None

    mods = MOD_NOREPEAT
    vk: int | None = None
    for part in parts:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "alt":
            mods |= MOD_ALT
        elif part in ("win", "meta", "super"):
            mods |= MOD_WIN
        elif part in _KEY_MAP:
            vk = _KEY_MAP[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            return None

    if vk is None or mods == MOD_NOREPEAT:
        return None
    return mods, vk


class _WinHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, callback) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG" or event_type == b"windows_dispatcher_MSG":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    self._callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


class GlobalHotkeyManager(QObject):
    """Sistem genelinde çalışan kısayol tuşu yöneticisi (Windows)."""

    triggered = pyqtSignal()

    def __init__(self, app, hotkey_id: int = 0x5245, parent=None) -> None:
        super().__init__(parent)
        self._app = app
        self._hotkey_id = hotkey_id
        self._registered = False
        self._filter = _WinHotkeyFilter(hotkey_id, self.triggered.emit)

    def register(self, shortcut: str) -> bool:
        self.unregister()
        if sys.platform != "win32":
            return False

        parsed = parse_hotkey(shortcut)
        if not parsed:
            logger.warning("Geçersiz global kısayol formatı: %s", shortcut)
            return False

        mods, vk = parsed
        ok = bool(ctypes.windll.user32.RegisterHotKey(None, self._hotkey_id, mods, vk))
        if ok:
            self._app.installNativeEventFilter(self._filter)
            self._registered = True
            logger.info("Global kısayol kaydedildi: %s", shortcut)
        else:
            logger.warning("Global kısayol kaydedilemedi (başka uygulama kullanıyor olabilir): %s", shortcut)
        return ok

    def unregister(self) -> None:
        if not self._registered:
            return
        try:
            self._app.removeNativeEventFilter(self._filter)
            if sys.platform == "win32":
                ctypes.windll.user32.UnregisterHotKey(None, self._hotkey_id)
        except Exception:
            pass
        self._registered = False
