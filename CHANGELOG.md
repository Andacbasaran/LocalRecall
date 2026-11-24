# Changelog

All notable changes to **LocalRecall** are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-11-24

### Added
- **Cross-Platform Native Engine (Windows x64, macOS Apple Silicon / Intel, Linux X11/Wayland):**
  - Native active window detection (`Win32`, macOS `NSWorkspace` / `lsappinfo` / `osascript`, Linux `xdotool` / `xprop` + `/proc/<pid>/comm`).
  - Native idle sleep tracking (`GetLastInputInfo` on Windows, `CoreGraphics` on macOS, `xprintidle` / `libXss` on Linux).
  - macOS Screen Recording permission preflight (`CGPreflightScreenCaptureAccess`) with in-app guidance banner.
  - Cross-platform login autostart (`HKCU\...\Run` on Windows, `LaunchAgents` plist on macOS, XDG `.desktop` on Linux).
- **Studio 2.0 4-Page Desktop Interface (PyQt6):**
  - **Timeline & Recall:** High-DPI custom thumbnail result cards, interactive zoom/pan preview stage (`50%–400%`), glowing Amber OCR match highlights, click-to-copy text boxes, annotated PNG export, bookmark pinning, personal notes, and an app-colored visual timeline ribbon with rewind playback.
  - **Activity & Insights:** O(1) SQLite telemetry cards (Total Captures, Ring-Buffer Dedup Savings, Disk Footprint/Quota, Privacy Blocks), Top Applications breakdown with 1-click Filter & Purge, 24-hour activity chart, DB `VACUUM`, retention runner, and Daily Markdown Digest exporter.
  - **Privacy Shield & Vault Controls:** Dedicated Emerald Privacy Shield control center with Password Manager Guard, Incognito Guard, Idle Sleep toggle, live process/title blocklist editors, and Rose Panic Privacy Controls (`Pause 15m/1h`, `Purge Last 15m/1h/Today`).
  - **Settings & Engine Configuration:** Auto hardware/ISA detection (`Auto / Eco / Balanced / Performance`), ONNX CPU thread budget (`0 MB VRAM`), bilingual EN/TR live switching, global hotkey customization, GitHub Releases SemVer auto-updater (SHA-256 verified), and built-in inline benchmark runner.
- **Automatic PII & Secret Redaction Shield (`capture/pii.py`):**
  - Offline regex + checksum engine (`~8.3 µs/frame`) detecting Luhn-validated credit cards, API keys (`sk-`, `ghp_`, `github_pat_`, `AKIA`, `AIza`, `xox*`, JWTs), IBANs, US SSNs, Turkish TCKN, and 6-digit OTP/2FA codes.
  - Supports **Redact Text & Blur Box on WebP**, **Redact OCR Text Only**, **Skip & Delete Capture**, or **Off**.
- **Perceptual Ring-Buffer Deduplication (`FrameDiffLock`, `history=8`):**
  - Skips static scenes and `Alt+Tab` revisits in `~1.25 ms/frame` (`97%` duplicate skip ratio on benchmark workloads).
- **Structured Hybrid Search Engine (`SQLite FTS5` + Turkish Diacritic Folding + N-Gram RRF):**
  - Sub-millisecond diacritic-folded FTS5 queries (`0.64 ms` p50 at 10,000 rows) scaling beyond the fuzzy candidate pool.
  - Structured operators: `app:vscode`, `app:"VS Code"`, `"exact phrase"`, `-exclude`, `pinned:true`, `is:pinned`.
- **Storage Governance & Archival:**
  - Configurable retention window, FIFO storage quota cap (protecting pinned captures), and **OCR-Only Archival Mode** (deletes old WebP images while preserving searchable OCR text).
- **8-Frame Synthetic Demo Timeline & Daily Markdown Digest (`demo.py`):**
  - One-click Demo Timeline loader for instant evaluation without waiting for background captures.
- **Multi-Platform Packaging & CI/CD:**
  - Inno Setup 6 Windows installer (bilingual TR/EN + optional clean vault uninstall), Windows Portable ZIP, macOS Apple Silicon `.dmg`, Linux `.tar.gz` + AppDir, Winget, Scoop, Homebrew Cask, SignPath guide, 3-OS GitHub Actions CI & unified Release pipeline with `SHA256SUMS.txt`.

### Fixed
- Extensionless process blocklist matching (e.g., `Bitwarden`, `Bitwarden.exe`, `1Password.app`, `/usr/bin/bitwarden` all normalize identically).
- `monitor_index=0` ("All Monitors") persistence bug in Settings save flow.
- Non-ASCII filesystem path handling for RapidOCR image loading.
- Startup OCR backfill for unfinished `ocr_done=0` records after unexpected termination.
- O(1) SQLite disk telemetry eliminating UI-thread filesystem walks.

## [0.1.0] — 2026-11-22

### Added
- Initial Windows prototype with MSS screen capture, RapidOCR CPU extraction, SQLite FTS5 + N-Gram hybrid search, basic privacy blocklist, PyQt6 viewer, and system tray.
