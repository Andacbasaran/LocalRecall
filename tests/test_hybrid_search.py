"""Hibrit arama (FTS5 + Türkçe/OCR-toleranslı bulanık eşleşme) testleri."""

from localrecall.search.hybrid import HybridSearchEngine, normalize_for_matching
from localrecall.storage.database import Database


def test_normalize_turkish_characters():
    assert normalize_for_matching("Şifre Yönetimi ÇĞIÖŞÜ") == "sifre yonetimi cgiosu"


def test_hybrid_search_finds_ocr_typos_and_turkish_variants(tmp_path):
    db = Database(tmp_path / "hybrid.db")
    try:
        cid_exact = db.insert_capture(
            image_path="a.webp",
            app_name="Code.exe",
            window_title="LocalRecall",
            width=1920,
            height=1080,
            ocr_text="LocalRecall hızlı ekran hafızası",
            ocr_done=True,
        )
        cid_typo = db.insert_capture(
            image_path="b.webp",
            app_name="notepad.exe",
            window_title="Not",
            width=1920,
            height=1080,
            ocr_text="LocaIRecall hizli ekran hafizasi",
            ocr_done=True,
        )

        engine = HybridSearchEngine(db)
        results = engine.search("LocalRecall hafızası", mode="hybrid")
        ids = [r.record.id for r in results]
        assert cid_exact in ids
        assert cid_typo in ids
        # Kesin eşleşme en üstte olmalı
        assert ids[0] == cid_exact
    finally:
        db.close()
