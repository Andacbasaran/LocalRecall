"""Regression tests for LocalRecall P0/P1 privacy shield, PII, vault security, and lifecycle fixes."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from localrecall.capture.diff import FrameDiffLock
from localrecall.capture.monitor import CaptureService
from localrecall.capture.pii import PII_MODE_REDACT_AND_BLUR, PIIRedactor
from localrecall.capture.privacy import PrivacyFilter
from localrecall.capture.window_info import ActiveWindowInfo
from localrecall.config import AppConfig
from localrecall.ocr.engine import OCRBox
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore
from localrecall.updater import (
    UpdateInfo,
    download_update_asset,
    is_newer_version,
    select_platform_asset,
)


def test_turkish_uppercase_privacy_shield_and_firefox_private() -> None:
    cfg = AppConfig()
    pf = PrivacyFilter(
        blocked_processes=cfg.blocked_processes,
        blocked_title_keywords=cfg.blocked_title_keywords,
    )
    # Turkish uppercase 'İ' (U+0130) must NOT bypass privacy shield!
    skip, reason = pf.should_skip(ActiveWindowInfo(process_name="chrome.exe", window_title="Banka - GİZLİ SEKME"))
    assert skip is True
    assert reason

    skip_pw, _ = pf.should_skip(ActiveWindowInfo(process_name="app.exe", window_title="ŞİFRE Yöneticisi"))
    assert skip_pw is True

    skip_ff, _ = pf.should_skip(ActiveWindowInfo(process_name="firefox.exe", window_title="Özel Gezinti — Mozilla Firefox"))
    assert skip_ff is True

    skip_1p, _ = pf.should_skip(ActiveWindowInfo(process_name="1password-gui", window_title="Vault"))
    assert skip_1p is True


def test_pii_cross_box_redaction_and_regex_accuracy() -> None:
    redactor = PIIRedactor(mode=PII_MODE_REDACT_AND_BLUR)

    # Stripe underscore secret key must be detected (constructed dynamically for scanner safety)
    fake_stripe = "sk_" + "live_" + "51AbCdEfGhIjKlMnOpQrStUvWxYz"
    txt, dets = redactor.redact_text(f"STRIPE_KEY={fake_stripe}")
    assert dets and ("sk_" + "live_") not in txt

    # Turkish T.C. Kimlik No with "No:" separator
    txt, dets = redactor.redact_text("T.C. Kimlik No: 10000000146")
    assert dets and "10000000146" not in txt

    # Bidirectional & space-separated OTP
    txt, dets = redactor.redact_text("849201 is your verification code")
    assert dets and "849201" not in txt
    txt, dets = redactor.redact_text("Verification code: 849 201")
    assert dets and "849 201" not in txt

    # DB credential URL & PEM private key & GitLab/HF tokens
    txt, dets = redactor.redact_text("DATABASE_URL=postgresql://admin:s3cr3tpass@db.internal:5432/prod")
    assert dets and "s3cr3tpass" not in txt
    fake_pem = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAK..."
    _, dets = redactor.redact_text(fake_pem)
    assert dets
    fake_hf = "hf_" + "abcdefghijklmnopqrstuvwxyz123456"
    txt, dets = redactor.redact_text(f"HF_TOKEN={fake_hf}")
    assert dets and ("hf_" + "abcdef") not in txt

    # False positive prevention: invalid IBAN checksum & 13-digit Unix ms timestamp
    _, dets_iban = redactor.redact_text("Ref ID: AB12 CDEF 3456 7890")
    assert not dets_iban
    _, dets_ts = redactor.redact_text("event ts=1700000000004 ok")
    assert not dets_ts

    # Valid Turkish IBAN passes mod-97 checksum and IS redacted
    txt, dets = redactor.redact_text("IBAN: TR33 0006 1005 1978 6457 8413 26")
    assert dets and "TR33" not in txt

    # Cross-box PII: label in box 1, secret code in box 2 -> BOTH boxes redacted & blurred!
    boxes = [
        OCRBox(text="Verification code:", x=0.1, y=0.1, w=0.2, h=0.05),
        OCRBox(text="849201", x=0.32, y=0.1, w=0.13, h=0.05),
    ]
    cleaned_boxes, blur_boxes, all_dets = redactor.redact_ocr_boxes(boxes)
    assert all_dets
    assert all("849201" not in b.text for b in cleaned_boxes)
    assert len(blur_boxes) >= 1


def test_media_store_blocks_path_traversal_and_sets_posix_perms(tmp_path: Path) -> None:
    store = MediaStore(captures_dir=tmp_path / "captures")
    with pytest.raises(ValueError):
        store.resolve_path("../../etc/passwd")
    with pytest.raises(ValueError):
        store.resolve_path("/etc/passwd")

    outside = tmp_path / "secret.txt"
    outside.write_text("keep", encoding="utf-8")
    assert store.delete_image("../secret.txt") is False
    assert outside.exists()

    if os.name == "posix":
        assert (store.captures_dir.stat().st_mode & 0o777) == 0o700


def test_updater_fail_closed_and_wrong_arch_rejection(tmp_path: Path) -> None:
    assert is_newer_version("1.0.0-beta.2", "1.0.0-beta.1") is True
    assert is_newer_version("1.0.0+build.1", "1.0.0-rc.1") is True

    assets = [
        {
            "name": "LocalRecall-v1.1.0-macOS-arm64.dmg",
            "browser_download_url": "https://github.com/Andacbasaran/LocalRecall/releases/download/v1.1.0/LocalRecall-v1.1.0-macOS-arm64.dmg",
            "size": 1000,
        },
        {
            "name": "LocalRecall-v1.1.0-Linux-x86_64.tar.gz",
            "browser_download_url": "https://github.com/Andacbasaran/LocalRecall/releases/download/v1.1.0/LocalRecall-v1.1.0-Linux-x86_64.tar.gz",
            "size": 1000,
        },
        {
            "name": "SHA256SUMS.txt",
            "browser_download_url": "https://github.com/Andacbasaran/LocalRecall/releases/download/v1.1.0/SHA256SUMS.txt",
            "size": 100,
        },
    ]
    # Intel Mac must reject arm64 DMG; Linux aarch64 must reject x86_64 tarball
    assert select_platform_asset(assets, platform_name="darwin", machine="x86_64")[0] == ""
    assert select_platform_asset(assets, platform_name="linux", machine="aarch64")[0] == ""

    info_no_cs = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/LocalRecall/releases/tag/v1.1.0",
        asset_name="LocalRecall-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/LocalRecall/releases/download/v1.1.0/LocalRecall-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="",
    )
    with pytest.raises(RuntimeError, match="SHA-256"):
        download_update_asset(info_no_cs, str(tmp_path))

    info_ok = UpdateInfo(
        current_version="1.0.0",
        latest_version="1.1.0",
        is_update_available=True,
        release_url="https://github.com/Andacbasaran/LocalRecall/releases/tag/v1.1.0",
        asset_name="LocalRecall-Setup-v1.1.0-Windows-x64.exe",
        asset_url="https://github.com/Andacbasaran/LocalRecall/releases/download/v1.1.0/LocalRecall-Setup-v1.1.0-Windows-x64.exe",
        checksum_url="https://github.com/Andacbasaran/LocalRecall/releases/download/v1.1.0/SHA256SUMS.txt",
    )
    asset_resp = MagicMock()
    asset_resp.headers = {"Content-Length": "4"}
    asset_resp.read.side_effect = [b"data", b""]
    asset_resp.__enter__.return_value = asset_resp
    sums_resp = MagicMock()
    sums_resp.__enter__.return_value = BytesIO(b"")
    with patch("localrecall.updater.urllib.request.urlopen", side_effect=[asset_resp, sums_resp]):
        with pytest.raises(RuntimeError, match="SHA-256"):
            download_update_asset(info_ok, str(tmp_path))


def test_capture_service_stop_idempotent_and_db_like_escaping(tmp_path: Path) -> None:
    db = Database(tmp_path / "lr.db")
    media = MediaStore(captures_dir=tmp_path / "caps")
    cfg = AppConfig(data_dir=str(tmp_path), ocr_enabled=False)

    statuses: list[str] = []
    svc = CaptureService(config=cfg, db=db, media=media, on_status=statuses.append)
    # Stopping a service that was never started must NOT emit "Stopped" onto a closed DB!
    svc.stop()
    assert statuses == []

    # LIKE wildcard escaping on app_filter
    db.insert_capture(
        app_name="100%_App",
        window_title="Test",
        image_path="a.webp",
        width=1280,
        height=720,
        ocr_text="hello world",
    )
    db.insert_capture(
        app_name="OtherApp",
        window_title="Other",
        image_path="b.webp",
        width=1280,
        height=720,
        ocr_text="hello world",
    )
    assert len(db.search(query="hello", app_filter_like="100%")) == 1
    assert len(db.search(query="hello", app_filter_like="____")) == 0
    db.close()

    # FrameDiffLock & atomic config backup
    dl = FrameDiffLock()
    assert dl.threshold > 0
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{corrupt", encoding="utf-8")
    loaded = AppConfig.load(tmp_path)
    assert isinstance(loaded, AppConfig)
    assert any(p.name.startswith("config.json.corrupt") for p in tmp_path.iterdir())
