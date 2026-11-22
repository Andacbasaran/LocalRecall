"""OCR kutu serileştirme, global kısayol ayrıştırma, MediaStore ve gizlilik temizlik testleri."""

from datetime import datetime, timedelta

from PIL import Image

from localrecall.ocr.engine import OCRBox, OCRResult
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore
from localrecall.ui.hotkey import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, parse_hotkey


def test_ocr_boxes_roundtrip():
    res = OCRResult(
        text="Merhaba Dünya",
        boxes=[
            OCRBox(text="Merhaba", x=0.1, y=0.2, w=0.3, h=0.05, score=0.98),
            OCRBox(text="Dünya", x=0.45, y=0.2, w=0.2, h=0.05, score=0.92),
        ],
    )
    raw = res.boxes_to_json()
    parsed = OCRResult.parse_boxes(raw)
    assert len(parsed) == 2
    assert parsed[0].text == "Merhaba"
    assert parsed[1].x == 0.45


def test_parse_hotkey():
    parsed = parse_hotkey("Ctrl+Shift+Space")
    assert parsed == (MOD_NOREPEAT | MOD_CONTROL | MOD_SHIFT, 0x20)

    parsed_alt = parse_hotkey("Alt+R")
    assert parsed_alt == (MOD_NOREPEAT | MOD_ALT, ord("R"))

    assert parse_hotkey("Space") is None  # modifier yok
    assert parse_hotkey("Ctrl+InvalidKeyName") is None


def test_media_store_save_and_delete(tmp_path):
    store = MediaStore(tmp_path / "captures", quality=70, max_width=800)
    img = Image.new("RGB", (1600, 900), color=(30, 60, 90))
    rel, w, h = store.save_image(img)
    assert w == 800
    assert h == 450
    assert store.resolve_path(rel).exists()
    assert store.total_size_bytes() > 0

    assert store.delete_image(rel) is True
    assert not store.resolve_path(rel).exists()


def test_purge_last_minutes_and_app_breakdown(tmp_path):
    db = Database(tmp_path / "purge.db")
    try:
        old_ts = datetime.now() - timedelta(minutes=45)
        recent_ts = datetime.now() - timedelta(minutes=2)

        db.insert_capture("old.webp", "Code.exe", "Eski", 100, 100, timestamp=old_ts)
        db.insert_capture("new1.webp", "chrome.exe", "Yeni 1", 100, 100, timestamp=recent_ts)
        db.insert_capture("new2.webp", "chrome.exe", "Yeni 2", 100, 100, timestamp=recent_ts)

        breakdown = dict(db.get_app_breakdown())
        assert breakdown["chrome.exe"] == 2
        assert breakdown["Code.exe"] == 1

        purged = db.purge_last_minutes(15)
        assert sorted(purged) == ["new1.webp", "new2.webp"]
        assert db.get_stats()["total"] == 1
    finally:
        db.close()
