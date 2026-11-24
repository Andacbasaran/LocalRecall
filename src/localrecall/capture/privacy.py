"""Privacy Shield filter: Password managers, private/incognito windows, and custom blocklists."""

from __future__ import annotations

import os
from typing import Iterable

from .window_info import ActiveWindowInfo

BUILTIN_PASSWORD_MANAGERS: frozenset[str] = frozenset(
    {
        "1password",
        "bitwarden",
        "keepass",
        "keepassxc",
        "lastpass",
        "dashlane",
        "nordpass",
        "protonpass",
        "enpass",
        "credentialuibroker",
        "lockapp",
        "logonui",
        "keychain access",
        "passwords",
        "securityagent",
        "gnome-keyring",
        "gnome-keyring-daemon",
        "kwalletd5",
        "kwalletd6",
    }
)

BUILTIN_INCOGNITO_KEYWORDS: tuple[str, ...] = (
    "inprivate",
    "incognito",
    "gizli",
    "private browsing",
    "private window",
    "tor browser",
)


def normalize_process_name(name: str) -> str:
    """Normalizes process names across Windows/macOS/Linux (strips path, .exe/.app, lowercases)."""
    cleaned = (name or "").strip().replace("\\", "/")
    if "/" in cleaned:
        cleaned = os.path.basename(cleaned)
    low = cleaned.lower().strip()
    for suffix in (".exe", ".app"):
        if low.endswith(suffix):
            low = low[: -len(suffix)]
    return low.strip()


class PrivacyFilter:
    """Excludes sensitive applications and browser private/incognito tabs from capture."""

    def __init__(
        self,
        blocked_processes: Iterable[str] = (),
        blocked_title_keywords: Iterable[str] = (),
        password_manager_guard: bool = True,
        incognito_guard: bool = True,
    ) -> None:
        self.password_manager_guard = password_manager_guard
        self.incognito_guard = incognito_guard
        self._blocked_processes: set[str] = set()
        self._blocked_keywords: list[str] = []
        self.update_rules(
            blocked_processes,
            blocked_title_keywords,
            password_manager_guard=password_manager_guard,
            incognito_guard=incognito_guard,
        )

    def update_rules(
        self,
        blocked_processes: Iterable[str],
        blocked_title_keywords: Iterable[str],
        password_manager_guard: bool | None = None,
        incognito_guard: bool | None = None,
    ) -> None:
        if password_manager_guard is not None:
            self.password_manager_guard = bool(password_manager_guard)
        if incognito_guard is not None:
            self.incognito_guard = bool(incognito_guard)

        # Normalize BOTH stored rules and incoming process names (Fixes Bug #1!)
        self._blocked_processes = {
            normalize_process_name(p) for p in blocked_processes if p and normalize_process_name(p)
        }
        self._blocked_keywords = [
            k.strip().lower() for k in blocked_title_keywords if k and k.strip()
        ]

    def should_skip(self, window: ActiveWindowInfo) -> tuple[bool, str]:
        """Returns (True, reason) if the active window must be skipped, else (False, '')."""
        proc_raw = (window.process_name or "").strip().lower()
        proc_norm = normalize_process_name(window.process_name)
        title = (window.window_title or "").strip().lower()

        if proc_norm:
            if proc_norm in self._blocked_processes:
                return True, f"process:{proc_raw or proc_norm}"
            if self.password_manager_guard and proc_norm in BUILTIN_PASSWORD_MANAGERS:
                return True, f"process:{proc_raw or proc_norm}"

        if title:
            for keyword in self._blocked_keywords:
                if keyword in title:
                    return True, f"title:{keyword}"
            if self.incognito_guard:
                for keyword in BUILTIN_INCOGNITO_KEYWORDS:
                    if keyword in title:
                        return True, f"title:{keyword}"

        return False, ""
