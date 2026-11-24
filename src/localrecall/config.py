"""Application configuration, persistent JSON settings, and cross-platform autostart."""

from __future__ import annotations

import json
import os
import plistlib
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from localrecall import __bundle_id__

DEFAULT_BLOCKED_PROCESSES: list[str] = [
    # Cross-platform password managers & credential agents (normalized automatically)
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
    # macOS sensitive apps & system agents
    "Keychain Access",
    "Passwords",
    "SecurityAgent",
    # Linux keyring / polkit agents
    "gnome-keyring",
    "gnome-keyring-daemon",
    "kwalletd5",
    "kwalletd6",
]

DEFAULT_BLOCKED_TITLE_KEYWORDS: list[str] = [
    "inprivate",
    "incognito",
    "gizli",
    "private browsing",
    "private window",
    "tor browser",
    "1password",
    "bitwarden",
    "keepass",
    "lastpass",
    "dashlane",
    "keychain",
    "şifre",
    "password manager",
    "vault",
    "authenticator",
]


def get_default_data_dir() -> Path:
    """Returns OS-native default data directory for LocalRecall."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "LocalRecall"
        return Path.home() / ".localrecall"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LocalRecall"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "localrecall"
    return Path.home() / ".local" / "share" / "localrecall"


def get_default_hotkey() -> str:
    """Returns OS-idiomatic default global hotkey."""
    return "Cmd+Shift+Space" if sys.platform == "darwin" else "Ctrl+Shift+Space"


def _build_launch_args() -> list[str]:
    """Builds command-line arguments to launch LocalRecall minimized at login."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimized"]
    script = Path(__file__).resolve().parents[2] / "main.py"
    if sys.platform == "win32":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw if pythonw.exists() else Path(sys.executable))
    else:
        exe = sys.executable
    return [exe, str(script), "--minimized"]


def set_windows_autostart(enabled: bool, app_name: str = "LocalRecall") -> bool:
    """Registers or removes Windows HKCU Run autostart entry (always passes --minimized)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                args = _build_launch_args()
                cmd = " ".join(f'"{a}"' if (" " in a or a.endswith(".exe") or a.endswith(".py")) else a for a in args)
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def set_macos_autostart(enabled: bool, plist_path: Path | None = None) -> bool:
    """Creates or removes ~/Library/LaunchAgents/com.andacbasaran.localrecall.plist."""
    if sys.platform != "darwin" and plist_path is None:
        return False
    target = plist_path or (
        Path.home() / "Library" / "LaunchAgents" / f"{__bundle_id__}.plist"
    )
    try:
        if enabled:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": __bundle_id__,
                "ProgramArguments": _build_launch_args(),
                "RunAtLoad": True,
                "KeepAlive": False,
                "ProcessType": "Interactive",
            }
            with open(target, "wb") as f:
                plistlib.dump(payload, f)
        else:
            if target.exists():
                target.unlink()
        return True
    except OSError:
        return False


def set_linux_autostart(enabled: bool, desktop_path: Path | None = None) -> bool:
    """Creates or removes ~/.config/autostart/localrecall.desktop."""
    if not sys.platform.startswith("linux") and desktop_path is None:
        return False
    target = desktop_path or (
        Path.home() / ".config" / "autostart" / "localrecall.desktop"
    )
    try:
        if enabled:
            target.parent.mkdir(parents=True, exist_ok=True)
            args = _build_launch_args()
            exec_cmd = " ".join(f'"{a}"' if " " in a else a for a in args)
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Version=1.0\n"
                "Name=LocalRecall\n"
                "Comment=100% Offline, Privacy-First Smart Screen Memory\n"
                f"Exec={exec_cmd}\n"
                "Icon=localrecall\n"
                "Terminal=false\n"
                "Categories=Utility;\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            target.write_text(content, encoding="utf-8")
        else:
            if target.exists():
                target.unlink()
        return True
    except OSError:
        return False


def set_autostart(enabled: bool, app_name: str = "LocalRecall") -> bool:
    """Cross-platform login autostart registration."""
    if sys.platform == "win32":
        return set_windows_autostart(enabled, app_name=app_name)
    if sys.platform == "darwin":
        return set_macos_autostart(enabled)
    if sys.platform.startswith("linux"):
        return set_linux_autostart(enabled)
    return False


@dataclass
class AppConfig:
    """Persistent LocalRecall application configuration."""

    capture_interval_sec: float = 3.0
    idle_pause_sec: float = 60.0
    diff_threshold: float = 0.015
    diff_history_size: int = 8
    webp_quality: int = 75
    max_image_width: int = 1920
    retention_days: int = 30
    max_storage_gb: float = 5.0
    archive_images_after_days: int = 0
    monitor_index: int = 1
    ocr_enabled: bool = True
    ocr_min_confidence: float = 0.45
    cpu_profile: str = "auto"
    pii_redaction_mode: str = "redact_and_blur"
    password_manager_guard: bool = True
    incognito_guard: bool = True
    pause_on_start: bool = False
    auto_start: bool = False
    minimize_to_tray: bool = True
    global_hotkey_enabled: bool = True
    global_hotkey: str = field(default_factory=get_default_hotkey)
    search_mode: str = "hybrid"
    ui_language: str = "en"
    check_updates_on_startup: bool = True
    blocked_processes: list[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_PROCESSES)
    )
    blocked_title_keywords: list[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_TITLE_KEYWORDS)
    )
    data_dir: str = field(default_factory=lambda: str(get_default_data_dir()))

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_path / "localrecall.db"

    @property
    def captures_dir(self) -> Path:
        return self.data_path / "captures"

    @property
    def config_path(self) -> Path:
        return self.data_path / "config.json"

    @property
    def crash_log_path(self) -> Path:
        return self.data_path / "crash.log"

    def ensure_dirs(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.ensure_dirs()
        self.config_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, data_dir: Path | None = None) -> AppConfig:
        target_dir = data_dir or get_default_data_dir()
        config_file = target_dir / "config.json"

        if config_file.exists():
            try:
                raw = json.loads(config_file.read_text(encoding="utf-8"))
                valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
                filtered = {k: v for k, v in raw.items() if k in valid_fields}
                filtered.setdefault("data_dir", str(target_dir))
                cfg = cls(**filtered)
                cfg.ensure_dirs()
                return cfg
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        cfg = cls(data_dir=str(target_dir))
        cfg.save()
        return cfg
