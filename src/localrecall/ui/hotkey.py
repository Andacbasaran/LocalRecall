"""Cross-platform Global Hotkey Manager (Win32 RegisterHotKey, macOS Carbon / Qt fallback, Linux)."""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut

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

# macOS Carbon virtual key codes & modifiers
_CARBON_CMD_KEY = 1 << 8
_CARBON_SHIFT_KEY = 1 << 9
_CARBON_OPT_KEY = 1 << 11
_CARBON_CTRL_KEY = 1 << 12

_MAC_VK_MAP: dict[str, int] = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06,
    "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E,
    "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "6": 0x16, "5": 0x17, "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F,
    "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D,
    "m": 0x2E, "space": 0x31, "return": 0x24, "enter": 0x24, "tab": 0x30,
    "esc": 0x35, "escape": 0x35, "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76,
    "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D,
    "f11": 0x67, "f12": 0x6F,
}


def parse_hotkey(shortcut: str) -> tuple[int, int] | None:
    """Parses strings like 'Ctrl+Shift+Space' or 'Cmd+Shift+Space' into Win32 (mods, vk)."""
    parts = [p.strip().lower() for p in (shortcut or "").split("+") if p.strip()]
    if not parts:
        return None

    mods = MOD_NOREPEAT
    vk: int | None = None
    for part in parts:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("alt", "opt", "option"):
            mods |= MOD_ALT
        elif part in ("win", "meta", "super", "cmd", "command"):
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


def parse_macos_hotkey(shortcut: str) -> tuple[int, int] | None:
    """Parses hotkey strings into macOS Carbon (modifiers, virtual_key_code)."""
    parts = [p.strip().lower() for p in (shortcut or "").split("+") if p.strip()]
    if not parts:
        return None

    mods = 0
    vk: int | None = None
    for part in parts:
        if part in ("cmd", "command", "meta", "super"):
            mods |= _CARBON_CMD_KEY
        elif part in ("ctrl", "control"):
            mods |= _CARBON_CTRL_KEY
        elif part == "shift":
            mods |= _CARBON_SHIFT_KEY
        elif part in ("alt", "opt", "option"):
            mods |= _CARBON_OPT_KEY
        elif part in _MAC_VK_MAP:
            vk = _MAC_VK_MAP[part]
        else:
            return None

    if vk is None or mods == 0:
        return None
    return mods, vk


def normalize_qt_shortcut(shortcut: str) -> str:
    """Converts shortcut strings into Qt QKeySequence syntax."""
    parts = [p.strip() for p in (shortcut or "").split("+") if p.strip()]
    out: list[str] = []
    for p in parts:
        low = p.lower()
        if low in ("cmd", "command"):
            out.append("Ctrl" if sys.platform == "darwin" else "Meta")
        elif low in ("ctrl", "control"):
            out.append("Meta" if sys.platform == "darwin" else "Ctrl")
        elif low in ("opt", "option"):
            out.append("Alt")
        else:
            out.append(p.capitalize() if len(p) > 1 else p.upper())
    return "+".join(out)


class _WinHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, callback) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                import ctypes.wintypes as wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    self._callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


class _CarbonEventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _CarbonEventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class GlobalHotkeyManager(QObject):
    """Cross-platform Global Hotkey Manager with graceful Qt QShortcut fallback."""

    triggered = pyqtSignal()

    def __init__(self, app, hotkey_id: int = 0x5245, parent=None, target_widget=None) -> None:
        super().__init__(parent)
        self._app = app
        self._hotkey_id = hotkey_id
        self._target_widget = target_widget
        self._registered = False
        self._backend = "none"
        self._filter = _WinHotkeyFilter(hotkey_id, self.triggered.emit)
        self._qt_shortcut: QShortcut | None = None
        self._carbon_hotkey_ref = ctypes.c_void_p(0)
        self._carbon_handler_ref = ctypes.c_void_p(0)
        self._carbon_cb = None
        self._carbon_lib = None

    @property
    def backend(self) -> str:
        return self._backend

    def set_target_widget(self, widget) -> None:
        self._target_widget = widget

    def _configure_win32_hotkey_api(self):
        import ctypes.wintypes as wintypes

        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        return user32

    def _register_macos_carbon(self, shortcut: str) -> bool:
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            return False
        parsed = parse_macos_hotkey(shortcut)
        if not parsed:
            return False
        mods, vk = parsed
        try:
            carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            carbon.GetApplicationEventTarget.argtypes = []
            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p

            cb_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            carbon.InstallEventHandler.argtypes = [
                ctypes.c_void_p,
                cb_type,
                ctypes.c_uint32,
                ctypes.POINTER(_CarbonEventTypeSpec),
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            carbon.InstallEventHandler.restype = ctypes.c_int32
            carbon.RegisterEventHotKey.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                _CarbonEventHotKeyID,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            carbon.RegisterEventHotKey.restype = ctypes.c_int32
            carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
            carbon.UnregisterEventHotKey.restype = ctypes.c_int32
            carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
            carbon.RemoveEventHandler.restype = ctypes.c_int32

            def _on_carbon_event(_next_handler, _event_ref, _user_data):
                try:
                    self.triggered.emit()
                except Exception:
                    pass
                return 0

            self._carbon_cb = cb_type(_on_carbon_event)
            # kEventClassKeyboard = 'keyb' (0x6B657962), kEventHotKeyPressed = 5
            spec = _CarbonEventTypeSpec(0x6B657962, 5)
            target = carbon.GetApplicationEventTarget()
            if not target:
                return False

            handler_ref = ctypes.c_void_p(0)
            err = carbon.InstallEventHandler(
                target, self._carbon_cb, 1, ctypes.byref(spec), None, ctypes.byref(handler_ref)
            )
            if err != 0:
                return False

            hk_id = _CarbonEventHotKeyID(0x4C52434C, self._hotkey_id)  # 'LRCL'
            hk_ref = ctypes.c_void_p(0)
            err = carbon.RegisterEventHotKey(vk, mods, hk_id, target, 0, ctypes.byref(hk_ref))
            if err != 0:
                carbon.RemoveEventHandler(handler_ref)
                return False

            self._carbon_lib = carbon
            self._carbon_handler_ref = handler_ref
            self._carbon_hotkey_ref = hk_ref
            self._registered = True
            self._backend = "carbon"
            logger.info("macOS Carbon global hotkey registered: %s", shortcut)
            return True
        except Exception as exc:
            logger.debug("macOS Carbon hotkey unavailable, using Qt shortcut fallback: %s", exc)
            return False

    def _register_qt_fallback(self, shortcut: str) -> bool:
        if self._target_widget is None:
            return False
        qt_seq = normalize_qt_shortcut(shortcut)
        if not qt_seq:
            return False
        try:
            sc = QShortcut(QKeySequence(qt_seq), self._target_widget)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(self.triggered.emit)
            self._qt_shortcut = sc
            self._registered = True
            self._backend = "qt_shortcut"
            return True
        except Exception:
            return False

    def register(self, shortcut: str) -> bool:
        self.unregister()
        if not shortcut or not shortcut.strip():
            return False

        if sys.platform == "win32":
            parsed = parse_hotkey(shortcut)
            if not parsed:
                logger.warning("Invalid global hotkey format: %s", shortcut)
                return False
            mods, vk = parsed
            try:
                user32 = self._configure_win32_hotkey_api()
                ok = bool(user32.RegisterHotKey(None, self._hotkey_id, mods, vk))
                if ok:
                    self._app.installNativeEventFilter(self._filter)
                    self._registered = True
                    self._backend = "win32"
                    logger.info("Win32 global hotkey registered: %s", shortcut)
                    return True
            except Exception:
                logger.exception("Win32 RegisterHotKey error.")
            return self._register_qt_fallback(shortcut)

        if sys.platform == "darwin":
            if self._register_macos_carbon(shortcut):
                return True
            return self._register_qt_fallback(shortcut)

        # Linux / other: safe Qt application shortcut fallback
        return self._register_qt_fallback(shortcut)

    def unregister(self) -> None:
        if not self._registered:
            return
        try:
            if self._backend == "win32" and sys.platform == "win32":
                self._app.removeNativeEventFilter(self._filter)
                user32 = self._configure_win32_hotkey_api()
                user32.UnregisterHotKey(None, self._hotkey_id)
            elif self._backend == "carbon" and self._carbon_lib is not None:
                if self._carbon_hotkey_ref.value:
                    self._carbon_lib.UnregisterEventHotKey(self._carbon_hotkey_ref)
                if self._carbon_handler_ref.value:
                    self._carbon_lib.RemoveEventHandler(self._carbon_handler_ref)
                self._carbon_hotkey_ref = ctypes.c_void_p(0)
                self._carbon_handler_ref = ctypes.c_void_p(0)
            if self._qt_shortcut is not None:
                self._qt_shortcut.setEnabled(False)
                self._qt_shortcut.deleteLater()
                self._qt_shortcut = None
        except Exception:
            pass
        self._registered = False
        self._backend = "none"
