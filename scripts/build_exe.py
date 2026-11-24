#!/usr/bin/env python3
"""
LocalRecall v1.0.0 — Windows x64 PyInstaller (--onedir) & Portable ZIP Builder.

Usage:
    python scripts/build_exe.py
    python scripts/build_exe.py --version 1.0.0
    python scripts/build_exe.py --skip-zip
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "LocalRecall"
DEFAULT_VERSION = "1.0.0"

HIDDEN_IMPORTS = [
    "localrecall",
    "localrecall.config",
    "localrecall.demo",
    "localrecall.hardware",
    "localrecall.i18n",
    "localrecall.updater",
    "localrecall.capture.diff",
    "localrecall.capture.monitor",
    "localrecall.capture.pii",
    "localrecall.capture.privacy",
    "localrecall.capture.window_info",
    "localrecall.ocr.engine",
    "localrecall.search.hybrid",
    "localrecall.storage.database",
    "localrecall.storage.media",
    "localrecall.ui.hotkey",
    "localrecall.ui.main_window",
    "localrecall.ui.preview_widget",
    "localrecall.ui.settings_dialog",
    "localrecall.ui.theme",
    "localrecall.ui.tray",
    "localrecall.ui.widgets",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "mss",
    "PIL",
    "certifi",
]


def read_project_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_onedir(root: Path) -> Path:
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--paths",
        str(root / "src"),
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "onnxruntime",
        "--collect-submodules",
        "localrecall",
    ]
    for mod in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", mod])

    ico = root / "assets" / "app_icon.ico"
    if ico.exists() and sys.platform == "win32":
        cmd.extend(["--icon", str(ico)])

    assets_dir = root / "assets"
    if assets_dir.is_dir():
        for fname in ("app_icon.png", "app_icon.ico", "app_icon.svg"):
            fp = assets_dir / fname
            if fp.exists():
                cmd.extend(["--add-data", f"{fp}{sep}assets"])

    cmd.append(str(root / "main.py"))

    env = os.environ.copy()
    pyi_cache = root / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)

    print("[1/2] Running PyInstaller:", " ".join(cmd))
    subprocess.run(cmd, cwd=root, env=env, check=True)

    app_dir = root / "dist" / APP_NAME
    if not app_dir.is_dir():
        raise RuntimeError(f"Expected PyInstaller output not found: {app_dir}")
    print(f"[OK] PyInstaller bundle built: {app_dir}")
    return app_dir


def package_portable_zip(root: Path, version: str) -> Path:
    dist_dir = root / "dist"
    zip_base = dist_dir / f"{APP_NAME}-Portable-v{version}-Windows-x64"
    archive = Path(shutil.make_archive(str(zip_base), "zip", root_dir=dist_dir, base_dir=APP_NAME))
    digest = sha256_file(archive)
    sums = dist_dir / "SHA256SUMS-Windows.txt"
    sums.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"[2/2] Portable ZIP ready: {archive} ({size_mb:.1f} MB)")
    print(f"[OK] SHA-256: {digest}")
    return archive


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build LocalRecall Windows PyInstaller bundle & ZIP")
    parser.add_argument("--version", default=read_project_version(root))
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    build_onedir(root)
    if not args.skip_zip:
        package_portable_zip(root, version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
