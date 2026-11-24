"""Comprehensive unit tests for PII Shield, PrivacyFilter, Ring-Buffer Diff, FTS5/Operators, Hardware, Updater & i18n."""

from __future__ import annotations

import plistlib
from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from localrecall.capture.diff import FrameDiffLock
from localrecall.capture.monitor import CaptureService
from localrecall.capture.pii import (
    PII_MODE_OFF,
    PII_MODE_REDACT_AND_BLUR,
    PIIRedactor,
    luhn_valid,
    tckn_valid,
)
from localrecall.capture.privacy import PrivacyFilter, normalize_process_name
from localrecall.capture.window_info import ActiveWindowInfo
from localrecall.config import (
    DEFAULT_BLOCKED_PROCESSES,
    DEFAULT_BLOCKED_TITLE_KEYWORDS,
    AppConfig,
    set_linux_autostart,
    set_macos_autostart,
)
from localrecall.demo import export_daily_markdown_digest
from localrecall.hardware import (
    PROFILE_AUTO,
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    HardwareProfile,
    classify_hardware_tier,
    compute_runtime_tuning,
    detect_hardware_profile,
    format_hardware_summary,
    get_ui_font_family,
    normalize_arch,
)
from localrecall.i18n import TRANSLATIONS, LanguageManager, tr
from localrecall.ocr.engine import OCRBox
from localrecall.search.hybrid import HybridSearchEngine, parse_search_query
from localrecall.storage.database import Database
from localrecall.storage.media import MediaStore
from localrecall.updater import (
    compute_file_sha256,
    is_newer_version,
    parse_semver,
    parse_sha256sums,
    select_platform_asset,
    verify_file_sha256,
)

# ── 1. PrivacyFilter & Extensionless Normalization ───────────────────────────


def test_normalize_process_name_cross_platform():
    assert normalize_process_name("Bitwarden.exe") == "bitwarden"
    assert normalize_process_name("bitwarden") == "bitwarden"
    assert normalize_process_name("1Password.app") == "1password"
    assert normalize_process_name("/usr/bin/bitwarden") == "bitwarden"
    assert normalize_process_name(r"C:\Program Files\KeePassXC\KeePassXC.exe") == "keepassxc"
    assert normalize_process_name("  Keychain Access  ") == "keychain access"


def test_privacy_filter_extensionless_and_guards():
    pf = PrivacyFilter(DEFAULT_BLOCKED_PROCESSES, DEFAULT_BLOCKED_TITLE_KEYWORDS)

    for proc, title in [
        ("bitwarden", "My Vault"),
        ("Bitwarden", "Unlock"),
        ("Bitwarden.exe", "Desktop"),
        ("1Password", "Personal"),
        ("1Password.app", "1Password"),
        ("/opt/Bitwarden/bitwarden", "Vault"),
        ("Keychain Access", "login"),
        ("gnome-keyring-daemon", ""),
    ]:
        skip, reason = pf.should_skip(ActiveWindowInfo(proc, title))
        assert skip is True, f"Expected {proc!r} to be blocked"
        assert reason.startswith("process:")

    # Disabling builtin guards respects explicit empty lists
    pf_open = PrivacyFilter(
        blocked_processes=[],
        blocked_title_keywords=[],
        password_manager_guard=False,
        incognito_guard=False,
    )
    assert pf_open.should_skip(ActiveWindowInfo("bitwarden", "Incognito")) == (False, "")

    # Enabling builtin guards catches them even with empty user lists
    pf_guarded = PrivacyFilter(
        blocked_processes=[],
        blocked_title_keywords=[],
        password_manager_guard=True,
        incognito_guard=True,
    )
    assert pf_guarded.should_skip(ActiveWindowInfo("1Password", "Main"))[0] is True
    assert pf_guarded.should_skip(ActiveWindowInfo("chrome", "Bank — Incognito"))[0] is True


# ── 2. PII & Secret Redaction Shield ─────────────────────────────────────────


def test_luhn_and_tckn_checksums():
    assert luhn_valid("4532015112830366") is True
    assert luhn_valid("4532015112830367") is False
    assert luhn_valid("0000000000000000") is False
    assert luhn_valid("12345") is False

    # Valid algorithmic TCKN (10000000146)
    assert tckn_valid("10000000146") is True
    assert tckn_valid("10000000147") is False
    assert tckn_valid("01234567890") is False


def test_pii_redactor_detects_all_secret_categories():
    redactor = PIIRedactor(mode=PII_MODE_REDACT_AND_BLUR)

    sample = (
        "OpenAI: sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz012345 "
        "GitHub: ghp_1234567890abcdefghij1234567890 "
        "AWS: AKIAIOSFODNN7EXAMPLE "
        "JWT: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U "
        "Card: 4532-0151-1283-0366 "
        "IBAN: TR330006100519786457841326 "
        "SSN: 123-45-6789 "
        "TCKN: 10000000146 "
        "Verification code: 849201"
    )
    sanitized, detections = redactor.redact_text(sample)
    cats = {d.category for d in detections}
    assert {"api_key", "card", "iban", "ssn", "tckn", "otp"}.issubset(cats)
    assert "[REDACTED:API_KEY]" in sanitized
    assert "[REDACTED:CARD]" in sanitized
    assert "[REDACTED:IBAN]" in sanitized
    assert "[REDACTED:SSN]" in sanitized
    assert "[REDACTED:TCKN]" in sanitized
    assert "[REDACTED:OTP]" in sanitized
    assert "4532-0151-1283-0366" not in sanitized
    assert "TR330006100519786457841326" not in sanitized
    assert "849201" not in sanitized

    # Turkish OTP context
    tr_clean, tr_dets = redactor.redact_text("Doğrulama kodu: 654321")
    assert tr_dets and "[REDACTED:OTP]" in tr_clean

    # Non-sensitive normal prose produces zero false positives
    benign = "LocalRecall v1.0.0 runs SQLite FTS5 in 0.64 ms with 0 MB VRAM on port 8080."
    clean_benign, dets_benign = redactor.redact_text(benign)
    assert dets_benign == []
    assert clean_benign == benign

    # Mode OFF disables redaction
    off = PIIRedactor(mode=PII_MODE_OFF)
    unchanged, off_dets = off.redact_text(sample)
    assert off_dets == []
    assert unchanged == sample


def test_pii_redact_ocr_boxes_and_blur_image():
    redactor = PIIRedactor(mode=PII_MODE_REDACT_AND_BLUR)
    boxes = [
        OCRBox(text="Hello LocalRecall", x=0.05, y=0.05, w=0.3, h=0.08, score=0.99),
        OCRBox(text="Key sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz012345", x=0.1, y=0.5, w=0.6, h=0.1, score=0.97),
    ]
    sanitized_boxes, blur_boxes, dets = redactor.redact_ocr_boxes(boxes)
    assert len(sanitized_boxes) == 2
    assert sanitized_boxes[0].text == "Hello LocalRecall"
    assert "[REDACTED:API_KEY]" in sanitized_boxes[1].text
    assert len(blur_boxes) == 1
    assert len(dets) == 1

    img = Image.new("RGB", (400, 200), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 100, 280, 120), fill=(255, 0, 0))
    blurred = PIIRedactor.blur_image_regions(img, blur_boxes)
    # Sensitive pixel region should now be veiled/darkened, while untouched corner remains bright
    assert blurred.getpixel((10, 10)) == (240, 240, 240)
    assert blurred.getpixel((150, 110)) != (255, 0, 0)


# ── 3. Ring-Buffer FrameDiffLock Deduplication ───────────────────────────────


def test_frame_diff_lock_ring_buffer_alt_tab_and_eviction():
    lock = FrameDiffLock(threshold=0.015, history_size=4)

    def _solid(rgb: tuple[int, int, int]) -> Image.Image:
        return Image.new("RGB", (256, 144), color=rgb)

    frame_a = _solid((10, 10, 10))
    frame_b = _solid((80, 80, 80))
    frame_c = _solid((160, 160, 160))
    frame_d = _solid((230, 230, 230))
    frame_e = _solid((40, 180, 90))

    assert lock.has_changed(frame_a)[0] is True
    assert lock.has_changed(frame_b)[0] is True
    assert lock.has_changed(frame_c)[0] is True

    # Alt+Tab back to unchanged frame_a -> ring-buffer hit, skipped!
    changed_revisit, score_revisit = lock.has_changed(frame_a.copy())
    assert changed_revisit is False
    assert score_revisit == 0.0
    assert lock.total_skipped == 1
    assert lock.savings_pct > 0.0

    # Push 2 more distinct frames (d, e) -> with history_size=4, frame_a is evicted
    assert lock.has_changed(frame_d)[0] is True
    assert lock.has_changed(frame_e)[0] is True
    assert lock.has_changed(frame_a.copy())[0] is True

    # Reset clears ring buffer
    lock.reset()
    assert lock.has_changed(frame_a.copy())[0] is True


# ── 4. Structured Search Operators & Turkish FTS5 Beyond 400 Rows ────────────


def test_parse_search_query_operators():
    parsed = parse_search_query('app:"VS Code" "SQLite FTS5" migration -slack -"old log" pinned:true')
    assert parsed.app_filter == "VS Code"
    assert parsed.exact_phrases == ["SQLite FTS5"]
    assert parsed.exclude_terms == ["slack", "old log"]
    assert parsed.pinned_only is True
    assert parsed.free_text == "migration"
    assert "SQLite FTS5" in parsed.highlight_query

    parsed_star = parse_search_query("is:pinned app:chrome")
    assert parsed_star.pinned_only is True
    assert parsed_star.app_filter == "chrome"
    assert parsed_star.has_text_query is False


def test_structured_operators_and_turkish_fts5_beyond_400_rows(tmp_path):
    db = Database(tmp_path / "search_scale.db")
    try:
        base = datetime.now() - timedelta(hours=10)
        # Insert target row #1 FIRST (will be older than the 400-row fuzzy pool!)
        old_target_id = db.insert_capture(
            image_path="old_tr.webp",
            app_name="VS Code",
            window_title="gizlilik_denetimi.py",
            width=1920,
            height=1080,
            ocr_text="Şifre yöneticisi hızlı günlük mimari raporu benzersiz_hedef_99",
            ocr_done=True,
            timestamp=base,
            pinned=True,
        )
        # Insert 430 newer noise rows so old_target_id falls beyond fuzzy_pool_size=400
        for i in range(430):
            db.insert_capture(
                image_path=f"noise_{i}.webp",
                app_name="Slack" if i % 2 == 0 else "Chrome",
                window_title=f"Noise Window #{i}",
                width=1920,
                height=1080,
                ocr_text=f"Routine daily standup status message iteration {i}",
                ocr_done=True,
                timestamp=base + timedelta(seconds=i + 1),
                pinned=False,
            )

        # Add a recent VS Code row with an excluded term
        excluded_id = db.insert_capture(
            image_path="recent_code.webp",
            app_name="VS Code",
            window_title="draft.py",
            width=1920,
            height=1080,
            ocr_text="Şifre yöneticisi hızlı taslak deprecated_noise",
            ocr_done=True,
            timestamp=base + timedelta(seconds=500),
            pinned=False,
        )

        engine = HybridSearchEngine(db, fuzzy_pool_size=400)

        # Turkish diacritic-folded search MUST find old_target_id beyond 400 rows!
        res_fts = engine.search("sifre hizli benzersiz_hedef_99", mode="fts")
        assert [r.record.id for r in res_fts] == [old_target_id]

        res_hybrid = engine.search("sifre hizli benzersiz_hedef_99", mode="hybrid")
        assert old_target_id in [r.record.id for r in res_hybrid]

        # Operators: app: + -exclude + pinned:true
        res_op = engine.search("app:code sifre -deprecated_noise pinned:true", mode="hybrid")
        ids = [r.record.id for r in res_op]
        assert old_target_id in ids
        assert excluded_id not in ids

        # Pure operator query (no text) -> pinned only
        res_pin_only = engine.search("pinned:true app:code", mode="hybrid")
        assert [r.record.id for r in res_pin_only] == [old_target_id]
    finally:
        db.close()


# ── 5. OCR-Only Archival Mode & Storage Quotas ───────────────────────────────


def test_ocr_only_archival_and_quota_protection(tmp_path):
    cfg = AppConfig(
        data_dir=str(tmp_path),
        retention_days=60,
        archive_images_after_days=7,
        max_storage_gb=0.0,
        ocr_enabled=False,
    )
    cfg.ensure_dirs()
    db = Database(cfg.db_path)
    media = MediaStore(cfg.captures_dir, quality=75, max_width=800)
    svc = CaptureService(config=cfg, db=db, media=media)
    try:
        old_ts = datetime.now() - timedelta(days=15)
        img = Image.new("RGB", (320, 180), color=(40, 80, 120))

        rel_unpinned, w, h, sz1 = media.save_image_with_size(img, timestamp=old_ts)
        cid_unpinned = db.insert_capture(
            image_path=rel_unpinned,
            app_name="Terminal",
            window_title="deploy.sh",
            width=w,
            height=h,
            ocr_text="kubernetes_archive_searchable_token",
            ocr_done=True,
            timestamp=old_ts,
            file_size_bytes=sz1,
            pinned=False,
        )

        rel_pinned, w2, h2, sz2 = media.save_image_with_size(img, timestamp=old_ts + timedelta(seconds=5))
        cid_pinned = db.insert_capture(
            image_path=rel_pinned,
            app_name="VS Code",
            window_title="important.py",
            width=w2,
            height=h2,
            ocr_text="pinned_protected_token",
            ocr_done=True,
            timestamp=old_ts + timedelta(seconds=5),
            file_size_bytes=sz2,
            pinned=True,
        )

        svc.run_retention_cleanup()

        # Unpinned old capture's WebP image was removed, but record & OCR text stay searchable!
        assert not media.resolve_path(rel_unpinned).exists()
        rec_arch = db.get_capture(cid_unpinned)
        assert rec_arch is not None
        assert rec_arch.image_archived is True
        assert rec_arch.file_size_bytes == 0
        hits = db.search("kubernetes_archive_searchable_token")
        assert [h.record.id for h in hits] == [cid_unpinned]

        # Pinned capture keeps its WebP image untouched
        assert media.resolve_path(rel_pinned).exists()
        rec_pin = db.get_capture(cid_pinned)
        assert rec_pin is not None and rec_pin.image_archived is False

        # Export Daily Markdown Digest works cleanly
        digest_path = export_daily_markdown_digest([rec_arch, rec_pin], tmp_path / "digest.md")
        digest_text = digest_path.read_text(encoding="utf-8")
        assert "LocalRecall Activity Digest" in digest_text
        assert "Terminal" in digest_text
        assert "[PINNED]" in digest_text
    finally:
        db.close()


# ── 6. Hardware, Updater, i18n & Cross-Platform Autostart ───────────────────


def test_hardware_detection_and_tuning():
    assert normalize_arch("AMD64") == "x86_64"
    assert normalize_arch("aarch64") == "arm64"
    assert classify_hardware_tier(2, 2, ("sse2",), "x86_64") == PROFILE_ECO
    assert classify_hardware_tier(4, 4, ("avx2",), "x86_64") == PROFILE_BALANCED
    assert classify_hardware_tier(10, 10, ("neon", "dotprod"), "arm64") == PROFILE_PERFORMANCE

    hw = detect_hardware_profile()
    assert hw.logical_cores >= 1
    assert hw.physical_cores >= 1
    assert get_ui_font_family() != ""

    fake_hw = HardwareProfile(
        os_name="Darwin",
        os_version="24.0",
        windows_build=0,
        arch="arm64",
        cpu_name="Apple M1 Pro",
        logical_cores=10,
        physical_cores=10,
        isa_features=("dotprod", "neon"),
        recommended_tier=PROFILE_PERFORMANCE,
    )
    t_auto = compute_runtime_tuning(fake_hw, PROFILE_AUTO)
    t_eco = compute_runtime_tuning(fake_hw, PROFILE_ECO)
    t_bal = compute_runtime_tuning(fake_hw, PROFILE_BALANCED)
    assert t_auto.effective_profile == PROFILE_PERFORMANCE
    assert t_auto.ocr_intra_threads == 4
    assert t_eco.ocr_intra_threads == 1
    assert t_bal.ocr_intra_threads == 2
    assert "0 MB VRAM" in format_hardware_summary(fake_hw, t_auto, lang="en")
    assert "Profil:" in format_hardware_summary(fake_hw, t_auto, lang="tr")


def test_updater_semver_assets_and_sha256(tmp_path):
    assert parse_semver("v1.2.3") == (1, 2, 3, 1)
    assert parse_semver("1.2.3-beta.1") == (1, 2, 3, 0)
    assert is_newer_version("v1.0.1", "1.0.0") is True
    assert is_newer_version("1.0.0", "1.0.0-rc1") is True
    assert is_newer_version("1.0.0", "1.0.0") is False

    assets = [
        {"name": "LocalRecall-Portable-v1.1.0-Windows-x64.zip", "browser_download_url": "https://example/win.zip", "size": 100},
        {"name": "LocalRecall-Setup-v1.1.0-Windows-x64.exe", "browser_download_url": "https://example/win.exe", "size": 120},
        {"name": "LocalRecall-v1.1.0-macOS-arm64.dmg", "browser_download_url": "https://example/mac.dmg", "size": 130},
        {"name": "LocalRecall-v1.1.0-Linux-x86_64.tar.gz", "browser_download_url": "https://example/linux.tar.gz", "size": 110},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://example/SHA256SUMS.txt", "size": 50},
    ]
    win_name, _, _, win_cs = select_platform_asset(assets, platform_name="win32", machine="AMD64")
    assert win_name == "LocalRecall-Setup-v1.1.0-Windows-x64.exe"
    assert win_cs.endswith("SHA256SUMS.txt")

    mac_name, _, _, _ = select_platform_asset(assets, platform_name="darwin", machine="arm64")
    assert mac_name == "LocalRecall-v1.1.0-macOS-arm64.dmg"

    lin_name, _, _, _ = select_platform_asset(assets, platform_name="linux", machine="x86_64")
    assert lin_name == "LocalRecall-v1.1.0-Linux-x86_64.tar.gz"

    sample_file = tmp_path / "LocalRecall-v1.1.0-macOS-arm64.dmg"
    sample_file.write_bytes(b"localrecall-release-bytes")
    digest = compute_file_sha256(str(sample_file))
    sums_text = f"{digest}  LocalRecall-v1.1.0-macOS-arm64.dmg\n"
    parsed = parse_sha256sums(sums_text, "LocalRecall-v1.1.0-macOS-arm64.dmg")
    assert parsed == digest
    assert verify_file_sha256(str(sample_file), digest) is True
    assert verify_file_sha256(str(sample_file), "0" * 64) is False


def test_i18n_parity_and_autostart_files(tmp_path):
    assert set(TRANSLATIONS["en"].keys()) == set(TRANSLATIONS["tr"].keys())

    mgr = LanguageManager("en")
    assert mgr.t("nav_privacy") == "Privacy Shield"
    mgr.set_language("tr")
    assert mgr.t("nav_privacy") == "Gizlilik Kalkanı"
    assert tr("results_header", lang="en", count=12) == "Captures (12)"
    assert tr("unknown_key_xyz", lang="tr") == "unknown_key_xyz"

    # macOS LaunchAgent plist creation & removal in temp dir
    plist_file = tmp_path / "com.andacbasaran.localrecall.plist"
    assert set_macos_autostart(True, plist_path=plist_file) is True
    data = plistlib.loads(plist_file.read_bytes())
    assert "--minimized" in data["ProgramArguments"]
    assert set_macos_autostart(False, plist_path=plist_file) is True
    assert not plist_file.exists()

    # Linux XDG desktop entry creation & removal in temp dir
    desktop_file = tmp_path / "localrecall.desktop"
    assert set_linux_autostart(True, desktop_path=desktop_file) is True
    content = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content and "--minimized" in content
    assert set_linux_autostart(False, desktop_path=desktop_file) is True
    assert not desktop_file.exists()
