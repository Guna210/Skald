"""Host hardware and NVIDIA GPU probing for `system.hardware` and fit rating."""

from __future__ import annotations

import csv
import importlib
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import psutil  # type: ignore[import-untyped]

from skald_core.schemas import GpuInfo, HardwareInfo
from skald_core.storage import get_storage_dir

logger = logging.getLogger(__name__)

_NVIDIA_SMI_TIMEOUT_S = 10.0
GPU_RETRY_SECONDS = 60
_CREATE_NO_WINDOW = 0x08000000
_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")
_NA_VALUES = frozenset({"", "n/a", "[n/a]", "[not supported]", "not supported"})

_gpu_cache_lock = threading.Lock()
_cached_gpus: list[GpuInfo] | None = None
_transient_retry_at: float | None = None


def clear_gpu_cache() -> None:
    """Reset the GPU probe caches (for tests)."""
    global _cached_gpus, _transient_retry_at
    with _gpu_cache_lock:
        _cached_gpus = None
        _transient_retry_at = None


def parse_numeric_version(version: str) -> tuple[int, ...]:
    """Parse a dotted numeric version string (e.g. driver or compute_cap) into ints."""
    cleaned = version.strip()
    if _VERSION_RE.fullmatch(cleaned) is None:
        raise ValueError(f"Invalid numeric version: {version!r}")
    return tuple(int(part) for part in cleaned.split("."))


def _probe_cpu_model() -> str:
    sys_name = platform.system().lower()
    if sys_name == "linux":
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
            for line in cpuinfo.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    if key.strip() == "model name" and val.strip():
                        return val.strip()
        except OSError as exc:
            logger.debug("Failed to read /proc/cpuinfo: %s", exc)
    elif sys_name == "windows":
        try:
            winreg = importlib.import_module("winreg")
        except ImportError:
            winreg = None
        if winreg is not None:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            except OSError as exc:
                logger.debug("Failed to read CPU model from registry: %s", exc)

    proc = platform.processor().strip()
    if proc:
        return proc
    machine = platform.machine().strip()
    return machine or "unknown"


def _disk_free_bytes(target_dir: Path) -> int:
    resolved = target_dir.resolve()
    probe_path = resolved
    while not probe_path.exists():
        parent = probe_path.parent
        if parent == probe_path:
            break
        probe_path = parent
    try:
        return int(psutil.disk_usage(str(probe_path)).free)
    except OSError as exc:
        logger.warning("Failed to measure free disk space at %s: %s", probe_path, exc)
        return 0


def _find_nvidia_smi() -> str | None:
    which_path = shutil.which("nvidia-smi")
    if which_path:
        return which_path

    if platform.system().lower() == "windows":
        system_root = os.environ.get("SystemRoot", "").strip() or r"C:\Windows"
        program_files = os.environ.get("ProgramFiles", "").strip() or r"C:\Program Files"
        candidates = (
            Path(system_root) / "System32" / "nvidia-smi.exe",
            Path(program_files) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

    return None


def _run_nvidia_smi(binary: str, query_fields: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        binary,
        f"--query-gpu={query_fields}",
        "--format=csv,noheader,nounits",
    ]
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW)
        if platform.system().lower() == "windows"
        else 0
    )
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_NVIDIA_SMI_TIMEOUT_S,
        creationflags=creationflags,
        check=False,
    )


def _parse_nvidia_smi_csv(stdout: str, *, expect_compute_cap: bool) -> list[GpuInfo] | None:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return []

    expected_cols = 4 if expect_compute_cap else 3
    gpus: list[GpuInfo] = []
    try:
        rows = list(csv.reader(lines, skipinitialspace=True))
    except csv.Error as exc:
        logger.warning("Failed to parse nvidia-smi CSV output: %s", exc)
        return None

    for row in rows:
        if len(row) != expected_cols:
            logger.warning(
                "Unexpected nvidia-smi CSV column count (%d, expected %d): %r",
                len(row),
                expected_cols,
                row,
            )
            return None

        name = row[0].strip()
        mem_raw = row[1].strip()
        driver_version = row[2].strip()

        if not name or name.lower() in _NA_VALUES:
            logger.warning("Invalid GPU name in nvidia-smi output: %r", row)
            return None

        try:
            memory_total_mb = int(mem_raw)
            if memory_total_mb <= 0:
                raise ValueError("memory_total_mb must be positive")
            parse_numeric_version(driver_version)
        except ValueError as exc:
            logger.warning("Invalid nvidia-smi GPU record %r: %s", row, exc)
            return None

        compute_cap: str | None = None
        bfloat16_capable = False
        if expect_compute_cap:
            cap_raw = row[3].strip()
            if cap_raw.lower() not in _NA_VALUES:
                try:
                    cap_tuple = parse_numeric_version(cap_raw)
                except ValueError as exc:
                    logger.warning("Invalid compute_cap in nvidia-smi output %r: %s", row, exc)
                    return None
                compute_cap = cap_raw
                major = cap_tuple[0]
                minor = cap_tuple[1] if len(cap_tuple) > 1 else 0
                bfloat16_capable = (major, minor) >= (8, 0)

        gpus.append(
            GpuInfo(
                name=name,
                memory_total_mb=memory_total_mb,
                driver_version=driver_version,
                compute_cap=compute_cap,
                bfloat16_capable=bfloat16_capable,
            )
        )

    return gpus


def _probe_gpus_uncached() -> tuple[list[GpuInfo], bool]:
    binary = _find_nvidia_smi()
    if binary is None:
        logger.warning("nvidia-smi not found; reporting no NVIDIA GPUs")
        return [], True

    expect_compute_cap = True
    try:
        proc = _run_nvidia_smi(binary, "name,memory.total,driver_version,compute_cap")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Failed to run nvidia-smi at %s: %s", binary, exc)
        return [], False

    if proc.returncode != 0:
        combined = f"{proc.stderr}\n{proc.stdout}".lower()
        if "compute_cap" in combined and "not a valid field" in combined:
            logger.info("nvidia-smi rejected compute_cap; retrying without compute_cap")
            expect_compute_cap = False
            try:
                proc = _run_nvidia_smi(binary, "name,memory.total,driver_version")
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Failed to run nvidia-smi retry at %s: %s", binary, exc)
                return [], False

    if proc.returncode != 0:
        logger.warning(
            "nvidia-smi exited with %d (%s)",
            proc.returncode,
            proc.stderr.strip() or proc.stdout.strip() or "no output",
        )
        return [], False

    parsed = _parse_nvidia_smi_csv(proc.stdout, expect_compute_cap=expect_compute_cap)
    if parsed is None:
        return [], False
    return parsed, True


def _probe_gpus() -> list[GpuInfo]:
    global _cached_gpus, _transient_retry_at
    with _gpu_cache_lock:
        if _cached_gpus is not None:
            return list(_cached_gpus)
        now = time.monotonic()
        if _transient_retry_at is not None and now < _transient_retry_at:
            return []
        gpus, should_cache = _probe_gpus_uncached()
        if should_cache:
            _cached_gpus = gpus
            _transient_retry_at = None
        else:
            _transient_retry_at = now + GPU_RETRY_SECONDS
        return list(gpus)


def probe_hardware() -> HardwareInfo:
    """Return host OS, CPU, RAM, storage disk space, and cached NVIDIA GPU info."""
    logical_cores = psutil.cpu_count(logical=True) or 1
    physical_cores = psutil.cpu_count(logical=False) or logical_cores
    vm = psutil.virtual_memory()

    return HardwareInfo(
        os=platform.system(),
        cpu_model=_probe_cpu_model(),
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_total_bytes=int(vm.total),
        ram_free_bytes=int(vm.available),
        disk_free_bytes=_disk_free_bytes(get_storage_dir()),
        gpus=_probe_gpus(),
    )
