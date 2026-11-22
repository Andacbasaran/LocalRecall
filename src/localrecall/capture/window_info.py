"""Windows Win32 API (ctypes) ile aktif pencere başlığı ve süreç adı tespiti."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
from dataclasses import dataclass


@dataclass(slots=True)
class ActiveWindowInfo:
    """Ön plandaki aktif pencerenin bilgileri."""

    process_name: str
    window_title: str
    pid: int = 0


def get_active_window_info() -> ActiveWindowInfo:
    """Ön plandaki pencerenin süreç adını ve başlığını döndürür (Windows)."""
    if sys.platform != "win32":
        return ActiveWindowInfo(process_name="unknown", window_title="")

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ActiveWindowInfo(process_name="", window_title="", pid=0)

    # Pencere başlığı
    length = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

    # Süreç ID (PID) ve executable adı
    pid_val = ctypes.wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val))
    pid = int(pid_val.value)

    process_name = ""
    if pid > 0:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h_proc:
            try:
                exe_buf = ctypes.create_unicode_buffer(512)
                size = ctypes.wintypes.DWORD(len(exe_buf))
                if kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buf, ctypes.byref(size)):
                    process_name = os.path.basename(exe_buf.value)
            finally:
                kernel32.CloseHandle(h_proc)

    return ActiveWindowInfo(process_name=process_name, window_title=title, pid=pid)
