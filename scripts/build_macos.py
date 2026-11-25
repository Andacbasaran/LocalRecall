#!/usr/bin/env python3
"""
LocalRecall v1.0.0 — macOS (Apple Silicon arm64 / x86_64) .app & .dmg Builder.

Features:
1. Verifies/builds assets/app_icon.icns from assets/app_icon.png.
2. Compiles standalone dist/LocalRecall.app via PyInstaller (--onedir --windowed).
3. Injects NSScreenCaptureUsageDescription, NSHighResolutionCapable, and bundle metadata into Info.plist.
4. Signs the bundle with ad-hoc or Developer ID (MACOS_SIGN_IDENTITY) codesign.
5. Creates compressed UDZO .dmg with Applications symlink, FIRST_LAUNCH_GUIDE.txt, and SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PIL import Image

APP_NAME = "LocalRecall"
BUNDLE_ID = "com.andacbasaran.localrecall"
DEFAULT_VERSION = "1.0.0"

FIRST_LAUNCH_GUIDE = """\
========================================================================
LocalRecall — macOS Quick Installation & Privacy Guide
========================================================================

1. INSTALL
   Drag "LocalRecall.app" into the "Applications" folder.

2. FIRST LAUNCH (Unsigned Open-Source Gatekeeper Notice)
   LocalRecall is free, MIT open-source software without a paid Apple
   Developer ID notarization certificate. If macOS says the developer
   cannot be verified, either:

   Option A (System Settings):
   - Try opening LocalRecall, dismiss the dialog.
   - Go to System Settings -> Privacy & Security -> click "Open Anyway".

   Option B (Terminal — one command):
   xattr -cr "/Applications/LocalRecall.app"

3. SCREEN RECORDING PERMISSION (Required)
   To capture app windows (instead of blank wallpaper):
   System Settings -> Privacy & Security -> Screen & System Audio Recording
   -> enable "LocalRecall" and restart the app.

4. VAULT LOCATION (100% Local)
   Your SQLite database and local WebP captures (0o600 user-only permissions) live locally at:
   ~/Library/Application Support/LocalRecall
========================================================================
"""


def read_project_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return DEFAULT_VERSION


def ensure_icns_icon(root: Path) -> Optional[Path]:
    icns_path = root / "assets" / "app_icon.icns"
    png_path = root / "assets" / "app_icon.png"
    if icns_path.exists() and icns_path.stat().st_size > 1024:
        return icns_path
    if not png_path.exists():
        print("[WARN] assets/app_icon.png not found.")
        return None

    print("[1/5] Generating assets/app_icon.icns...")
    mapping = [
        (b"icp4", 16),
        (b"ic11", 32),
        (b"icp5", 32),
        (b"ic12", 64),
        (b"ic07", 128),
        (b"ic13", 256),
        (b"ic08", 256),
        (b"ic14", 512),
        (b"ic09", 512),
    ]
    chunks: list[bytes] = []
    with Image.open(png_path) as img:
        for ostype, px in mapping:
            resized = img.resize((px, px), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            data = buf.getvalue()
            chunks.append(ostype + struct.pack(">I", len(data) + 8) + data)
    body = b"".join(chunks)
    icns_path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    return icns_path


def build_app_bundle(root: Path, icns_path: Optional[Path], arch: str) -> Path:
    print(f"[2/5] Building '{APP_NAME}.app' ({arch}) via PyInstaller...")
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
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--target-arch",
        arch,
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "onnxruntime",
        "--collect-submodules",
        "localrecall",
        "--hidden-import",
        "PyQt6.QtNetwork",
        "--hidden-import",
        "certifi",
        "--hidden-import",
        "mss",
        "--hidden-import",
        "PIL",
    ]
    if icns_path and icns_path.exists():
        cmd.extend(["--icon", str(icns_path), "--add-data", f"{icns_path}:assets"])

    png_path = root / "assets" / "app_icon.png"
    if png_path.exists():
        cmd.extend(["--add-data", f"{png_path}:assets"])

    cmd.append(str(root / "main.py"))
    env = os.environ.copy()
    pyi_cache = root / "build" / "pyinstaller_cache"
    pyi_cache.mkdir(parents=True, exist_ok=True)
    env["PYINSTALLER_CONFIG_DIR"] = str(pyi_cache)
    subprocess.run(cmd, cwd=root, env=env, check=True)

    app_path = root / "dist" / f"{APP_NAME}.app"
    if not app_path.is_dir():
        raise RuntimeError(f"Expected .app bundle not found: {app_path}")
    return app_path


def update_info_plist(app_path: Path, version: str) -> None:
    print("[3/5] Updating Info.plist with macOS Screen Recording privacy metadata...")
    plist_path = app_path / "Contents" / "Info.plist"
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    plist["CFBundleDisplayName"] = APP_NAME
    plist["CFBundleName"] = APP_NAME
    plist["CFBundleIdentifier"] = BUNDLE_ID
    plist["CFBundleShortVersionString"] = version
    plist["CFBundleVersion"] = version
    plist["LSMinimumSystemVersion"] = "12.0"
    plist["LSApplicationCategoryType"] = "public.app-category.productivity"
    plist["NSHighResolutionCapable"] = True
    plist["NSSupportsAutomaticGraphicsSwitching"] = True
    plist["NSScreenCaptureUsageDescription"] = (
        "LocalRecall needs Screen Recording permission to build your 100% local, "
        "searchable screen memory vault. No data ever leaves your Mac."
    )

    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)


def codesign_app(app_path: Path) -> None:
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "-").strip() or "-"
    label = "Ad-hoc" if identity == "-" else f"Developer ID ({identity})"
    print(f"[4/5] Codesigning {app_path.name} ({label})...")
    cmd = ["codesign", "--force", "--deep", "--sign", identity]
    if identity != "-":
        cmd.extend(["--options", "runtime", "--timestamp"])
    cmd.append(str(app_path))
    subprocess.run(cmd, check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app_path)], check=True)
    print("[OK] Codesign verified.")


def create_dmg(root: Path, app_path: Path, version: str, arch: str) -> Path:
    dmg_name = f"{APP_NAME}-v{version}-macOS-{arch}.dmg"
    dmg_path = root / "dist" / dmg_name
    if dmg_path.exists():
        dmg_path.unlink()

    print(f"[5/5] Creating DMG installer: {dmg_name}...")
    staging = root / "build" / "dmg_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(app_path, staging / app_path.name, symlinks=True)
        os.symlink("/Applications", staging / "Applications")
        (staging / "FIRST_LAUNCH_GUIDE.txt").write_text(FIRST_LAUNCH_GUIDE, encoding="utf-8")

        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"{APP_NAME} v{version}",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                "-imagekey",
                "zlib-level=9",
                str(dmg_path),
            ],
            check=True,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    sha = hashlib.sha256()
    with open(dmg_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    (root / "dist" / "SHA256SUMS-macOS.txt").write_text(f"{digest}  {dmg_name}\n", encoding="ascii")
    size_mb = dmg_path.stat().st_size / (1024 * 1024)
    print(f"[OK] DMG ready: {dmg_path} ({size_mb:.1f} MB)")
    print(f"[OK] SHA-256: {digest}")
    return dmg_path


def main() -> int:
    if sys.platform != "darwin":
        print("[ERROR] build_macos.py must be run on macOS.")
        return 1

    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build LocalRecall macOS .app and .dmg")
    parser.add_argument("--version", default=read_project_version(root))
    parser.add_argument("--arch", default="arm64", choices=["arm64", "x86_64", "universal2"])
    parser.add_argument("--skip-dmg", action="store_true")
    args = parser.parse_args()
    version = args.version.lstrip("v")

    icns = ensure_icns_icon(root)
    app_path = build_app_bundle(root, icns, args.arch)
    update_info_plist(app_path, version)
    codesign_app(app_path)
    if not args.skip_dmg:
        create_dmg(root, app_path, version, args.arch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
