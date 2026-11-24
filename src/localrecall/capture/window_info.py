"""Cross-platform active window inspection, idle time, screen permissions, and monitor listing."""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import mss


@dataclass(slots=True)
class ActiveWindowInfo:
    """Foreground active window metadata."""

    process_name: str
    window_title: str
    pid: int = 0


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


_win32_configured = False
_cg_lib: Any = None
_cg_configured = False


def _configure_win32_ctypes() -> tuple[Any, Any]:
    """Configures explicit 64-bit safe argtypes/restype on all Win32 ctypes calls."""
    global _win32_configured
    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not _win32_configured:
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND

        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int

        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
        user32.GetLastInputInfo.restype = wintypes.BOOL

        kernel32.GetTickCount.argtypes = []
        kernel32.GetTickCount.restype = wintypes.DWORD

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE

        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        _win32_configured = True
    return user32, kernel32


def _get_coregraphics() -> Any:
    """Lazy-loads macOS CoreGraphics framework via ctypes with proper signatures."""
    global _cg_lib, _cg_configured
    if _cg_configured:
        return _cg_lib
    _cg_configured = True
    if sys.platform != "darwin":
        return None
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_int32, ctypes.c_uint32]
        cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
        if hasattr(cg, "CGPreflightScreenCaptureAccess"):
            cg.CGPreflightScreenCaptureAccess.argtypes = []
            cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        if hasattr(cg, "CGRequestScreenCaptureAccess"):
            cg.CGRequestScreenCaptureAccess.argtypes = []
            cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        _cg_lib = cg
    except Exception:
        _cg_lib = None
    return _cg_lib


def has_screen_recording_permission() -> bool:
    """Returns True if screen capture permission is granted (checks CoreGraphics on macOS)."""
    if sys.platform != "darwin":
        return True
    cg = _get_coregraphics()
    if cg is None or not hasattr(cg, "CGPreflightScreenCaptureAccess"):
        return True
    try:
        return bool(cg.CGPreflightScreenCaptureAccess())
    except Exception:
        return True


def request_screen_recording_permission() -> bool:
    """Triggers macOS Screen Recording permission prompt via CoreGraphics."""
    if sys.platform != "darwin":
        return True
    cg = _get_coregraphics()
    if cg is None or not hasattr(cg, "CGRequestScreenCaptureAccess"):
        return True
    try:
        return bool(cg.CGRequestScreenCaptureAccess())
    except Exception:
        return False


def _get_linux_idle_seconds() -> float:
    # 1. Try xprintidle if available (X11)
    xprintidle = shutil.which("xprintidle")
    if xprintidle and os.environ.get("DISPLAY"):
        try:
            res = subprocess.run(
                [xprintidle],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return int(res.stdout.strip()) / 1000.0
        except Exception:
            pass

    # 2. Fallback: libXss via ctypes on X11
    if os.environ.get("DISPLAY"):
        try:
            class _XScreenSaverInfo(ctypes.Structure):
                _fields_ = [
                    ("window", ctypes.c_ulong),
                    ("state", ctypes.c_int),
                    ("kind", ctypes.c_int),
                    ("til_or_since", ctypes.c_ulong),
                    ("idle", ctypes.c_ulong),
                    ("event_mask", ctypes.c_ulong),
                ]

            x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            xss = ctypes.cdll.LoadLibrary("libXss.so.1")
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x11.XFree.argtypes = [ctypes.c_void_p]
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XScreenSaverInfo)
            xss.XScreenSaverQueryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.POINTER(_XScreenSaverInfo),
            ]
            xss.XScreenSaverQueryInfo.restype = ctypes.c_int

            dpy = x11.XOpenDisplay(None)
            if dpy:
                try:
                    info = xss.XScreenSaverAllocInfo()
                    if info:
                        try:
                            root = x11.XDefaultRootWindow(dpy)
                            if xss.XScreenSaverQueryInfo(dpy, root, info):
                                return float(info.contents.idle) / 1000.0
                        finally:
                            x11.XFree(info)
                finally:
                    x11.XCloseDisplay(dpy)
        except Exception:
            pass
    return 0.0


def get_idle_seconds() -> float:
    """Returns seconds since last keyboard/mouse input (Windows, macOS, Linux)."""
    if sys.platform == "win32":
        try:
            user32, kernel32 = _configure_win32_ctypes()
            info = _LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            if not user32.GetLastInputInfo(ctypes.byref(info)):
                return 0.0
            tick_now = int(kernel32.GetTickCount()) & 0xFFFFFFFF
            elapsed_ms = (tick_now - int(info.dwTime)) & 0xFFFFFFFF
            return elapsed_ms / 1000.0
        except Exception:
            return 0.0

    if sys.platform == "darwin":
        cg = _get_coregraphics()
        if cg is None:
            return 0.0
        try:
            # 0 = kCGEventSourceStateCombinedSessionState, 0xFFFFFFFF = kCGAnyInputEventType
            secs = float(cg.CGEventSourceSecondsSinceLastEventType(0, 0xFFFFFFFF))
            return max(0.0, secs)
        except Exception:
            return 0.0

    if sys.platform.startswith("linux"):
        return _get_linux_idle_seconds()

    return 0.0


def open_mss() -> Any:
    """Opens MSS screen capture context using modern mss.MSS() with mss.mss() fallback."""
    mss_cls = getattr(mss, "MSS", None)
    if callable(mss_cls):
        try:
            return mss_cls()
        except Exception:
            pass
    return mss.mss()


def list_monitors(lang: str = "en") -> list[tuple[int, str]]:
    """Returns available monitors as (mss_index, label) pairs."""
    result: list[tuple[int, str]] = []
    all_lbl = "Tüm Monitörler" if lang == "tr" else "All Monitors"
    mon_lbl = "Monitör" if lang == "tr" else "Monitor"
    primary_lbl = "Birincil" if lang == "tr" else "Primary"
    try:
        with open_mss() as sct:
            for idx, mon in enumerate(sct.monitors):
                w = mon.get("width", 0)
                h = mon.get("height", 0)
                if idx == 0:
                    result.append((0, f"{all_lbl} ({w}×{h})"))
                else:
                    label = f"{mon_lbl} {idx} ({w}×{h})"
                    if idx == 1:
                        label += f" — {primary_lbl}"
                    result.append((idx, label))
    except Exception:
        result.append((1, f"{mon_lbl} 1 ({primary_lbl})"))
    return result


def _get_macos_active_window() -> ActiveWindowInfo:
    # 1. Try NSWorkspace if PyObjC is installed (zero subprocess)
    app_name = ""
    pid = 0
    title = ""
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is not None:
            app_name = str(front.localizedName() or "")
            pid = int(front.processIdentifier() or 0)
    except Exception:
        pass

    # 2. Ultra-fast zero-permission fallback via lsappinfo
    if not app_name:
        try:
            front_res = subprocess.run(
                ["lsappinfo", "front"],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            asn = front_res.stdout.strip()
            if front_res.returncode == 0 and asn:
                info_res = subprocess.run(
                    ["lsappinfo", "info", "-only", "name", "-only", "pid", asn],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                    check=False,
                )
                if info_res.returncode == 0:
                    m_name = re.search(r'"LSDisplayName"="([^"]+)"', info_res.stdout)
                    if m_name:
                        app_name = m_name.group(1).strip()
                    m_pid = re.search(r'"pid"=(\d+)', info_res.stdout)
                    if m_pid:
                        pid = int(m_pid.group(1))
        except Exception:
            pass

    # 3. Try osascript for active window title (and app name if still empty)
    try:
        script = (
            'tell application "System Events"\n'
            "  set fp to first application process whose frontmost is true\n"
            "  set appName to name of fp\n"
            "  set appPid to unix id of fp\n"
            '  set winTitle to ""\n'
            "  try\n"
            "    set winTitle to name of front window of fp\n"
            "  end try\n"
            '  return appName & "|||" & (appPid as text) & "|||" & winTitle\n'
            "end tell"
        )
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=0.7,
            check=False,
        )
        if res.returncode == 0 and "|||" in res.stdout:
            parts = res.stdout.strip().split("|||", 2)
            if parts[0].strip() and not app_name:
                app_name = parts[0].strip()
            if len(parts) > 1 and parts[1].strip().isdigit() and pid == 0:
                pid = int(parts[1].strip())
            if len(parts) > 2:
                title = parts[2].strip()
    except Exception:
        pass

    return ActiveWindowInfo(process_name=app_name or "macOS", window_title=title, pid=pid)


def _get_linux_active_window() -> ActiveWindowInfo:
    if not os.environ.get("DISPLAY"):
        return ActiveWindowInfo(process_name="wayland", window_title="", pid=0)

    # 1. Try xdotool
    xdotool = shutil.which("xdotool")
    if xdotool:
        try:
            wid_res = subprocess.run(
                [xdotool, "getactivewindow"],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            wid = wid_res.stdout.strip()
            if wid_res.returncode == 0 and wid:
                pid = 0
                title = ""
                proc = ""
                pid_res = subprocess.run(
                    [xdotool, "getwindowpid", wid],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                    check=False,
                )
                if pid_res.returncode == 0 and pid_res.stdout.strip().isdigit():
                    pid = int(pid_res.stdout.strip())
                    comm_path = f"/proc/{pid}/comm"
                    if os.path.exists(comm_path):
                        with open(comm_path, "r", encoding="utf-8", errors="ignore") as f:
                            proc = f.read().strip()

                name_res = subprocess.run(
                    [xdotool, "getwindowname", wid],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                    check=False,
                )
                if name_res.returncode == 0:
                    title = name_res.stdout.strip()
                return ActiveWindowInfo(process_name=proc or "x11", window_title=title, pid=pid)
        except Exception:
            pass

    # 2. Fallback: xprop
    xprop = shutil.which("xprop")
    if xprop:
        try:
            root_res = subprocess.run(
                [xprop, "-root", "_NET_ACTIVE_WINDOW"],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            m = re.search(r"0x[0-9a-fA-F]+", root_res.stdout)
            if m and m.group(0) != "0x0":
                wid = m.group(0)
                info_res = subprocess.run(
                    [xprop, "-id", wid, "_NET_WM_PID", "_NET_WM_NAME", "WM_NAME"],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                    check=False,
                )
                pid = 0
                proc = ""
                title = ""
                m_pid = re.search(r"_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)", info_res.stdout)
                if m_pid:
                    pid = int(m_pid.group(1))
                    comm_path = f"/proc/{pid}/comm"
                    if os.path.exists(comm_path):
                        with open(comm_path, "r", encoding="utf-8", errors="ignore") as f:
                            proc = f.read().strip()
                m_title = re.search(r'(?:_NET_WM_NAME|WM_NAME)\([^)]+\)\s*=\s*"([^"]*)"', info_res.stdout)
                if m_title:
                    title = m_title.group(1).strip()
                return ActiveWindowInfo(process_name=proc or "x11", window_title=title, pid=pid)
        except Exception:
            pass

    return ActiveWindowInfo(process_name="linux", window_title="", pid=0)


def get_active_window_info() -> ActiveWindowInfo:
    """Returns foreground process name, window title, and PID across Windows, macOS, and Linux."""
    if sys.platform == "win32":
        import ctypes.wintypes as wintypes

        user32, kernel32 = _configure_win32_ctypes()
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ActiveWindowInfo(process_name="", window_title="", pid=0)

        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()

        pid_val = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val))
        pid = int(pid_val.value)

        process_name = ""
        if pid > 0:
            process_query_limited = 0x1000
            h_proc = kernel32.OpenProcess(process_query_limited, False, pid)
            if h_proc:
                try:
                    exe_buf = ctypes.create_unicode_buffer(512)
                    size = wintypes.DWORD(len(exe_buf))
                    if kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buf, ctypes.byref(size)):
                        process_name = os.path.basename(exe_buf.value)
                finally:
                    kernel32.CloseHandle(h_proc)

        return ActiveWindowInfo(process_name=process_name, window_title=title, pid=pid)

    if sys.platform == "darwin":
        return _get_macos_active_window()

    if sys.platform.startswith("linux"):
        return _get_linux_active_window()

    return ActiveWindowInfo(process_name="unknown", window_title="", pid=0)
