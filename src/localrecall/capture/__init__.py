"""Ekran yakalama, aktif pencere tespiti, gizlilik filtresi ve Frame Diff Lock."""

from .diff import FrameDiffLock
from .privacy import PrivacyFilter
from .window_info import ActiveWindowInfo, get_active_window_info

__all__ = [
    "ActiveWindowInfo",
    "FrameDiffLock",
    "PrivacyFilter",
    "get_active_window_info",
]
