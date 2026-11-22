"""LocalRecall Windows Portable (PyInstaller + ZIP) paketleme betiği."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        "LocalRecall",
        "--paths",
        str(ROOT / "src"),
        "--collect-all",
        "rapidocr_onnxruntime",
        str(ROOT / "main.py"),
    ]
    print("PyInstaller çalıştırılıyor:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    app_dir = DIST_DIR / "LocalRecall"
    zip_base = DIST_DIR / "LocalRecall-Portable-win64"
    if app_dir.exists():
        archive = shutil.make_archive(str(zip_base), "zip", root_dir=DIST_DIR, base_dir="LocalRecall")
        print(f"Portable ZIP oluşturuldu: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
