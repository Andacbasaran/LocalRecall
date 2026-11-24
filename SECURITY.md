# Security & Privacy Policy

## Supported Versions

| Version | Supported |
| :--- | :---: |
| `1.0.x` (Latest) | ✅ |
| `< 1.0.0` | ❌ |

## 100% Offline & Zero-Telemetry Architecture

LocalRecall is engineered from the ground up so your visual history never leaves your device:

- **Zero Cloud Bytes:** Screen capture (`mss`), perceptual deduplication (`FrameDiffLock`), OCR (`RapidOCR` ONNX CPU), PII detection & image blurring, and full-text indexing (`SQLite FTS5`) execute 100% locally on your CPU (`0 MB VRAM`).
- **Local-Only Vault Locations:**
  - **Windows:** `%LOCALAPPDATA%\LocalRecall`
  - **macOS:** `~/Library/Application Support/LocalRecall`
  - **Linux:** `~/.local/share/localrecall` (or `$XDG_DATA_HOME/localrecall`)
- **Defense-in-Depth Privacy Shield:**
  - **Pre-Capture Blocklist:** Password managers (`1Password`, `Bitwarden`, `KeePassXC`, `Keychain Access`, `Passwords`, `gnome-keyring`, `kwalletd`, etc.) and private browser sessions (`Incognito`, `InPrivate`, `Gizli`, `Tor Browser`) are skipped *before* any pixels are captured.
  - **Automatic PII & Secret Redaction:** Offline regex + checksum scanners detect credit cards (Luhn), API keys (`sk-`, `ghp_`, `github_pat_`, `AKIA`, `AIza`, `xox*`, JWT), IBAN, US SSN, Turkish TCKN, and 6-digit OTP codes, redacting OCR text and blurring matching bounding boxes on the stored WebP image (or auto-deleting the capture in `Skip` mode).
  - **Panic Privacy Controls:** One-click permanent deletion of the last 15 minutes, last 1 hour, today, or any single application from both SQLite and disk.
- **Optional Update Checker:** Queries the public GitHub Releases API (`api.github.com`) solely to compare release version tags and verify `SHA256SUMS.txt`. Sends zero user data and can be disabled anytime in *Settings → Updates & Local Benchmark*.

## Binary Integrity & Code Signing

Every official GitHub Release publishes a unified `SHA256SUMS.txt` file. Verify downloads before running:

- **Windows (PowerShell):**
  ```powershell
  Get-FileHash .\LocalRecall-Setup-v1.0.0-Windows-x64.exe -Algorithm SHA256
  ```
- **macOS:**
  ```bash
  shasum -a 256 LocalRecall-v1.0.0-macOS-arm64.dmg
  ```
- **Linux:**
  ```bash
  sha256sum -c --ignore-missing SHA256SUMS.txt
  ```

See [packaging/signpath/README.md](packaging/signpath/README.md) for our SignPath.io free Open Source Code Signing roadmap to eliminate Windows SmartScreen warnings.

## Reporting a Vulnerability

If you discover a security or privacy vulnerability (for example, a Privacy Shield bypass, PII leak, or updater validation bug), **please do not open a public issue**. Instead:

1. Use **GitHub Private Vulnerability Reporting** (*Security → Advisories → Report a vulnerability*) on this repository, or
2. Contact the maintainer directly via the profile email listed on [github.com/Andacbasaran](https://github.com/Andacbasaran).

We aim to acknowledge reports within **48 hours** and issue a patched release promptly.
