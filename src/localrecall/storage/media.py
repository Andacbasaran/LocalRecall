"""WebP compressed screenshot storage manager."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image


class MediaStore:
    """Stores desktop captures as WebP images organized in daily subfolders."""

    def __init__(self, captures_dir: Path, quality: int = 75, max_width: int = 1920) -> None:
        self.captures_dir = captures_dir
        self.quality = quality
        self.max_width = max_width
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        img_to_save = image
        if self.max_width > 0 and image.width > self.max_width:
            ratio = self.max_width / float(image.width)
            new_height = max(1, int(image.height * ratio))
            img_to_save = image.resize((self.max_width, new_height), Image.Resampling.LANCZOS)

        if img_to_save.mode not in ("RGB", "RGBA"):
            img_to_save = img_to_save.convert("RGB")
        return img_to_save

    def save_image_with_size(
        self,
        image: Image.Image,
        timestamp: datetime | None = None,
    ) -> tuple[str, int, int, int]:
        """Saves image as WebP and returns (rel_path, width, height, size_bytes)."""
        ts = timestamp or datetime.now()
        day_dir = self.captures_dir / ts.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        base_name = ts.strftime("%H%M%S_%f")[:-3]
        full_path = day_dir / f"{base_name}.webp"
        counter = 1
        while full_path.exists():
            full_path = day_dir / f"{base_name}_{counter}.webp"
            counter += 1

        img_to_save = self._prepare_image(image)
        img_to_save.save(full_path, format="WEBP", quality=self.quality, method=4)
        size_bytes = int(full_path.stat().st_size) if full_path.exists() else 0
        rel_path = full_path.relative_to(self.captures_dir).as_posix()
        return rel_path, img_to_save.width, img_to_save.height, size_bytes

    def save_image(self, image: Image.Image, timestamp: datetime | None = None) -> tuple[str, int, int]:
        """Saves image as WebP and returns (rel_path, width, height)."""
        rel_path, w, h, _ = self.save_image_with_size(image, timestamp=timestamp)
        return rel_path, w, h

    def overwrite_image(self, rel_path: str, image: Image.Image) -> int:
        """Atomically overwrites an existing WebP capture (e.g. after PII blur) and returns bytes."""
        target = self.resolve_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(".tmp.webp")
        img_to_save = self._prepare_image(image)
        img_to_save.save(tmp_path, format="WEBP", quality=self.quality, method=4)
        tmp_path.replace(target)
        return int(target.stat().st_size) if target.exists() else 0

    def resolve_path(self, rel_path: str) -> Path:
        return self.captures_dir / rel_path

    def delete_image(self, rel_path: str) -> bool:
        if not rel_path:
            return False
        target = self.resolve_path(rel_path)
        try:
            if target.exists():
                target.unlink()
                if target.parent != self.captures_dir and target.parent.exists():
                    if not any(target.parent.iterdir()):
                        target.parent.rmdir()
                return True
        except OSError:
            return False
        return False

    def total_size_bytes(self) -> int:
        total = 0
        if not self.captures_dir.exists():
            return 0
        for path in self.captures_dir.rglob("*.webp"):
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total
