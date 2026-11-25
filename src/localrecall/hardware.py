"""Cross-platform hardware, CPU/ISA detection, OS paths, and ONNX CPU budget tuning."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Set, Tuple

PROFILE_AUTO = "auto"
PROFILE_ECO = "eco"
PROFILE_BALANCED = "balanced"
PROFILE_PERFORMANCE = "performance"

VALID_PROFILES = (PROFILE_AUTO, PROFILE_ECO, PROFILE_BALANCED, PROFILE_PERFORMANCE)


@dataclass(frozen=True)
class HardwareProfile:
    """Detected host hardware and OS capabilities."""

    os_name: str
    os_version: str
    windows_build: int
    arch: str
    cpu_name: str
    logical_cores: int
    physical_cores: int
    isa_features: Tuple[str, ...] = field(default_factory=tuple)
    recommended_tier: str = PROFILE_BALANCED
    is_wayland: bool = False

    @property
    def has_modern_simd(self) -> bool:
        feats = set(self.isa_features)
        return bool(
            feats.intersection(
                {"avx2", "avx512f", "avx_vnni", "avx512_vnni", "neon", "dotprod"}
            )
        )

    @property
    def short_cpu_label(self) -> str:
        name = " ".join(self.cpu_name.split())
        if len(name) > 40:
            name = name[:37] + "..."
        return name or f"{self.arch.upper()} CPU"


@dataclass(frozen=True)
class RuntimeTuning:
    """Runtime CPU thread budget keeping LocalRecall under <1% idle CPU and 0 MB VRAM."""

    requested_profile: str
    effective_profile: str
    ocr_intra_threads: int
    ocr_inter_threads: int
    suggested_interval_sec: float


def normalize_arch(raw_machine: Optional[str] = None) -> str:
    m = (raw_machine or platform.machine() or "").strip().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64", "armv8", "armv8l"):
        return "arm64"
    if m in ("i386", "i686", "x86"):
        return "x86"
    return m or "unknown"


def get_windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def is_wayland_session() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    session_type = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    return session_type == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def detect_cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if val and str(val).strip():
                    return " ".join(str(val).strip().split())
        except Exception:
            pass

    if sys.platform.startswith("linux"):
        try:
            fallback_arm: Optional[str] = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    k = key.strip().lower()
                    v = " ".join(val.strip().split())
                    if not v:
                        continue
                    if k == "model name":
                        return v
                    if k in ("hardware", "model") and not v.isdigit() and fallback_arm is None:
                        fallback_arm = v
            if fallback_arm:
                return fallback_arm
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return " ".join(res.stdout.strip().split())
        except Exception:
            pass

    fallback = (platform.processor() or "").strip()
    if fallback:
        return " ".join(fallback.split())
    return f"{normalize_arch().upper()} Processor"


def detect_physical_cores(logical_cores: int) -> int:
    logical = max(1, int(logical_cores))

    if sys.platform.startswith("linux"):
        try:
            pairs: Set[Tuple[str, str]] = set()
            phys_id = "0"
            core_id: Optional[str] = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        if core_id is not None:
                            pairs.add((phys_id, core_id))
                        phys_id = "0"
                        core_id = None
                        continue
                    if ":" in stripped:
                        k, v = [p.strip() for p in stripped.split(":", 1)]
                        if k == "physical id":
                            phys_id = v
                        elif k == "core id":
                            core_id = v
                if core_id is not None:
                    pairs.add((phys_id, core_id))
            if pairs:
                return max(1, min(logical, len(pairs)))
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return max(1, min(logical, int(res.stdout.strip())))
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            kernel32.GetLogicalProcessorInformationEx.argtypes = [
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.GetLogicalProcessorInformationEx.restype = wintypes.BOOL
            relation_processor_core = 0
            buf_len = wintypes.DWORD(0)
            kernel32.GetLogicalProcessorInformationEx(
                relation_processor_core, None, ctypes.byref(buf_len)
            )
            if buf_len.value > 0:
                buf = ctypes.create_string_buffer(buf_len.value)
                ok = kernel32.GetLogicalProcessorInformationEx(
                    relation_processor_core, buf, ctypes.byref(buf_len)
                )
                if ok:
                    raw = buf.raw
                    offset = 0
                    cores = 0
                    while offset + 8 <= buf_len.value:
                        rel = int.from_bytes(raw[offset : offset + 4], "little")
                        size = int.from_bytes(raw[offset + 4 : offset + 8], "little")
                        if size <= 0:
                            break
                        if rel == relation_processor_core:
                            cores += 1
                        offset += size
                    if cores > 0:
                        return max(1, min(logical, cores))
        except Exception:
            pass

    if logical <= 2:
        return logical
    return max(2, logical // 2)


def detect_isa_features(arch: Optional[str] = None) -> Tuple[str, ...]:
    norm_arch = normalize_arch(arch)
    found: Set[str] = set()

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            is_feat = ctypes.windll.kernel32.IsProcessorFeaturePresent
            is_feat.argtypes = [wintypes.DWORD]
            is_feat.restype = wintypes.BOOL
            win_flags = (
                (10, "sse2"),
                (37, "sse4_1"),
                (38, "sse4_2"),
                (39, "avx"),
                (40, "avx2"),
                (41, "avx512f"),
                (19, "neon"),
                (43, "dotprod"),
            )
            for code, name in win_flags:
                try:
                    if bool(is_feat(code)):
                        found.add(name)
                except Exception:
                    pass
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    lower = line.lower()
                    if lower.startswith(("flags", "features")) and ":" in lower:
                        tokens = set(lower.split(":", 1)[1].split())
                        flag_map = {
                            "sse2": "sse2",
                            "sse4_1": "sse4_1",
                            "sse4_2": "sse4_2",
                            "avx": "avx",
                            "avx2": "avx2",
                            "avx512f": "avx512f",
                            "avx512_vnni": "avx512_vnni",
                            "avx_vnni": "avx_vnni",
                            "asimd": "neon",
                            "neon": "neon",
                            "asimddp": "dotprod",
                        }
                        for src_flag, norm_name in flag_map.items():
                            if src_flag in tokens:
                                found.add(norm_name)
                        break
        except Exception:
            pass
    elif sys.platform == "darwin":
        if norm_arch == "arm64":
            found.update({"neon", "dotprod"})
        else:
            for sysctl_key, feat_name in (
                ("hw.optional.sse4_2", "sse4_2"),
                ("hw.optional.avx1_0", "avx"),
                ("hw.optional.avx2_0", "avx2"),
                ("hw.optional.avx512f", "avx512f"),
            ):
                try:
                    res = subprocess.run(
                        ["sysctl", "-n", sysctl_key],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        check=False,
                    )
                    if res.returncode == 0 and res.stdout.strip() == "1":
                        found.add(feat_name)
                except Exception:
                    pass

    return tuple(sorted(found))


def classify_hardware_tier(
    logical_cores: int,
    physical_cores: int,
    isa_features: Sequence[str],
    arch: str,
) -> str:
    feats = set(isa_features)
    has_modern = bool(
        feats.intersection({"avx2", "avx512f", "avx_vnni", "avx512_vnni", "neon", "dotprod"})
    )

    if physical_cores >= 6 and logical_cores >= 8 and (has_modern or not feats):
        return PROFILE_PERFORMANCE
    if physical_cores <= 2 or logical_cores <= 2:
        return PROFILE_ECO
    if arch == "x86_64" and feats and not has_modern and physical_cores <= 4:
        return PROFILE_ECO
    return PROFILE_BALANCED


def detect_hardware_profile() -> HardwareProfile:
    os_name = platform.system() or sys.platform
    os_version = platform.release() or ""
    win_build = get_windows_build()
    arch = normalize_arch()
    cpu_name = detect_cpu_name()
    logical = max(1, os.cpu_count() or 2)
    physical = detect_physical_cores(logical)
    isa = detect_isa_features(arch)
    tier = classify_hardware_tier(logical, physical, isa, arch)

    return HardwareProfile(
        os_name=os_name,
        os_version=os_version,
        windows_build=win_build,
        arch=arch,
        cpu_name=cpu_name,
        logical_cores=logical,
        physical_cores=physical,
        isa_features=isa,
        recommended_tier=tier,
        is_wayland=is_wayland_session(),
    )


def compute_runtime_tuning(
    hw: HardwareProfile,
    requested_profile: str = PROFILE_AUTO,
) -> RuntimeTuning:
    req = requested_profile if requested_profile in VALID_PROFILES else PROFILE_AUTO
    eff = hw.recommended_tier if req == PROFILE_AUTO else req

    safe_max = max(1, hw.logical_cores - 1) if hw.logical_cores >= 2 else 1

    if eff == PROFILE_ECO:
        ocr_intra = 1
        interval = 5.0
    elif eff == PROFILE_PERFORMANCE:
        ocr_intra = max(1, min(4, max(2, hw.physical_cores // 2), safe_max))
        interval = 2.0
    else:
        ocr_intra = max(1, min(2, max(1, hw.physical_cores // 2), safe_max))
        interval = 3.0

    return RuntimeTuning(
        requested_profile=req,
        effective_profile=eff,
        ocr_intra_threads=ocr_intra,
        ocr_inter_threads=1,
        suggested_interval_sec=interval,
    )


def apply_thread_env_defaults(tuning: RuntimeTuning) -> None:
    """Caps BLAS/OpenMP threads to prevent background CPU spikes during OCR."""
    t = str(max(1, tuning.ocr_intra_threads))
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(var, t)


def get_app_base_dir() -> str:
    """Returns project root in source mode or executable directory when frozen."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return str(Path(__file__).resolve().parents[2])


def get_writable_data_dir(preferred_dir: Optional[str] = None) -> Path:
    """Returns OS-standard writable data directory for LocalRecall."""
    if preferred_dir:
        p = Path(preferred_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        target = Path(root) / "LocalRecall" if root else Path.home() / ".localrecall"
    elif sys.platform == "darwin":
        target = Path.home() / "Library" / "Application Support" / "LocalRecall"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        target = Path(xdg) / "localrecall" if xdg else Path.home() / ".local" / "share" / "localrecall"

    target.mkdir(parents=True, exist_ok=True)
    return target


def get_ui_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "DejaVu Sans"


def format_hardware_summary(hw: HardwareProfile, tuning: RuntimeTuning, lang: str = "en") -> str:
    if lang == "tr":
        tiers = {
            PROFILE_ECO: "Eko (<1% CPU)",
            PROFILE_BALANCED: "Dengeli",
            PROFILE_PERFORMANCE: "Performans",
        }
        prof_lbl = f"Profil: {tiers.get(tuning.effective_profile, tuning.effective_profile)}"
    else:
        tiers = {
            PROFILE_ECO: "Eco (<1% CPU)",
            PROFILE_BALANCED: "Balanced",
            PROFILE_PERFORMANCE: "Performance",
        }
        prof_lbl = f"Profile: {tiers.get(tuning.effective_profile, tuning.effective_profile)}"

    simd_str = ", ".join(f.upper() for f in hw.isa_features) if hw.isa_features else "Standard"
    return (
        f"{hw.short_cpu_label} ({hw.physical_cores}C/{hw.logical_cores}T, {hw.arch}) · "
        f"{prof_lbl} · ONNX: {tuning.ocr_intra_threads}T · 0 MB VRAM · ISA: {simd_str}"
    )
