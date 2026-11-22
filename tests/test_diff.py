"""Frame Diff Lock birim testleri."""

from PIL import Image, ImageDraw

from localrecall.capture.diff import FrameDiffLock


def test_frame_diff_lock_skips_identical_and_detects_change():
    lock = FrameDiffLock(threshold=0.015)

    img1 = Image.new("RGB", (640, 360), color=(20, 20, 20))
    changed1, _ = lock.has_changed(img1)
    assert changed1 is True

    # Aynı görüntü tekrar gelirse atlamalı
    changed2, score2 = lock.has_changed(img1.copy())
    assert changed2 is False
    assert score2 == 0.0

    # Belirgin bir değişiklik çizildiğinde yakalamalı
    img2 = img1.copy()
    draw = ImageDraw.Draw(img2)
    draw.rectangle((50, 50, 400, 250), fill=(240, 240, 240))
    changed3, score3 = lock.has_changed(img2)
    assert changed3 is True
    assert score3 > 0.015
