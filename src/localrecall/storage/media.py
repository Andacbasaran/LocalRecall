"""Ekran görüntülerini WebP formatında sıkıştırarak diske kaydetme ve yönetme."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image


class MediaStore:
    """Ekran görüntülerini tarih bazlı klasörlerde WebP olarak saklar."""

    def __init__(self, captures_dir: Path, quality: int = 75, max_width: int = 1920) -> None:
        self.captures_dir = captures_dir
        self.quality = quality
        self.max_width = max_width
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def save_image(self, image: Image.Image, timestamp: datetime | None = None) -> tuple[str, int, int]:
        """Görüntüyü WebP olarak kaydeder ve (göreli_yol, genişlik, yükseklik) döndürür."""
        ts = timestamp or datetime.now()
        day_dir = self.captures_dir / ts.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        filename = ts.strftime("%H%M%S_%f")[:-3] + ".webp"
        full_path = day_dir / filename

        img_to_save = image
        if self.max_width > 0 and image.width > self.max_width:
            ratio = self.max_width / float(image.width)
            new_height = max(1, int(image.height * ratio))
            img_to_save = image.resize((self.max_width, new_height), Image.Resampling.LANCZOS)

        if img_to_save.mode not in ("RGB", "RGBA"):
            img_to_save = img_to_save.convert("RGB")

        img_to_save.save(full_path, format="WEBP", quality=self.quality, method=4)
        rel_path = full_path.relative_to(self.captures_dir).as_posix()
        return rel_path, img_to_save.width, img_to_save.height

    def resolve_path(self, rel_path: str) -> Path:
        """Göreli kayıt yolunu tam disk yoluna çevirir."""
        return self.captures_dir / rel_path

    def delete_image(self, rel_path: str) -> bool:
        """Diskten ilgili ekran görüntüsünü siler."""
        target = self.resolve_path(rel_path)
        try:
            if target.exists():
                target.unlink()
                # Boş kalan gün klasörünü temizle
                if target.parent != self.captures_dir and not any(target.parent.iterdir()):
                    target.parent.rmdir()
                return True
        except OSError:
            return False
        return False

    def total_size_bytes(self) -> int:
        """Tüm kayıtlı ekran görüntülerinin toplam disk boyutunu bayt cinsinden döndürür."""
        total = 0
        if not self.captures_dir.exists():
            return 0
        for path in self.captures_dir.rglob("*.webp"):
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total
