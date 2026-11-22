"""Uygulama yapılandırması ve kalıcı ayar yönetimi."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_BLOCKED_PROCESSES: list[str] = [
    "1password.exe",
    "bitwarden.exe",
    "keepass.exe",
    "keepassxc.exe",
    "lastpass.exe",
    "dashlane.exe",
    "nordpass.exe",
    "protonpass.exe",
    "enpass.exe",
    "credentialuibroker.exe",
    "lockapp.exe",
    "logonui.exe",
]

DEFAULT_BLOCKED_TITLE_KEYWORDS: list[str] = [
    "inprivate",
    "incognito",
    "gizli",
    "private browsing",
    "tor browser",
    "1password",
    "bitwarden",
    "keepass",
    "lastpass",
    "dashlane",
    "şifre",
    "password manager",
    "vault",
]


def get_default_data_dir() -> Path:
    """Varsayılan kullanıcı veri dizinini döndürür (%LOCALAPPDATA%/LocalRecall)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "LocalRecall"
    return Path.home() / ".localrecall"


@dataclass
class AppConfig:
    """LocalRecall kalıcı uygulama ayarları."""

    capture_interval_sec: float = 3.0
    diff_threshold: float = 0.015  # 0.0 - 1.0 arası ortalama piksel farkı eşiği (%1.5)
    webp_quality: int = 75
    max_image_width: int = 1920
    retention_days: int = 30
    monitor_index: int = 1  # mss monitör indeksi (1 = birincil monitör, 0 = tümü)
    ocr_enabled: bool = True
    ocr_min_confidence: float = 0.45
    pause_on_start: bool = False
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

    def ensure_dirs(self) -> None:
        """Gerekli veri klasörlerini oluşturur."""
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        """Ayarları JSON dosyasına kaydeder."""
        self.ensure_dirs()
        self.config_path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, data_dir: Path | None = None) -> AppConfig:
        """Ayarları diskten yükler; yoksa varsayılanları oluşturup kaydeder."""
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
