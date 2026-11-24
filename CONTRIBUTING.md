# Contributing to LocalRecall

Thank you for considering contributing to **LocalRecall**! Every contribution — bug reports, OS/Wayland compatibility entries, password-manager blocklist additions, PII pattern refinements, translations, or performance optimizations — helps build a truly open, private, and cross-platform screen memory tool.

## Ways to Contribute

1. **Report Bugs & Edge Cases:** Open an issue using the Bug Report template (include OS, display server, version, and redacted logs).
2. **Expand OS & App Compatibility:** Tested LocalRecall on a new Linux desktop environment, macOS version, or multi-monitor setup? Open a PR updating [COMPATIBILITY.md](COMPATIBILITY.md).
3. **Strengthen Privacy Shield & PII Rules:** Suggest new password manager process names (`src/localrecall/capture/privacy.py`) or zero-false-positive secret patterns (`src/localrecall/capture/pii.py`) with unit tests.
4. **Code & UX Improvements:** Contribute to search ranking (`src/localrecall/search/hybrid.py`), OCR pipelines (`src/localrecall/ocr/engine.py`), or Studio 2.0 UI (`src/localrecall/ui/`).

## Development Setup

```bash
git clone https://github.com/Andacbasaran/LocalRecall.git
cd LocalRecall
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install --prefer-binary -r requirements.txt pytest ruff
pip install -e . --no-deps
```

## Running Tests & Linter

Before opening a Pull Request, please verify all checks pass locally:

```bash
# Lint check (must report 0 errors)
ruff check .

# Full automated unit & offscreen Studio 2.0 UI test suite
QT_QPA_PLATFORM=offscreen pytest -v

# Optional: refresh local performance metrics
QT_QPA_PLATFORM=offscreen python scripts/benchmark.py
```

## Pull Request Guidelines

- Keep PRs focused on a single feature, bug fix, privacy enhancement, or documentation update.
- **Strictly preserve 100% offline, 0 MB VRAM default behavior:** Never transmit screenshots, OCR text, notes, or telemetry to any external service.
- Keep `src/localrecall/i18n.py` synchronized across both English (`en`) and Turkish (`tr`) strings when adding UI labels.
- Add or update unit tests in `tests/` for all new logic and bug fixes.
- Follow Conventional Commits (`feat:`, `fix:`, `privacy:`, `perf:`, `docs:`, `refactor:`, `test:`, `chore:`).
