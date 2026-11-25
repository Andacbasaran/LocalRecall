"""Privacy Shield filter: Password managers, private/incognito windows, and custom blocklists."""

from __future__ import annotations

import os
import threading
from typing import Iterable

from localrecall.storage.database import fold_text

from .window_info import ActiveWindowInfo

BUILTIN_PASSWORD_MANAGERS: frozenset[str] = frozenset(
    {
        "1password",
        "1password7",
        "1password8",
        "1password-gui",
        "bitwarden",
        "bitwarden-desktop",
        "keepass",
        "keepassxc",
        "lastpass",
        "dashlane",
        "nordpass",
        "protonpass",
        "enpass",
        "keeper",
        "authy",
        "ente auth",
        "yubico authenticator",
        "strongbox",
        "macpass",
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
        "seahorse",
        "pinentry",
    }
)

BUILTIN_INCOGNITO_KEYWORDS: tuple[str, ...] = (
    "inprivate",
    "incognito",
    "inkognito",
    "gizli",
    "özel gezinti",
    "özel pencere",
    "private browsing",
    "private window",
    "privates fenster",
    "navigation privée",
    "navegación privada",
    "tor browser",
)

_BUILTIN_INCOGNITO_FOLDED: tuple[tuple[str, str], ...] = tuple(
    (fold_text(k), k) for k in BUILTIN_INCOGNITO_KEYWORDS if fold_text(k)
)


def normalize_process_name(name: str) -> str:
    """Normalizes process names across Windows/macOS/Linux (strips path, .exe/.app, folds case/diacritics)."""
    cleaned = (name or "").strip().replace("\\", "/")
    if "/" in cleaned:
        cleaned = os.path.basename(cleaned)
    low = fold_text(cleaned)
    for suffix in (".exe", ".app"):
        if low.endswith(suffix):
            low = low[: -len(suffix)]
    return low.strip()


class PrivacyFilter:
    """Thread-safe filter excluding sensitive applications and private/incognito tabs from capture."""

    def __init__(
        self,
        blocked_processes: Iterable[str] = (),
        blocked_title_keywords: Iterable[str] = (),
        password_manager_guard: bool = True,
        incognito_guard: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self.password_manager_guard = bool(password_manager_guard)
        self.incognito_guard = bool(incognito_guard)
        self._blocked_processes: frozenset[str] = frozenset()
        self._blocked_keywords: tuple[tuple[str, str], ...] = ()
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
        procs = frozenset(
            norm for p in blocked_processes if p and (norm := normalize_process_name(p))
        )
        keywords = tuple(
            (folded, k.strip())
            for k in blocked_title_keywords
            if k and k.strip() and (folded := fold_text(k))
        )
        with self._lock:
            if password_manager_guard is not None:
                self.password_manager_guard = bool(password_manager_guard)
            if incognito_guard is not None:
                self.incognito_guard = bool(incognito_guard)
            self._blocked_processes = procs
            self._blocked_keywords = keywords

    def should_skip(self, window: ActiveWindowInfo) -> tuple[bool, str]:
        """Returns (True, reason) if the active window must be skipped, else (False, '')."""
        proc_raw = (window.process_name or "").strip().lower()
        proc_norm = normalize_process_name(window.process_name)
        title_folded = fold_text(window.window_title or "")

        with self._lock:
            blocked_procs = self._blocked_processes
            blocked_kws = self._blocked_keywords
            pm_guard = self.password_manager_guard
            inc_guard = self.incognito_guard

        if proc_norm:
            if proc_norm in blocked_procs:
                return True, f"process:{proc_raw or proc_norm}"
            if pm_guard and proc_norm in BUILTIN_PASSWORD_MANAGERS:
                return True, f"process:{proc_raw or proc_norm}"

        if title_folded:
            for folded_kw, raw_kw in blocked_kws:
                if folded_kw in title_folded:
                    return True, f"title:{raw_kw}"
            if inc_guard:
                for folded_kw, raw_kw in _BUILTIN_INCOGNITO_FOLDED:
                    if folded_kw in title_folded:
                        return True, f"title:{raw_kw}"

        return False, ""
