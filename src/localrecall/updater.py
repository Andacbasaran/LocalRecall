"""Cross-platform GitHub Releases SemVer auto-updater for LocalRecall."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from localrecall import __repo__, __version__

GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{__repo__}/releases/latest"

ALLOWED_UPDATE_HOSTS: frozenset[str] = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


def validate_update_url(url: str) -> str:
    """Enforces HTTPS and the GitHub release host allowlist for all update requests/redirects."""
    cleaned = (url or "").strip()
    parsed = urllib.parse.urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in ALLOWED_UPDATE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"Blocked untrusted update URL: {cleaned}")
    return cleaned


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validates every HTTP redirect target against the HTTPS + GitHub host allowlist."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved = urllib.parse.urljoin(req.full_url, newurl)
        validate_update_url(resolved)
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _open_verified_url(
    req: urllib.request.Request,
    timeout: float,
    context: Optional[ssl.SSLContext] = None,
):
    validate_update_url(req.full_url)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _SafeRedirectHandler(),
    )
    return opener.open(req, timeout=timeout)


def _make_ssl_context() -> Optional[ssl.SSLContext]:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    is_update_available: bool
    release_url: str
    release_notes: str = ""
    error: Optional[str] = None
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    checksum_url: str = ""

    @property
    def has_direct_installer(self) -> bool:
        return bool(self.asset_url and self.asset_name)


def parse_semver(version_str: str) -> Tuple[int, int, int, int]:
    cleaned = (version_str or "").strip().lstrip("vV")
    core = cleaned.split("+", 1)[0]
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-(.+))?$", core)
    if not match:
        return (0, 0, 0, 0)
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    is_stable = 0 if match.group(4) is not None else 1
    return (major, minor, patch, is_stable)


def _semver_sort_key(
    version_str: str,
) -> Tuple[int, int, int, int, Tuple[Tuple[int, object], ...]]:
    cleaned = (version_str or "").strip().lstrip("vV")
    core = cleaned.split("+", 1)[0]
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-(.+))?$", core)
    if not match:
        return (0, 0, 0, 0, ())
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    prerelease = match.group(4)
    if prerelease is None:
        return (major, minor, patch, 1, ())
    parts = tuple(
        (0, int(tok)) if tok.isdigit() else (1, tok)
        for tok in prerelease.split(".")
        if tok != ""
    )
    return (major, minor, patch, 0, parts)


def is_newer_version(latest: str, current: str) -> bool:
    return _semver_sort_key(latest) > _semver_sort_key(current)


def select_platform_asset(
    assets: List[Dict],
    platform_name: Optional[str] = None,
    machine: Optional[str] = None,
) -> Tuple[str, str, int, str]:
    """Selects best GitHub Release asset and SHA256SUMS URL for the host OS/arch."""
    if not isinstance(assets, list):
        return ("", "", 0, "")

    plat = (platform_name or sys.platform).lower()
    arch = (machine or platform.machine() or "").lower()
    is_arm64 = arch in ("arm64", "aarch64", "armv8", "armv8l")
    is_x64 = arch in ("x86_64", "amd64", "x64")

    best_asset: Optional[Dict] = None
    best_score = -1
    checksum_platform = ""
    checksum_generic = ""

    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        low = name.lower()

        if "sha256" in low and low.endswith(".txt"):
            is_mac_cs = "macos" in low or "darwin" in low
            is_win_cs = "windows" in low or "win32" in low or "win64" in low or "-win" in low
            is_lin_cs = "linux" in low
            if plat == "darwin" and is_mac_cs:
                checksum_platform = url
            elif plat == "win32" and is_win_cs:
                checksum_platform = url
            elif plat.startswith("linux") and is_lin_cs:
                checksum_platform = url
            elif not (is_mac_cs or is_win_cs or is_lin_cs):
                checksum_generic = url
            continue

        has_arm64_tag = any(tok in low for tok in ("arm64", "aarch64", "apple-silicon"))
        has_x64_tag = any(tok in low for tok in ("x86_64", "amd64", "x64", "intel"))
        has_universal_tag = "universal" in low

        score = -1
        if plat == "darwin":
            if low.endswith(".dmg"):
                if has_universal_tag:
                    score = 20
                elif has_arm64_tag and not has_x64_tag:
                    score = 30 if is_arm64 else -1
                elif has_x64_tag and not has_arm64_tag:
                    score = 30 if is_x64 else -1
                else:
                    score = 10
        elif plat == "win32":
            if (has_arm64_tag and not has_x64_tag and not is_arm64) or (
                has_x64_tag and not has_arm64_tag and not is_x64
            ):
                score = -1
            elif low.endswith(".exe"):
                score = 30 if "setup" in low else 15
            elif low.endswith(".zip") and "win" in low:
                score = 10
        elif plat.startswith("linux"):
            if (has_arm64_tag and not has_x64_tag and not is_arm64) or (
                has_x64_tag and not has_arm64_tag and not is_x64
            ):
                score = -1
            elif low.endswith(".appimage"):
                score = 30
            elif low.endswith(".tar.gz") and "linux" in low:
                score = 25

        if score > best_score:
            best_score = score
            best_asset = item

    if not best_asset:
        return ("", "", 0, "")

    checksum_url = checksum_platform or checksum_generic
    return (
        str(best_asset.get("name") or ""),
        str(best_asset.get("browser_download_url") or ""),
        int(best_asset.get("size") or 0),
        checksum_url,
    )


def parse_sha256sums(sums_text: str, target_filename: str) -> Optional[str]:
    target_base = os.path.basename(target_filename).strip().lower()
    for line in (sums_text or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            digest = parts[0].strip().lower()
            fname = os.path.basename(parts[-1].lstrip("*")).strip().lower()
            if fname == target_base and re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return None


def compute_file_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_file_sha256(file_path: str, expected_hex: str) -> bool:
    if not expected_hex or not os.path.isfile(file_path):
        return False
    return compute_file_sha256(file_path) == expected_hex.strip().lower()


def check_for_updates(
    current_version: str = __version__,
    api_url: str = GITHUB_LATEST_RELEASE_URL,
    timeout_sec: float = 5.0,
) -> UpdateInfo:
    default_release_url = f"https://github.com/{__repo__}/releases/latest"
    try:
        validated_api = validate_update_url(api_url)
        req = urllib.request.Request(
            validated_api,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"LocalRecall/{current_version}",
            },
        )
        ctx = _make_ssl_context()
        with _open_verified_url(req, timeout=timeout_sec, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        tag_name = str(payload.get("tag_name") or "").strip()
        latest_ver = tag_name.lstrip("vV") or current_version
        raw_html_url = str(payload.get("html_url") or default_release_url)
        try:
            html_url = validate_update_url(raw_html_url)
        except ValueError:
            html_url = default_release_url
        notes = str(payload.get("body") or "").strip()[:800]
        asset_name, asset_url, asset_size, checksum_url = select_platform_asset(
            payload.get("assets") or []
        )
        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_ver,
            is_update_available=is_newer_version(latest_ver, current_version),
            release_url=html_url,
            release_notes=notes,
            asset_name=asset_name,
            asset_url=asset_url,
            asset_size=asset_size,
            checksum_url=checksum_url,
        )
    except Exception as exc:
        return UpdateInfo(
            current_version=current_version,
            latest_version=current_version,
            is_update_available=False,
            release_url=default_release_url,
            error=str(exc),
        )


def download_update_asset(
    info: UpdateInfo,
    dest_dir: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    status_cb: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    timeout_sec: float = 20.0,
) -> str:
    if not info.has_direct_installer:
        raise RuntimeError("No direct installer package available for this platform.")

    # Fail-closed: enforce HTTPS + GitHub host allowlist and mandatory SHA-256 manifest
    validated_asset_url = validate_update_url(info.asset_url)
    if not info.checksum_url:
        raise RuntimeError("Missing SHA-256 checksum manifest URL; refusing unverified update.")
    validated_checksum_url = validate_update_url(info.checksum_url)

    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(info.asset_name)
    final_path = os.path.join(dest_dir, safe_name)
    part_path = final_path + ".part"

    ctx = _make_ssl_context()

    # Fetch and verify checksum manifest exists for this asset BEFORE accepting download
    if status_cb:
        status_cb("Fetching SHA-256 checksum manifest…")
    try:
        cs_req = urllib.request.Request(
            validated_checksum_url,
            headers={"User-Agent": f"LocalRecall/{info.current_version}"},
        )
        with _open_verified_url(cs_req, timeout=min(10.0, timeout_sec), context=ctx) as cs_resp:
            sums_text = cs_resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch SHA-256 checksum manifest: {exc}") from exc

    expected = parse_sha256sums(sums_text, safe_name)
    if not expected:
        raise RuntimeError(f"SHA-256 checksum manifest has no matching entry for {safe_name}.")

    req = urllib.request.Request(
        validated_asset_url,
        headers={"User-Agent": f"LocalRecall/{info.current_version}"},
    )
    downloaded = 0
    total = int(info.asset_size or 0)

    try:
        with _open_verified_url(req, timeout=timeout_sec, context=ctx) as resp:
            if total <= 0:
                hdr_len = resp.headers.get("Content-Length")
                if hdr_len and hdr_len.isdigit():
                    total = int(hdr_len)
            with open(part_path, "wb") as out:
                while True:
                    if cancel_check and cancel_check():
                        raise RuntimeError("Update download cancelled.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)

        if status_cb:
            status_cb("Verifying SHA-256 checksum…")
        if not verify_file_sha256(part_path, expected):
            raise RuntimeError("SHA-256 verification failed for downloaded update.")

        os.replace(part_path, final_path)
        return final_path
    except Exception:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
        raise


def _find_running_macos_app_bundle() -> Optional[str]:
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    exe = os.path.abspath(sys.executable)
    marker = ".app/Contents/"
    idx = exe.find(marker)
    if idx == -1:
        return None
    return exe[: idx + 4]


def apply_downloaded_update(installer_path: str) -> Tuple[bool, str]:
    if not os.path.isfile(installer_path):
        return (False, f"Update file not found: {installer_path}")

    if sys.platform == "win32":
        low = installer_path.lower()
        if low.endswith(".exe"):
            cmd = [installer_path]
            if "setup" in os.path.basename(low):
                cmd.extend(["/SP-", "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            subprocess.Popen(cmd, creationflags=creationflags, close_fds=True)
            return (True, "Windows installer started. LocalRecall will restart after updating.")
        os.startfile(installer_path)  # type: ignore[attr-defined]
        return (False, "Update package opened.")

    if sys.platform == "darwin":
        app_bundle = _find_running_macos_app_bundle()
        if (
            app_bundle
            and installer_path.lower().endswith(".dmg")
            and os.access(os.path.dirname(app_bundle), os.W_OK)
        ):
            pid = os.getpid()
            script_fd, script_path = tempfile.mkstemp(prefix="localrecall_updater_", suffix=".sh")
            mount_dir = tempfile.mkdtemp(prefix="localrecall_mnt_")
            q_dmg = shlex.quote(installer_path)
            q_app = shlex.quote(app_bundle)
            q_app_new = shlex.quote(app_bundle + ".new")
            q_app_old = shlex.quote(app_bundle + ".old")
            q_mnt = shlex.quote(mount_dir)
            q_script = shlex.quote(script_path)

            script_body = f"""#!/bin/bash
set -e
OLD_PID={pid}
SWAPPED=0
cleanup() {{
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -ne 0 ] && [ "$SWAPPED" -eq 1 ] && [ -d {q_app_old} ] && [ ! -d {q_app} ]; then
        mv {q_app_old} {q_app} 2>/dev/null || true
    fi
    rm -rf {q_app_new} 2>/dev/null || true
    hdiutil detach {q_mnt} -quiet 2>/dev/null || true
    rmdir {q_mnt} 2>/dev/null || true
    rm -f {q_script} 2>/dev/null || true
}}
trap cleanup EXIT
WAIT_COUNT=0
while kill -0 "$OLD_PID" 2>/dev/null; do
    WAIT_COUNT=$((WAIT_COUNT + 1))
    if [ "$WAIT_COUNT" -ge 100 ]; then
        exit 1
    fi
    sleep 0.3
done
hdiutil attach {q_dmg} -nobrowse -quiet -mountpoint {q_mnt}
SRC_APP="$(find {q_mnt} -maxdepth 1 -name '*.app' -print -quit)"
if [ -z "$SRC_APP" ]; then
    open {q_dmg}
    exit 1
fi
rm -rf {q_app_new} {q_app_old}
ditto "$SRC_APP" {q_app_new}
xattr -dr com.apple.quarantine {q_app_new} 2>/dev/null || true
if [ -d {q_app} ]; then
    mv {q_app} {q_app_old}
    SWAPPED=1
fi
mv {q_app_new} {q_app}
SWAPPED=0
rm -rf {q_app_old}
rm -f {q_dmg} 2>/dev/null || true
open -n {q_app}
"""
            with os.fdopen(script_fd, "w", encoding="utf-8") as f:
                f.write(script_body)
            os.chmod(script_path, 0o700)
            subprocess.Popen(
                ["/bin/bash", script_path],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return (True, "Applying macOS update. LocalRecall will relaunch shortly.")

        subprocess.Popen(["open", installer_path], start_new_session=True)
        return (False, "DMG opened in Finder. Drag LocalRecall.app into Applications.")

    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, installer_path], start_new_session=True)
    return (False, f"Update downloaded to: {installer_path}")


try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class UpdateCheckerThread(QThread):
        update_checked = pyqtSignal(object)

        def __init__(self, current_version: str = __version__, parent=None):
            super().__init__(parent)
            self.current_version = current_version

        def run(self) -> None:
            info = check_for_updates(current_version=self.current_version)
            self.update_checked.emit(info)

    class UpdateDownloadThread(QThread):
        progress_changed = pyqtSignal(int, int)
        status_changed = pyqtSignal(str)
        download_finished = pyqtSignal(str, str)

        def __init__(self, info: UpdateInfo, dest_dir: str, parent=None):
            super().__init__(parent)
            self.info = info
            self.dest_dir = dest_dir
            self._cancelled = False

        def cancel(self) -> None:
            self._cancelled = True

        def run(self) -> None:
            try:
                path = download_update_asset(
                    info=self.info,
                    dest_dir=self.dest_dir,
                    progress_cb=lambda dl, tot: self.progress_changed.emit(int(dl), int(tot)),
                    status_cb=lambda msg: self.status_changed.emit(str(msg)),
                    cancel_check=lambda: self._cancelled,
                )
                self.download_finished.emit(path, "")
            except Exception as exc:
                self.download_finished.emit("", str(exc))

except Exception:
    UpdateCheckerThread = None  # type: ignore[assignment,misc]
    UpdateDownloadThread = None  # type: ignore[assignment,misc]
