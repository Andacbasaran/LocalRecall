"""Frame Diff Lock with Perceptual Ring-Buffer Deduplication (history=8)."""

from __future__ import annotations

import threading
from collections import deque

import numpy as np
from PIL import Image


class FrameDiffLock:
    """
    Thread-safe deduplicator using downsampled perceptual fingerprints in a ring buffer.
    Alt+Tabbing back to an unchanged window hits the ring buffer and skips duplicates.
    """

    def __init__(
        self,
        threshold: float = 0.015,
        sample_size: tuple[int, int] = (128, 72),
        history_size: int = 8,
    ) -> None:
        self._lock = threading.Lock()
        self.threshold = float(threshold)
        self.sample_size = sample_size
        self.history_size = max(1, int(history_size))
        self._history: deque[np.ndarray] = deque(maxlen=self.history_size)
        self.total_checked: int = 0
        self.total_skipped: int = 0

    @property
    def savings_pct(self) -> float:
        with self._lock:
            if self.total_checked <= 0:
                return 0.0
            return round((self.total_skipped / float(self.total_checked)) * 100.0, 1)

    def reset(self) -> None:
        """Clears the perceptual ring buffer so the next frame is always captured."""
        with self._lock:
            self._history.clear()

    def set_history_size(self, history_size: int) -> None:
        size = max(1, int(history_size))
        with self._lock:
            if size == self.history_size:
                return
            self.history_size = size
            self._history = deque(self._history, maxlen=size)

    def _fingerprint(self, image: Image.Image) -> np.ndarray:
        # Downsample BEFORE grayscale conversion to avoid full-res color math on 1080p/4K frames
        small = image.resize(self.sample_size, Image.Resampling.BILINEAR).convert("L")
        return np.asarray(small, dtype=np.float32) / 255.0

    def has_changed(self, image: Image.Image) -> tuple[bool, float]:
        """
        Returns (True, min_diff_score) if the frame differs from all recent frames
        in the ring buffer by at least `threshold`; otherwise (False, min_diff_score).
        """
        current = self._fingerprint(image)
        with self._lock:
            self.total_checked += 1
            if not self._history:
                self._history.append(current)
                return True, 1.0

            min_diff = 1.0
            for prev in self._history:
                if current.shape != prev.shape:
                    continue
                diff_score = float(np.mean(np.abs(current - prev)))
                if diff_score < min_diff:
                    min_diff = diff_score
                if min_diff < self.threshold:
                    self.total_skipped += 1
                    return False, min_diff

            self._history.append(current)
            return True, min_diff
