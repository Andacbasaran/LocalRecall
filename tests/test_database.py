"""SQLite + FTS5 veritabanı ve arama testleri."""

from datetime import datetime, timedelta

from localrecall.storage.database import Database


def test_insert_and_fts_search(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        cid1 = db.insert_capture(
            image_path="2026-11-22/100000_000.webp",
            app_name="Code.exe",
            window_title="main.py - LocalRecall",
            width=1920,
            height=1080,
            ocr_text="SQLite FTS5 ile anında tam metin arama",
            ocr_done=True,
        )
        cid2 = db.insert_capture(
            image_path="2026-11-22/100005_000.webp",
            app_name="chrome.exe",
            window_title="Python Documentation",
            width=1920,
            height=1080,
            ocr_text="RapidOCR ONNX runtime CPU inference",
            ocr_done=True,
        )

        # Türkçe karakterli prefix araması
        res = db.search("anında")
        assert len(res) == 1
        assert res[0].record.id == cid1

        # Uygulama filtresiyle arama
        res_chrome = db.search("ONNX", app_name="chrome.exe")
        assert len(res_chrome) == 1
        assert res_chrome[0].record.id == cid2

        assert db.search("ONNX", app_name="Code.exe") == []
        assert db.list_apps() == ["chrome.exe", "Code.exe"]
    finally:
        db.close()


def test_update_ocr_and_delete_syncs_fts(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        cid = db.insert_capture(
            image_path="2026-11-22/100000_000.webp",
            app_name="notepad.exe",
            window_title="Notlar",
            width=800,
            height=600,
            ocr_text="",
            ocr_done=False,
        )
        assert db.search("gizli_kelime") == []

        db.update_ocr_text(cid, "Bu belgede gizli_kelime geçiyor")
        res = db.search("gizli_kelime")
        assert len(res) == 1
        assert res[0].record.ocr_done is True

        deleted_path = db.delete_capture(cid)
        assert deleted_path == "2026-11-22/100000_000.webp"
        assert db.search("gizli_kelime") == []
    finally:
        db.close()


def test_retention_purge(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        old_ts = datetime.now() - timedelta(days=45)
        new_ts = datetime.now()

        db.insert_capture("old.webp", "app.exe", "Eski", 100, 100, timestamp=old_ts)
        db.insert_capture("new.webp", "app.exe", "Yeni", 100, 100, timestamp=new_ts)

        purged = db.purge_older_than(30)
        assert purged == ["old.webp"]
        assert db.get_stats()["total"] == 1
    finally:
        db.close()
