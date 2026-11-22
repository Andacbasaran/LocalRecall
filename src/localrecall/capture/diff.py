"""Frame Diff Lock: Ekran anlamlı biçimde değişmediyse yakalamayı atlar."""

from __future__ import annotations

import numpy as np
from PIL import Image


class FrameDiffLock:
    """Küçültülmüş gri tonlamalı kare farkıyla boşta CPU/disk kullanımını minimize eder."""

    def __init__(self, threshold: float = 0.015, sample_size: tuple[int, int] = (128, 72)) -> None:
        self.threshold = threshold
        self.sample_size = sample_size
        self._last_frame: np.ndarray | None = None

    def reset(self) -> None:
        """Son referans kareyi sıfırlar (bir sonraki kare mutlaka yakalanır)."""
        self._last_frame = None

    def _fingerprint(self, image: Image.Image) -> np.ndarray:
        small = image.convert("L").resize(self.sample_size, Image.Resampling.BILINEAR)
        return np.asarray(small, dtype=np.float32) / 255.0

    def has_changed(self, image: Image.Image) -> tuple[bool, float]:
        """Görüntü önceki referans kareden eşik üzerinde farklıysa (True, skor) döndürür."""
        current = self._fingerprint(image)
        if self._last_frame is None:
            self._last_frame = current
            return True, 1.0

        if current.shape != self._last_frame.shape:
            self._last_frame = current
            return True, 1.0

        diff_score = float(np.mean(np.abs(current - self._last_frame)))
        if diff_score >= self.threshold:
            self._last_frame = current
            return True, diff_score

        return False, diff_score
