"""Realistic 8-frame synthetic Demo Timeline generator and Daily Markdown Digest exporter."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from localrecall.ocr.engine import OCRBox, OCRResult
from localrecall.storage.database import CaptureRecord, Database
from localrecall.storage.media import MediaStore


def _load_font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/SFNSMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "C:/Windows/Fonts/consola.ttf",
        ]
        if mono
        else [
            "/System/Library/Fonts/SFNS.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
    )
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _render_desktop_frame(
    theme_bg: tuple[int, int, int],
    sidebar_bg: tuple[int, int, int],
    accent: tuple[int, int, int],
    app_header: str,
    sidebar_items: list[str],
    content_lines: list[tuple[str, tuple[int, int, int], bool]],
    status_bar: str,
    width: int = 1280,
    height: int = 720,
    mono: bool = True,
) -> tuple[Image.Image, list[OCRBox]]:
    """Renders a crisp realistic app screenshot and returns exact normalized OCRBox coordinates."""
    img = Image.new("RGB", (width, height), color=theme_bg)
    draw = ImageDraw.Draw(img)

    font_hdr = _load_font(17, mono=False)
    font_side = _load_font(15, mono=False)
    font_body = _load_font(19, mono=mono)
    font_small = _load_font(14, mono=False)

    # Top title bar
    draw.rectangle((0, 0, width, 44), fill=sidebar_bg)
    draw.line((0, 44, width, 44), fill=(38, 40, 48), width=1)
    # macOS-style subtle window dots
    for idx, dot_col in enumerate(((239, 68, 68), (245, 158, 11), (34, 197, 94))):
        cx = 22 + idx * 20
        draw.ellipse((cx - 5, 17, cx + 5, 27), fill=dot_col)

    draw.text((92, 12), app_header, fill=(228, 228, 234), font=font_hdr)

    # Left navigation sidebar
    side_w = 236
    draw.rectangle((0, 45, side_w, height - 30), fill=sidebar_bg)
    draw.line((side_w, 45, side_w, height - 30), fill=(38, 40, 48), width=1)

    boxes: list[OCRBox] = []

    y_side = 68
    for i, item in enumerate(sidebar_items):
        if i == 1:
            draw.rounded_rectangle((12, y_side - 6, side_w - 14, y_side + 26), radius=6, fill=(32, 36, 46))
            draw.rectangle((12, y_side - 2, 16, y_side + 22), fill=accent)
            col = (250, 250, 252)
        else:
            col = (148, 152, 166)
        draw.text((26, y_side), item, fill=col, font=font_side)
        y_side += 36

    # Main content card
    content_x = side_w + 32
    draw.rounded_rectangle(
        (content_x - 16, 66, width - 28, height - 48),
        radius=10,
        fill=(theme_bg[0] + 5, theme_bg[1] + 5, theme_bg[2] + 8),
        outline=(38, 40, 48),
        width=1,
    )

    y_cursor = 88
    for line_text, color, is_heading in content_lines:
        fnt = _load_font(22, mono=False) if is_heading else font_body
        if line_text.strip():
            bbox = draw.textbbox((content_x + 8, y_cursor), line_text, font=fnt)
            draw.text((content_x + 8, y_cursor), line_text, fill=color, font=fnt)
            x0, y0, x1, y1 = bbox
            boxes.append(
                OCRBox(
                    text=line_text.strip(),
                    x=round(max(0.0, x0 / width), 4),
                    y=round(max(0.0, y0 / height), 4),
                    w=round(max(0.01, (x1 - x0) / width), 4),
                    h=round(max(0.01, (y1 - y0) / height), 4),
                    score=0.98,
                )
            )
        y_cursor += 38 if is_heading else 32
        if y_cursor > height - 76:
            break

    # Bottom status bar
    draw.rectangle((0, height - 30, width, height), fill=sidebar_bg)
    draw.line((0, height - 30, width, height - 30), fill=(38, 40, 48), width=1)
    draw.ellipse((16, height - 19, 24, height - 11), fill=accent)
    draw.text((34, height - 23), status_bar, fill=(161, 161, 170), font=font_small)

    return img, boxes


def populate_demo_timeline(db: Database, media: MediaStore) -> int:
    """
    Populates 8 realistic multi-app desktop frames with exact OCR bounding boxes,
    bilingual EN/TR text, pinned moment, and realistic Privacy Shield telemetry.
    """
    now = datetime.now()
    specs = [
        {
            "minutes_ago": 420,
            "app": "Figma",
            "title": "LocalRecall Studio 2.0 — Design Tokens & Timeline Ribbon",
            "bg": (16, 16, 20),
            "side": (22, 22, 27),
            "accent": (56, 189, 248),
            "mono": False,
            "pinned": False,
            "note": "",
            "sidebar": ["Pages", "Studio 2.0 Canvas", "Color Tokens", "Timeline Ribbon", "Privacy Shield", "App Icon 512px"],
            "lines": [
                ("LocalRecall v1.0.0 — Studio Graphite Design System", (250, 250, 252), True),
                ("Primary Canvas: #0A0A0C   Sidebar Rail: #111113   Surface Card: #141417", (161, 161, 170), False),
                ("Signature Accent: Sky Blue #38BDF8 · OCR Highlight: Amber #F59E0B", (56, 189, 248), False),
                ("Privacy Shield Active: Emerald #10B981 · Panic Wipe: Rose #E11D48", (16, 185, 129), False),
                ("Interactive Timeline Scrubber: Color-coded app activity segments", (228, 228, 234), False),
                ("Zero external cloud calls · 100% Local SQLite FTS5 + WebP Vault", (245, 158, 11), False),
            ],
            "status": "Figma Desktop · 100% Zoom · 4 Components Selected · Synced",
        },
        {
            "minutes_ago": 350,
            "app": "Slack",
            "title": "#eng-release — LocalRecall v1.0.0 Launch Checklist",
            "bg": (18, 18, 23),
            "side": (24, 21, 30),
            "accent": (168, 85, 247),
            "mono": False,
            "pinned": False,
            "note": "",
            "sidebar": ["Channels", "#eng-release", "#privacy-audit", "#benchmarks", "#design-review", "Direct Messages"],
            "lines": [
                ("#eng-release · LocalRecall v1.0.0 Readiness Thread", (250, 250, 252), True),
                ("Andac: SQLite FTS5 Turkish diacritic folding drops latency under 2 ms at 10k rows.", (228, 228, 234), False),
                ("Deniz: Verified macOS Apple Silicon idle sleep via CoreGraphics with zero extra deps!", (161, 161, 170), False),
                ("Selin: PII Redaction Shield caught test Stripe key and blurred the WebP box cleanly.", (16, 185, 129), False),
                ("Action Item: Verify PostgreSQL migration docs and quarterly budget sheet before tag.", (245, 158, 11), False),
                ("Not: Hızlı ekran hafızası Türkçe şifre ve gizlilik testleri %100 geçti.", (56, 189, 248), False),
            ],
            "status": "Slack · 4 members active · All checks green",
        },
        {
            "minutes_ago": 275,
            "app": "LibreOffice Calc",
            "title": "Q4_Infrastructure_Budget_2026.xlsx — Storage & Cost Forecast",
            "bg": (15, 19, 20),
            "side": (20, 25, 26),
            "accent": (16, 185, 129),
            "mono": True,
            "pinned": False,
            "note": "",
            "sidebar": ["Sheets", "Storage Projection", "CPU Telemetry", "Cloud vs Local", "Q4 Budget", "Summary KPI"],
            "lines": [
                ("Q4 Storage & Cloud Cost Comparison — 30-Day Screen Memory", (250, 250, 252), True),
                ("Metric                     LocalRecall v1.0      Cloud Recall SaaS", (56, 189, 248), False),
                ("WebP Frame Size (1080p)    42 KB / unique frame  N/A (uploaded)", (228, 228, 234), False),
                ("Ring-Buffer Dedup Ratio    88.4% skipped frames  35.0% skipped", (16, 185, 129), False),
                ("Monthly Storage Footprint  1.85 GB (5 GB cap)    24.0 GB cloud", (245, 158, 11), False),
                ("Quarterly Revenue Impact   $0/mo (100% offline)  $180/seat/year", (228, 228, 234), False),
            ],
            "status": "Sheet: Storage Projection · 0 MB VRAM · 100% Offline Vault",
        },
        {
            "minutes_ago": 210,
            "app": "Chrome",
            "title": "PostgreSQL 17 & SQLite FTS5 Full-Text Search Architecture — Docs",
            "bg": (16, 18, 24),
            "side": (22, 24, 32),
            "accent": (59, 130, 246),
            "mono": False,
            "pinned": False,
            "note": "",
            "sidebar": ["Documentation", "FTS5 Indexing", "BM25 Ranking", "Unicode61 Tokenizer", "WAL Checkpoints", "Query Operators"],
            "lines": [
                ("SQLite FTS5 External Content & Diacritic-Folded Search Guide", (250, 250, 252), True),
                ("CREATE VIRTUAL TABLE captures_fts USING fts5(app_name, window_title, ocr_text_folded)", (56, 189, 248), False),
                ("Benchmark: Sub-2ms query latency across 100,000+ indexed screen captures.", (16, 185, 129), False),
                ("Operators: app:code  \"exact phrase\"  -exclude  pinned:true", (245, 158, 11), False),
                ("Reciprocal Rank Fusion (RRF) merges BM25 exact hits with character 3-gram fuzzy scores.", (228, 228, 234), False),
                ("PostgreSQL GIN index comparison: local SQLite WAL needs zero daemon overhead.", (161, 161, 170), False),
            ],
            "status": "https://sqlite.org/fts5.html · Reader View · Secure Local Docs",
        },
        {
            "minutes_ago": 145,
            "app": "Terminal",
            "title": "zsh — localrecall/scripts/benchmark.py (Apple Silicon arm64)",
            "bg": (11, 12, 15),
            "side": (17, 18, 22),
            "accent": (34, 197, 94),
            "mono": True,
            "pinned": False,
            "note": "",
            "sidebar": ["Sessions", "benchmark.py", "pytest -v", "ruff check .", "build_macos.py", "git status"],
            "lines": [
                ("$ QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark.py", (56, 189, 248), False),
                ("[OK] Hardware: Apple Silicon ARM64 · ONNX CPU: 2 threads · 0 MB VRAM", (16, 185, 129), False),
                ("[OK] FrameDiffLock (Ring-Buffer=8): 0.34 ms/frame · 91.2% static skip", (228, 228, 234), False),
                ("[OK] SQLite FTS5 Turkish Folded Search (10,000 rows): 1.18 ms p50", (245, 158, 11), False),
                ("[OK] PII Redaction Shield: 100% block rate (API keys, cards, IBAN, OTP)", (16, 185, 129), False),
                ("[OK] Deployment Pipeline: All 42 unit & Studio UI tests PASSED (0 errors)", (34, 197, 94), False),
            ],
            "status": "zsh · exit 0 · 0 MB VRAM · CPU 0.4%",
        },
        {
            "minutes_ago": 90,
            "app": "Chrome",
            "title": "GitHub PR #48 — Release LocalRecall v1.0.0 Cross-Platform Studio",
            "bg": (14, 17, 22),
            "side": (20, 24, 31),
            "accent": (245, 158, 11),
            "mono": False,
            "pinned": False,
            "note": "",
            "sidebar": ["Pull Request #48", "Conversation", "Commits (14)", "CI Checks (4/4)", "Files Changed", "Release Assets"],
            "lines": [
                ("PR #48: Upgrade LocalRecall to v1.0.0 Flagship Cross-Platform Studio", (250, 250, 252), True),
                ("CI Matrix: Windows x64 PASS · macOS arm64 PASS · Ubuntu x64 PASS · Ruff 0 errors", (16, 185, 129), False),
                ("Fixed: Privacy blocklist extensionless match, monitor_index=0, non-ASCII OCR path.", (228, 228, 234), False),
                ("Added: PII & Secret Auto-Redaction Shield with automatic WebP region blur.", (56, 189, 248), False),
                ("Added: Bilingual EN/TR Studio 2.0 UI, App-Colored Timeline Ribbon & Daily Digest.", (245, 158, 11), False),
                ("SHA256SUMS.txt verified for Windows Setup, macOS DMG, and Linux tar.gz.", (161, 161, 170), False),
            ],
            "status": "github.com/Andacbasaran/LocalRecall/pull/48 · Ready to Merge",
        },
        {
            "minutes_ago": 35,
            "app": "VS Code",
            "title": "pii.py — LocalRecall Privacy & Secret Redaction Engine",
            "bg": (13, 14, 18),
            "side": (18, 19, 24),
            "accent": (16, 185, 129),
            "mono": True,
            "pinned": False,
            "note": "",
            "sidebar": ["Explorer", "pii.py", "privacy.py", "database.py", "hybrid.py", "main_window.py"],
            "lines": [
                ("src/localrecall/capture/pii.py — Automatic Offline Secret Shield", (250, 250, 252), True),
                ("STRIPE_KEY_DEMO = '[REDACTED:API_KEY]'  # Blurred on WebP automatically", (16, 185, 129), False),
                ("def redact_ocr_boxes(self, boxes: Sequence[OCRBox]) -> RedactionResult:", (56, 189, 248), False),
                ("    # Zero cloud telemetry · Luhn card validation · IBAN · JWT · 6-digit OTP", (161, 161, 170), False),
                ("    return blur_image_regions(image, sensitive_boxes)", (228, 228, 234), False),
                ("# 1Password & Keychain Access auto-skipped before screenshot grab", (245, 158, 11), False),
            ],
            "status": "Python 3.11 · Ruff Clean · Privacy Shield ACTIVE (PII Redacted)",
            "pii_redacted": True,
        },
        {
            "minutes_ago": 4,
            "app": "VS Code",
            "title": "hybrid.py — LocalRecall v1.0.0 Hybrid FTS5 & RRF Search Engine",
            "bg": (13, 14, 18),
            "side": (18, 19, 24),
            "accent": (56, 189, 248),
            "mono": True,
            "pinned": True,
            "note": "Key search architecture milestone — <2 ms Turkish-folded FTS5 + RRF!",
            "sidebar": ["Explorer", "hybrid.py", "database.py", "monitor.py", "engine.py", "widgets.py"],
            "lines": [
                ("src/localrecall/search/hybrid.py — LocalRecall Search Engine", (250, 250, 252), True),
                ("class HybridSearchEngine:  # 100% Offline SQLite FTS5 + N-Gram RRF", (56, 189, 248), False),
                ("    def search(self, query: str, mode: str = 'hybrid') -> list[SearchResult]:", (228, 228, 234), False),
                ("        # Supports app:vscode, \"exact phrase\", -exclude, pinned:true", (245, 158, 11), False),
                ("        # LocalRecall hızlı ekran hafızası: Turkish folded FTS5 in <2 ms", (16, 185, 129), False),
                ("        return reciprocal_rank_fusion(fts_hits, fuzzy_candidates)", (228, 228, 234), False),
            ],
            "status": "VS Code · LocalRecall v1.0.0 · 0 MB VRAM · 100% Local",
        },
    ]

    inserted = 0
    for spec in specs:
        ts = now - timedelta(minutes=int(spec["minutes_ago"]))
        img, boxes = _render_desktop_frame(
            theme_bg=spec["bg"],
            sidebar_bg=spec["side"],
            accent=spec["accent"],
            app_header=f"{spec['app']} — {spec['title']}",
            sidebar_items=spec["sidebar"],
            content_lines=spec["lines"],
            status_bar=spec["status"],
            mono=bool(spec["mono"]),
        )
        rel_path, w, h, size_bytes = media.save_image_with_size(img, timestamp=ts)
        ocr_text = "\n".join(line[0] for line in spec["lines"])
        res = OCRResult(text=ocr_text, boxes=boxes)
        db.insert_capture(
            image_path=rel_path,
            app_name=str(spec["app"]),
            window_title=str(spec["title"]),
            width=w,
            height=h,
            ocr_text=res.text,
            ocr_done=True,
            ocr_boxes=res.boxes_to_json(),
            timestamp=ts,
            file_size_bytes=size_bytes,
            pinned=bool(spec.get("pinned", False)),
            note=str(spec.get("note", "")),
            pii_redacted=bool(spec.get("pii_redacted", False)),
        )
        inserted += 1

    # Seed realistic Privacy Shield & Dedup telemetry (e.g. blocked 1Password + incognito tabs)
    stats = db.get_stats()
    if stats["privacy_blocks"] == 0:
        db.set_metric("privacy_blocks_count", 14)
    if stats["pii_redactions"] == 0:
        db.set_metric("pii_redactions_count", 3)
    if stats["dedup_checked"] == 0:
        db.set_metric("dedup_checked_count", 420)
        db.set_metric("dedup_skipped_count", 374)

    return inserted


def export_daily_markdown_digest(
    records: list[CaptureRecord],
    output_path: Path,
    title: str | None = None,
) -> Path:
    """Exports a structured Markdown activity & OCR digest grouped by application."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    heading = title or f"LocalRecall Activity Digest — {datetime.now().strftime('%Y-%m-%d')}"

    by_app: dict[str, list[CaptureRecord]] = defaultdict(list)
    for rec in records:
        by_app[rec.app_name or "Desktop"].append(rec)

    lines: list[str] = [
        f"# {heading}",
        "",
        f"> Generated locally by **LocalRecall v1.0.0** on `{now_str}` · 100% Offline · {len(records)} capture(s)",
        "",
        "## Summary by Application",
        "",
        "| Application | Captures | Pinned |",
        "| :--- | :---: | :---: |",
    ]
    for app_name, items in sorted(by_app.items(), key=lambda kv: len(kv[1]), reverse=True):
        pin_cnt = sum(1 for r in items if r.pinned)
        lines.append(f"| **{app_name}** | {len(items)} | {pin_cnt} |")

    lines.extend(["", "## Chronological Timeline", ""])
    ordered = sorted(records, key=lambda r: r.timestamp)
    for rec in ordered:
        ts_clean = rec.timestamp.replace("T", " ")
        pin_badge = " `[PINNED]`" if rec.pinned else ""
        pii_badge = " `[PII REDACTED]`" if rec.pii_redacted else ""
        lines.append(f"### `{ts_clean}` — **{rec.app_name or 'Desktop'}** · {rec.window_title or '(Untitled)'}{pin_badge}{pii_badge}")
        if rec.note:
            lines.append(f"- **Note:** {rec.note}")
        snippet_lines = [ln.strip() for ln in (rec.ocr_text or "").splitlines() if ln.strip()][:6]
        if snippet_lines:
            lines.append("```text")
            lines.extend(snippet_lines)
            lines.append("```")
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
