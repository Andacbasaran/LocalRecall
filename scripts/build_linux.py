#!/usr/bin/env python3
"""
LocalRecall v1.0.0 — Linux Portable .tar.gz & AppDir/AppImage Builder.

Usage:
    python scripts/build_linux.py
    python scripts/build_linux.py --version 1.0.0 --arch x86_64 --skip-appimage
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import List, Optional

APP_NAME = "LocalRecall"
DESKTOP_ID = "com.andacbasaran.LocalRecall.desktop"
ICON_NAME = "localrecall"
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
    print(f"[1/4] Building PyInstaller --onedir bundle '{APP_NAME}'...")
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

    assets_dir = root / "assets"
    if assets_dir.is_dir():
        for fname in ("app_icon.png", "app_icon.svg"):
            fp = assets_dir / fname
            if fp.exists():
                cmd.extend(["--add-data", f"{fp}:assets"])

    cmd.append(str(root / "main.py"))

    env = os.environ.copy()
    pyi_cache = root / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)
    subprocess.run(cmd, cwd=root, env=env, check=True)

    bundle_dir = root / "dist" / APP_NAME
    if not bundle_dir.is_dir():
        raise RuntimeError(f"Expected bundle not found: {bundle_dir}")
    return bundle_dir


def create_tarball(root: Path, bundle_dir: Path, version: str, arch: str) -> Path:
    tar_name = f"{APP_NAME}-v{version}-Linux-{arch}.tar.gz"
    tar_path = root / "dist" / tar_name
    if tar_path.exists():
        tar_path.unlink()

    print(f"[2/4] Packaging portable archive: {tar_name}...")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=APP_NAME)
    return tar_path


def assemble_appdir(root: Path, bundle_dir: Path) -> Path:
    print(f"[3/4] Assembling dist/{APP_NAME}.AppDir...")
    appdir = root / "dist" / f"{APP_NAME}.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    usr_bin = appdir / "usr" / "bin"
    usr_apps = appdir / "usr" / "share" / "applications"
    usr_icons = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    usr_apps.mkdir(parents=True, exist_ok=True)
    usr_icons.mkdir(parents=True, exist_ok=True)

    shutil.copytree(bundle_dir, usr_bin, symlinks=True)

    apprun_src = root / "packaging" / "linux" / "AppRun"
    apprun_dst = appdir / "AppRun"
    shutil.copy2(apprun_src, apprun_dst)
    apprun_dst.chmod(apprun_dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    desktop_src = root / "packaging" / "linux" / DESKTOP_ID
    shutil.copy2(desktop_src, appdir / DESKTOP_ID)
    shutil.copy2(desktop_src, usr_apps / DESKTOP_ID)

    icon_src = root / "assets" / "app_icon.png"
    if icon_src.exists():
        shutil.copy2(icon_src, appdir / f"{ICON_NAME}.png")
        shutil.copy2(icon_src, appdir / ".DirIcon")
        shutil.copy2(icon_src, usr_icons / f"{ICON_NAME}.png")
    return appdir


def build_appimage(root: Path, appdir: Path, version: str, arch: str) -> Optional[Path]:
    tool = shutil.which("appimagetool")
    if not tool:
        print("[INFO] 'appimagetool' not found; skipping AppImage creation.")
        return None
    out_path = root / "dist" / f"{APP_NAME}-v{version}-Linux-{arch}.AppImage"
    if out_path.exists():
        out_path.unlink()
    print(f"[4/4] Building AppImage: {out_path.name}...")
    env = os.environ.copy()
    env["ARCH"] = arch
    subprocess.run([tool, str(appdir), str(out_path)], cwd=root, env=env, check=True)
    return out_path


def write_checksums(root: Path, artifacts: List[Path]) -> Path:
    sums = root / "dist" / "SHA256SUMS-Linux.txt"
    lines = [f"{sha256_file(p)}  {p.name}\n" for p in artifacts]
    sums.write_text("".join(lines), encoding="ascii")
    return sums


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("[ERROR] build_linux.py must be run on Linux.")
        return 1

    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build LocalRecall Linux .tar.gz and AppDir/AppImage")
    parser.add_argument("--version", default=read_project_version(root))
    parser.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64"])
    parser.add_argument("--skip-appimage", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    bundle = build_onedir(root)
    artifacts: List[Path] = [create_tarball(root, bundle, version, args.arch)]
    appdir = assemble_appdir(root, bundle)
    if not args.skip_appimage:
        ai = build_appimage(root, appdir, version, args.arch)
        if ai:
            artifacts.append(ai)
    write_checksums(root, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
