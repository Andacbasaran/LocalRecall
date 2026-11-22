"""Gizlilik filtresi: Şifre yöneticileri, gizli sekmeler ve kara liste kontrolü."""

from __future__ import annotations

from typing import Iterable

from .window_info import ActiveWindowInfo


class PrivacyFilter:
    """Hassas uygulama ve pencere başlıklarını yakalamadan hariç tutar."""

    def __init__(
        self,
        blocked_processes: Iterable[str] = (),
        blocked_title_keywords: Iterable[str] = (),
    ) -> None:
        self.update_rules(blocked_processes, blocked_title_keywords)

    def update_rules(
        self,
        blocked_processes: Iterable[str],
        blocked_title_keywords: Iterable[str],
    ) -> None:
        self._blocked_processes = {
            p.strip().lower() for p in blocked_processes if p and p.strip()
        }
        self._blocked_keywords = [
            k.strip().lower() for k in blocked_title_keywords if k and k.strip()
        ]

    def should_skip(self, window: ActiveWindowInfo) -> tuple[bool, str]:
        """Pencere hariç tutulmalıysa (True, sebep), değilse (False, '') döndürür."""
        proc = window.process_name.strip().lower()
        title = window.window_title.strip().lower()

        if proc and proc in self._blocked_processes:
            return True, f"process:{proc}"

        # ".exe" uzantısız girilmiş kuralları da destekle
        proc_stem = proc[:-4] if proc.endswith(".exe") else proc
        if proc_stem and proc_stem in self._blocked_processes:
            return True, f"process:{proc_stem}"

        if title:
            for keyword in self._blocked_keywords:
                if keyword in title:
                    return True, f"title:{keyword}"

        return False, ""
