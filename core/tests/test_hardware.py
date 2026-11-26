"""Tests for hardware probing (`system.hardware`) and model fit rating."""

from __future__ import annotations

import io
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import psutil
import pytest

from skald_core.catalog.schema import CatalogHardware, CpuHardware, CudaHardware
from skald_core.hardware import (
    CHARS_PER_SECOND_ESTIMATE,
    clear_gpu_cache,
    probe_hardware,
    rate_model_fit,
)
from skald_core.packs.manager import CUDA_DRIVER_REQUIREMENTS
from skald_core.rpc import INVALID_PARAMS, RpcServer
from skald_core.rpc.methods import register_all
from skald_core.schemas import FitRating, GpuInfo, HardwareInfo

_BYTES_PER_GB = 1024**3


@pytest.fixture(autouse=True)
def _isolated_hardware_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure hardware tests never touch real home/storage dirs and reset GPU cache."""
    storage_dir = tmp_path / "storage"
    data_dir = tmp_path / "userdata"
    storage_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SKALD_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("SKALD_DATA_DIR", str(data_dir))
    clear_gpu_cache()


def _fake_hw(
    *,
    os_name: str = "Linux",
    ram_gb: float = 16.0,
    gpus: list[GpuInfo] | None = None,
) -> HardwareInfo:
    total = int(ram_gb * _BYTES_PER_GB)
    return HardwareInfo(
        os=os_name,
        cpu_model="Test CPU",
        physical_cores=4,
        logical_cores=8,
        ram_total_bytes=total,
        ram_free_bytes=total // 2,
        disk_free_bytes=100 * _BYTES_PER_GB,
        gpus=[] if gpus is None else gpus,
    )


def _gpu(
    *,
    name: str = "NVIDIA GeForce RTX 3060",
    vram_mb: int = 12288,
    driver: str = "560.76",
    compute_cap: str | None = "8.6",
    bf16: bool = True,
) -> GpuInfo:
    return GpuInfo(
        name=name,
        memory_total_mb=vram_mb,
        driver_version=driver,
        compute_cap=compute_cap,
        bfloat16_capable=bf16,
    )


# ---------------------------------------------------------------------------
# Hardware probe tests (captured nvidia-smi outputs, CPU, disk, caching)
# ---------------------------------------------------------------------------


def test_probe_nvidia_smi_two_gpus_and_comma_in_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    captured_calls: list[tuple[list[str], dict[str, Any]]] = []
    stdout = (
        '"NVIDIA Tesla, Custom Edition", 15360, 560.28.03, 7.5\n'
        "NVIDIA GeForce RTX 4090, 24564, 560.28.03, 8.9\n"
    )

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        captured_calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    hw = probe_hardware()
    assert len(captured_calls) == 1
    cmd, kwargs = captured_calls[0]
    assert cmd == [
        "/usr/bin/nvidia-smi",
        "--query-gpu=name,memory.total,driver_version,compute_cap",
        "--format=csv,noheader,nounits",
    ]
    assert kwargs["capture_output"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["timeout"] == 10.0

    assert len(hw.gpus) == 2
    assert hw.gpus[0] == GpuInfo(
        name="NVIDIA Tesla, Custom Edition",
        memory_total_mb=15360,
        driver_version="560.28.03",
        compute_cap="7.5",
        bfloat16_capable=False,
    )
    assert hw.gpus[1] == GpuInfo(
        name="NVIDIA GeForce RTX 4090",
        memory_total_mb=24564,
        driver_version="560.28.03",
        compute_cap="8.9",
        bfloat16_capable=True,
    )


def test_probe_nvidia_smi_old_driver_retries_without_compute_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(cmd)
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=2,
                stdout="",
                stderr='Field "compute_cap" is not a valid field to query.\n',
            )
        return SimpleNamespace(
            returncode=0,
            stdout="GeForce GTX 1080, 8192, 470.82\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    hw = probe_hardware()
    assert len(calls) == 2
    assert "--query-gpu=name,memory.total,driver_version,compute_cap" in calls[0]
    assert "--query-gpu=name,memory.total,driver_version" in calls[1]
    assert hw.gpus == [
        GpuInfo(
            name="GeForce GTX 1080",
            memory_total_mb=8192,
            driver_version="470.82",
            compute_cap=None,
            bfloat16_capable=False,
        )
    ]


@pytest.mark.parametrize(
    "case",
    [
        "missing_binary",
        "empty_output",
        "nonzero_exit",
        "timeout",
        "garbage_not_csv",
        "garbage_bad_vram",
        "garbage_bad_driver",
        "garbage_bad_compute_cap",
        "retry_still_fails",
    ],
)
def test_probe_nvidia_smi_failures_return_empty_and_warn(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    if case == "missing_binary":
        monkeypatch.setattr(shutil, "which", lambda name: None)
    else:
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")

        def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
            if case == "empty_output":
                return SimpleNamespace(returncode=0, stdout="  \n", stderr="")
            if case == "nonzero_exit":
                return SimpleNamespace(returncode=9, stdout="", stderr="No devices were found")
            if case == "timeout":
                raise subprocess.TimeoutExpired(cmd, timeout=10.0)
            if case == "garbage_not_csv":
                return SimpleNamespace(returncode=0, stdout="NVIDIA-SMI has failed\n", stderr="")
            if case == "garbage_bad_vram":
                return SimpleNamespace(
                    returncode=0, stdout="RTX 3060, 12288 MiB, 560.76, 8.6\n", stderr=""
                )
            if case == "garbage_bad_driver":
                return SimpleNamespace(
                    returncode=0, stdout="RTX 3060, 12288, unknown_drv, 8.6\n", stderr=""
                )
            if case == "garbage_bad_compute_cap":
                return SimpleNamespace(
                    returncode=0, stdout="RTX 3060, 12288, 560.76, ada\n", stderr=""
                )
            if case == "retry_still_fails":
                if "compute_cap" in " ".join(cmd):
                    return SimpleNamespace(
                        returncode=2,
                        stdout="",
                        stderr='Field "compute_cap" is not a valid field to query.',
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="Driver/library mismatch")
            raise AssertionError(f"Unhandled case {case}")

        monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING, logger="skald_core.hardware.probe"):
        hw = probe_hardware()

    assert hw.gpus == []
    if case != "empty_output":
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)


@pytest.mark.parametrize(
    "stderr_msg",
    [
        "some other error",
        "compute_cap permission denied",
    ],
)
def test_probe_generic_failure_does_not_retry(
    stderr_msg: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stdout="", stderr=stderr_msg)

    monkeypatch.setattr(subprocess, "run", fake_run)

    hw = probe_hardware()
    assert hw.gpus == []
    assert len(calls) == 1


@pytest.mark.parametrize("failure_mode", ["timeout", "nonzero_exit", "garbage"])
def test_probe_transient_failures_are_cached_60s_and_recover_after(
    failure_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    from skald_core.hardware.probe import GPU_RETRY_SECONDS

    assert GPU_RETRY_SECONDS == 60
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])

    run_count = 0

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            if failure_mode == "timeout":
                raise subprocess.TimeoutExpired(cmd, timeout=10.0)
            if failure_mode == "nonzero_exit":
                return SimpleNamespace(returncode=1, stdout="", stderr="GPU waking up")
            return SimpleNamespace(returncode=0, stdout="garbage output\n", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="NVIDIA GeForce RTX 3080, 10240, 560.28.03, 8.6\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    # Initial transient failure returns [] and starts the 60 s cooldown.
    hw1 = probe_hardware()
    assert hw1.gpus == []
    assert run_count == 1

    # (a) Within 60 s, returns [] without running nvidia-smi again.
    clock[0] += GPU_RETRY_SECONDS - 1.0
    hw_within = probe_hardware()
    assert hw_within.gpus == []
    assert run_count == 1

    # (b)/(c) Once 60 s have passed, probes again and recovers GPUs.
    clock[0] += 1.0
    hw2 = probe_hardware()
    assert len(hw2.gpus) == 1
    assert hw2.gpus[0].name == "NVIDIA GeForce RTX 3080"
    assert run_count == 2

    # Definitive success stays cached for the process lifetime even after another 60 s.
    clock[0] += GPU_RETRY_SECONDS * 10
    hw3 = probe_hardware()
    assert hw3.gpus == hw2.gpus
    assert run_count == 2


def test_probe_caches_missing_nvidia_smi_and_successful_empty_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    which_calls = 0

    def missing_which(name: str) -> None:
        nonlocal which_calls
        which_calls += 1
        return None

    monkeypatch.setattr(shutil, "which", missing_which)
    assert probe_hardware().gpus == []
    assert probe_hardware().gpus == []
    assert which_calls == 1

    clear_gpu_cache()
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    run_count = 0

    def empty_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        nonlocal run_count
        run_count += 1
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", empty_run)
    assert probe_hardware().gpus == []
    assert probe_hardware().gpus == []
    assert run_count == 1


def test_probe_windows_nvidia_smi_fallbacks_and_create_no_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "processor", lambda: "Mock Windows CPU")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    sys_root = tmp_path / "WinRoot"
    prog_files = tmp_path / "ProgFiles"
    nvsmi_prog = prog_files / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"
    nvsmi_prog.parent.mkdir(parents=True)
    nvsmi_prog.write_text("placeholder", encoding="utf-8")

    monkeypatch.setenv("SystemRoot", str(sys_root))
    monkeypatch.setenv("ProgramFiles", str(prog_files))

    seen_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        seen_calls.append((cmd, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="NVIDIA GeForce RTX 4070, 12288, 560.76, 8.9\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    hw = probe_hardware()
    assert len(seen_calls) == 1
    assert seen_calls[0][0][0] == str(nvsmi_prog)
    assert seen_calls[0][1]["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    assert len(hw.gpus) == 1

    # System32 takes precedence over ProgramFiles when present.
    clear_gpu_cache()
    nvsmi_sys32 = sys_root / "System32" / "nvidia-smi.exe"
    nvsmi_sys32.parent.mkdir(parents=True)
    nvsmi_sys32.write_text("placeholder", encoding="utf-8")

    hw2 = probe_hardware()
    assert seen_calls[1][0][0] == str(nvsmi_sys32)
    assert len(hw2.gpus) == 1


def test_probe_caches_gpus_for_process_lifetime_but_rereads_ram_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    run_count = 0

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        nonlocal run_count
        run_count += 1
        return SimpleNamespace(
            returncode=0,
            stdout="NVIDIA GeForce RTX 3080, 10240, 560.28.03, 8.6\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ram_values = iter([4 * _BYTES_PER_GB, 3 * _BYTES_PER_GB])
    disk_values = iter([50 * _BYTES_PER_GB, 40 * _BYTES_PER_GB])
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=16 * _BYTES_PER_GB, available=next(ram_values)),
    )
    monkeypatch.setattr(
        psutil,
        "disk_usage",
        lambda _p: SimpleNamespace(free=next(disk_values)),
    )

    hw1 = probe_hardware()
    hw2 = probe_hardware()

    assert run_count == 1
    assert hw1.gpus == hw2.gpus
    assert hw1.ram_free_bytes == 4 * _BYTES_PER_GB
    assert hw2.ram_free_bytes == 3 * _BYTES_PER_GB
    assert hw1.disk_free_bytes == 50 * _BYTES_PER_GB
    assert hw2.disk_free_bytes == 40 * _BYTES_PER_GB


def test_probe_disk_free_uses_nearest_existing_ancestor_of_storage_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "existing_mount"
    existing.mkdir()
    nested = existing / "does" / "not" / "exist" / "yet"
    monkeypatch.setenv("SKALD_STORAGE_DIR", str(nested))
    monkeypatch.setattr(shutil, "which", lambda name: None)

    probed_paths: list[str] = []

    def fake_disk_usage(path_str: str) -> SimpleNamespace:
        probed_paths.append(path_str)
        return SimpleNamespace(free=123_456_789)

    monkeypatch.setattr(psutil, "disk_usage", fake_disk_usage)

    hw = probe_hardware()
    assert probed_paths == [str(existing.resolve())]
    assert hw.disk_free_bytes == 123_456_789


def test_probe_cpu_model_linux_winreg_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    # 1. Linux /proc/cpuinfo
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    orig_read_text = Path.read_text

    def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == Path("/proc/cpuinfo"):
            return "processor\t: 0\nvendor_id\t: AuthenticAMD\nmodel name\t: AMD Ryzen 7 5700U\n"
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    assert probe_hardware().cpu_model == "AMD Ryzen 7 5700U"

    # 2. Windows winreg path
    clear_gpu_cache()
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    fake_winreg = ModuleType("winreg")
    fake_winreg.HKEY_LOCAL_MACHINE = 0x80000002  # type: ignore[attr-defined]

    class _FakeKey:
        def __enter__(self) -> _FakeKey:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    fake_winreg.OpenKey = lambda _hkey, _subkey: _FakeKey()  # type: ignore[attr-defined]
    fake_winreg.QueryValueEx = lambda _key, _val: ("Intel Core i7-13700H", 1)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert probe_hardware().cpu_model == "Intel Core i7-13700H"

    # 3. Fallback to platform.processor() when winreg fails
    clear_gpu_cache()

    def failing_open(*_args: object) -> None:
        raise OSError("registry unavailable")

    fake_winreg.OpenKey = failing_open  # type: ignore[attr-defined]
    monkeypatch.setattr(platform, "processor", lambda: "Fallback-CPU-Model")
    assert probe_hardware().cpu_model == "Fallback-CPU-Model"


def test_system_hardware_rpc_and_subprocess(tmp_path: Path) -> None:
    server = RpcServer(stdin=io.BytesIO(), stdout=io.BytesIO())
    manager = register_all(server)
    try:
        resp = server.handle_line('{"jsonrpc":"2.0","id":1,"method":"system.hardware"}')
        assert resp is not None
        assert "result" in resp
        parsed = HardwareInfo.model_validate(resp["result"])
        assert parsed.os == platform.system()
        assert parsed.physical_cores >= 1
        assert parsed.logical_cores >= parsed.physical_cores
        assert parsed.ram_total_bytes > 0

        resp_bad = server.handle_line(
            '{"jsonrpc":"2.0","id":2,"method":"system.hardware","params":{"x":1}}'
        )
        assert resp_bad is not None
        assert resp_bad["error"]["code"] == INVALID_PARAMS
    finally:
        manager.shutdown()

    env = {
        **os.environ,
        "SKALD_LOG_DIR": str(tmp_path / "logs"),
        "SKALD_STORAGE_DIR": str(tmp_path / "storage"),
        "SKALD_DATA_DIR": str(tmp_path / "data"),
    }
    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.hardware"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "system.shutdown"}),
        ]
    )
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core"],
        input=f"{requests}\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0
    messages = [json.loads(line) for line in proc.stdout.splitlines() if line]
    assert len(messages) == 2
    assert messages[0]["id"] == 1
    assert HardwareInfo.model_validate(messages[0]["result"]).ram_total_bytes > 0
    assert messages[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


# ---------------------------------------------------------------------------
# Fit rating table: fake machines x fake models covering ratings, reasons,
# boundaries, warnings, multi-GPU, CPU-only, CUDA-only, and unknown RTF.
# ---------------------------------------------------------------------------


def test_fit_rating_table_and_boundaries() -> None:
    linux_floor = str(CUDA_DRIVER_REQUIREMENTS["cu126"]["linux"]["min_driver"])
    linux_toolkit = str(CUDA_DRIVER_REQUIREMENTS["cu126"]["linux"]["toolkit_driver"])
    win_floor = str(CUDA_DRIVER_REQUIREMENTS["cu126"]["windows"]["min_driver"])
    win_toolkit = str(CUDA_DRIVER_REQUIREMENTS["cu126"]["windows"]["toolkit_driver"])

    cuda_fast = CatalogHardware(
        cpu=None,
        cuda=CudaHardware(min_vram_gb=8.0, min_ram_gb=8.0, rtf_reference=0.5),
    )
    cuda_unknown_rtf = CatalogHardware(
        cpu=None,
        cuda=CudaHardware(min_vram_gb=8.0, rtf_reference=None),
    )
    cuda_slow = CatalogHardware(
        cpu=None,
        cuda=CudaHardware(min_vram_gb=8.0, rtf_reference=1.01),
    )
    cuda_borderline_rtf = CatalogHardware(
        cpu=None,
        cuda=CudaHardware(min_vram_gb=8.0, rtf_reference=1.0),
    )
    cpu_fast = CatalogHardware(
        cpu=CpuHardware(min_ram_gb=4.0, rtf_reference=0.5),
        cuda=None,
    )
    cpu_slow = CatalogHardware(
        cpu=CpuHardware(min_ram_gb=4.0, rtf_reference=1.2),
        cuda=None,
    )
    cpu_unknown_rtf = CatalogHardware(
        cpu=CpuHardware(min_ram_gb=4.0, rtf_reference=None),
        cuda=None,
    )
    hybrid = CatalogHardware(
        cpu=CpuHardware(min_ram_gb=8.0, rtf_reference=1.5),
        cuda=CudaHardware(min_vram_gb=8.0, rtf_reference=0.3),
    )

    cases: list[tuple[str, CatalogHardware, HardwareInfo, int | None, dict[str, Any]]] = [
        # --- CUDA ratings & boundaries ---
        (
            "cuda exact min VRAM (8192 MB) + rtf=0.5 -> good (not 1.5x)",
            cuda_fast,
            _fake_hw(
                ram_gb=8.0,
                gpus=[_gpu(vram_mb=8192, driver=linux_toolkit, compute_cap="8.6")],
            ),
            1500,
            {
                "rating": "good",
                "tier": "cuda",
                "gpu_index": 0,
                "warnings": [],
                "rtf": 0.5,
                "estimate_seconds": pytest.approx(50.0),
            },
        ),
        (
            "cuda exact 1.5x VRAM (12288 MB) + rtf=0.5 -> great",
            cuda_fast,
            _fake_hw(
                ram_gb=8.0,
                gpus=[_gpu(vram_mb=12288, driver=linux_toolkit, compute_cap="7.0")],
            ),
            1500,
            {
                "rating": "great",
                "tier": "cuda",
                "gpu_index": 0,
                "warnings": [],
                "rtf": 0.5,
                "estimate_seconds": pytest.approx(50.0),
            },
        ),
        (
            "cuda 1 MB below 1.5x VRAM -> good",
            cuda_fast,
            _fake_hw(
                ram_gb=8.0,
                gpus=[_gpu(vram_mb=12287, driver=linux_toolkit, compute_cap="8.6")],
            ),
            None,
            {"rating": "good", "tier": "cuda", "warnings": [], "estimate_seconds": None},
        ),
        (
            "cuda unknown rtf with 2x VRAM -> good (never great)",
            cuda_unknown_rtf,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap="8.6")]),
            1500,
            {"rating": "good", "tier": "cuda", "rtf": None, "estimate_seconds": None},
        ),
        (
            "cuda rtf=1.0 -> good (not slow)",
            cuda_borderline_rtf,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap="8.6")]),
            None,
            {"rating": "good", "tier": "cuda", "rtf": 1.0},
        ),
        (
            "cuda rtf=1.01 -> slow",
            cuda_slow,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap="8.6")]),
            1500,
            {
                "rating": "slow",
                "tier": "cuda",
                "rtf": 1.01,
                "estimate_seconds": pytest.approx(101.0),
            },
        ),
        # --- Driver boundaries & warnings ---
        (
            "linux driver at floor -> driver_below_recommended, capped at good",
            cuda_fast,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_floor, compute_cap="8.6")]),
            None,
            {
                "rating": "good",
                "tier": "cuda",
                "warnings": ["driver_below_recommended"],
            },
        ),
        (
            "windows driver at toolkit_driver -> great, no warning",
            cuda_fast,
            _fake_hw(
                os_name="Windows",
                gpus=[_gpu(vram_mb=16384, driver=win_toolkit, compute_cap="8.6")],
            ),
            None,
            {"rating": "great", "tier": "cuda", "warnings": []},
        ),
        (
            "windows driver at floor -> capped at good with driver_below_recommended",
            cuda_fast,
            _fake_hw(
                os_name="Windows",
                gpus=[_gpu(vram_mb=16384, driver=win_floor, compute_cap="8.6")],
            ),
            None,
            {
                "rating": "good",
                "tier": "cuda",
                "warnings": ["driver_below_recommended"],
            },
        ),
        (
            "windows driver below floor -> not_supported driver_too_old",
            cuda_fast,
            _fake_hw(
                os_name="Windows",
                gpus=[_gpu(vram_mb=16384, driver="528.32", compute_cap="8.6")],
            ),
            None,
            {"rating": "not_supported", "tier": None, "reason": "driver_too_old"},
        ),
        (
            "linux numeric driver comparison 525.60.2 < 525.60.13 -> driver_too_old",
            cuda_fast,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver="525.60.2", compute_cap="8.6")]),
            None,
            {"rating": "not_supported", "tier": None, "reason": "driver_too_old"},
        ),
        # --- Compute cap boundaries & warnings ---
        (
            "compute_cap 4.9 (Kepler) -> not_supported gpu_too_old",
            cuda_fast,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap="4.9")]),
            None,
            {"rating": "not_supported", "tier": None, "reason": "gpu_too_old"},
        ),
        (
            "compute_cap 5.0 (Maxwell) -> eligible with gpu_generation_unconfirmed, capped at good",
            cuda_fast,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap="5.0")]),
            None,
            {
                "rating": "good",
                "tier": "cuda",
                "warnings": ["gpu_generation_unconfirmed"],
            },
        ),
        (
            "compute_cap 6.1 (Pascal) -> eligible with gpu_generation_unconfirmed, capped at good",
            cuda_fast,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap="6.1")]),
            None,
            {
                "rating": "good",
                "tier": "cuda",
                "warnings": ["gpu_generation_unconfirmed"],
            },
        ),
        (
            "compute_cap None -> gpu_generation_unconfirmed, capped at good",
            cuda_fast,
            _fake_hw(
                gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap=None, bf16=False)],
            ),
            None,
            {
                "rating": "good",
                "tier": "cuda",
                "warnings": ["gpu_generation_unconfirmed"],
            },
        ),
        (
            "slow model with warning stays slow (warning does not upgrade slow to good)",
            cuda_slow,
            _fake_hw(gpus=[_gpu(vram_mb=16384, driver=linux_floor, compute_cap="6.1")]),
            None,
            {
                "rating": "slow",
                "tier": "cuda",
                "warnings": ["driver_below_recommended", "gpu_generation_unconfirmed"],
            },
        ),
        # --- CUDA failure reasons ---
        (
            "cuda-only on machine with no GPU -> needs_nvidia_gpu",
            cuda_fast,
            _fake_hw(gpus=[]),
            1500,
            {
                "rating": "not_supported",
                "tier": None,
                "reason": "needs_nvidia_gpu",
                "estimate_seconds": None,
            },
        ),
        (
            "cuda GPU 1 MB below min VRAM -> not_enough_vram",
            cuda_fast,
            _fake_hw(gpus=[_gpu(vram_mb=8191, driver=linux_toolkit, compute_cap="8.6")]),
            None,
            {"rating": "not_supported", "tier": None, "reason": "not_enough_vram"},
        ),
        (
            "cuda GPU OK but system RAM below cuda.min_ram_gb -> not_enough_ram",
            cuda_fast,
            _fake_hw(
                ram_gb=7.5,
                gpus=[_gpu(vram_mb=16384, driver=linux_toolkit, compute_cap="8.6")],
            ),
            None,
            {"rating": "not_supported", "tier": None, "reason": "not_enough_ram"},
        ),
        # --- CPU tier ---
        (
            "cpu-only model on machine with GPU -> uses CPU tier",
            cpu_fast,
            _fake_hw(ram_gb=6.0, gpus=[_gpu(vram_mb=24576, driver=linux_toolkit)]),
            300,
            {
                "rating": "great",
                "tier": "cpu",
                "gpu_index": None,
                "warnings": [],
                "rtf": 0.5,
                "estimate_seconds": pytest.approx(10.0),
            },
        ),
        (
            "cpu exact min RAM (4 GB) -> good",
            cpu_fast,
            _fake_hw(ram_gb=4.0),
            None,
            {"rating": "good", "tier": "cpu", "gpu_index": None},
        ),
        (
            "cpu below min RAM -> not_supported not_enough_ram",
            cpu_fast,
            _fake_hw(ram_gb=3.9),
            None,
            {"rating": "not_supported", "tier": None, "reason": "not_enough_ram"},
        ),
        (
            "cpu slow rtf > 1 -> slow",
            cpu_slow,
            _fake_hw(ram_gb=16.0),
            150,
            {
                "rating": "slow",
                "tier": "cpu",
                "rtf": 1.2,
                "estimate_seconds": pytest.approx(12.0),
            },
        ),
        (
            "cpu unknown rtf -> good (never great)",
            cpu_unknown_rtf,
            _fake_hw(ram_gb=16.0),
            150,
            {"rating": "good", "tier": "cpu", "rtf": None, "estimate_seconds": None},
        ),
        # --- Hybrid (CUDA + CPU fallback) ---
        (
            "hybrid with eligible GPU -> picks CUDA",
            hybrid,
            _fake_hw(ram_gb=16.0, gpus=[_gpu(vram_mb=12288, driver=linux_toolkit)]),
            1500,
            {"rating": "great", "tier": "cuda", "gpu_index": 0, "rtf": 0.3},
        ),
        (
            "hybrid without GPU -> falls back to CPU",
            hybrid,
            _fake_hw(ram_gb=16.0, gpus=[]),
            1500,
            {
                "rating": "slow",
                "tier": "cpu",
                "gpu_index": None,
                "rtf": 1.5,
                "estimate_seconds": pytest.approx(150.0),
            },
        ),
        (
            "hybrid with ineligible GPU and low RAM -> not_enough_ram",
            hybrid,
            _fake_hw(ram_gb=4.0, gpus=[_gpu(vram_mb=4096, driver=linux_toolkit)]),
            None,
            {"rating": "not_supported", "tier": None, "reason": "not_enough_ram"},
        ),
    ]

    for label, model_hw, machine_hw, char_count, expected in cases:
        result = rate_model_fit(model_hw, machine_hw, char_count=char_count)
        assert isinstance(result, FitRating), label
        for field_name, exp_val in expected.items():
            assert getattr(result, field_name) == exp_val, f"{label}: field {field_name}"


def test_fit_multi_gpu_selection_and_failure_details() -> None:
    model_hw = CatalogHardware(
        cpu=None,
        cuda=CudaHardware(min_vram_gb=8.0, min_ram_gb=8.0, rtf_reference=0.4),
    )

    # 1. Two eligible GPUs: picks highest VRAM (index 1).
    hw_multi = _fake_hw(
        ram_gb=16.0,
        gpus=[
            _gpu(name="RTX 3060", vram_mb=12288, driver="560.28.03", compute_cap="8.6"),
            _gpu(name="RTX 4090", vram_mb=24564, driver="560.28.03", compute_cap="8.9"),
        ],
    )
    fit = rate_model_fit(model_hw, hw_multi, char_count=0)
    assert fit.rating == "great"
    assert fit.tier == "cuda"
    assert fit.gpu_index == 1
    assert fit.estimate_seconds == 0.0

    # 1b. Two eligible GPUs with equal VRAM: picks the lower gpu_index (0).
    hw_equal_vram = _fake_hw(
        ram_gb=16.0,
        gpus=[
            _gpu(name="RTX 3060 A", vram_mb=12288, driver="560.28.03", compute_cap="8.6"),
            _gpu(name="RTX 3060 B", vram_mb=12288, driver="560.28.03", compute_cap="8.6"),
        ],
    )
    fit_equal = rate_model_fit(model_hw, hw_equal_vram)
    assert fit_equal.rating == "great"
    assert fit_equal.tier == "cuda"
    assert fit_equal.gpu_index == 0

    # 2. GPU 0 is huge (24 GB) but Kepler (too old); GPU 1 is 12 GB Ampere -> picks GPU 1.
    hw_mixed = _fake_hw(
        ram_gb=16.0,
        gpus=[
            _gpu(name="Tesla K80", vram_mb=24576, driver="560.28.03", compute_cap="3.7"),
            _gpu(name="RTX 3060", vram_mb=12288, driver="560.28.03", compute_cap="8.6"),
        ],
    )
    fit_mixed = rate_model_fit(model_hw, hw_mixed)
    assert fit_mixed.rating == "great"
    assert fit_mixed.gpu_index == 1

    # 3. Multiple ineligible GPUs: GPU 0 is 4 GB, GPU 1 is 8 GB with old driver -> driver_too_old.
    hw_fail_multi = _fake_hw(
        ram_gb=16.0,
        gpus=[
            _gpu(name="GTX 1650", vram_mb=4096, driver="560.28.03", compute_cap="7.5"),
            _gpu(name="RTX 3070", vram_mb=8192, driver="510.47.03", compute_cap="8.6"),
        ],
    )
    fit_fail = rate_model_fit(model_hw, hw_fail_multi)
    assert fit_fail.rating == "not_supported"
    assert fit_fail.reason == "driver_too_old"
    assert fit_fail.details == {"needed_driver": "525.60.13", "actual_driver": "510.47.03"}

    # 3b. Multiple ineligible GPUs with equal blocker count and kind: reports highest VRAM GPU.
    hw_fail_same_blocker = _fake_hw(
        ram_gb=16.0,
        gpus=[
            _gpu(name="GTX 1650", vram_mb=4096, driver="560.28.03", compute_cap="7.5"),
            _gpu(name="RTX 2060", vram_mb=6144, driver="560.28.03", compute_cap="7.5"),
        ],
    )
    fit_fail_vram = rate_model_fit(model_hw, hw_fail_same_blocker)
    assert fit_fail_vram.rating == "not_supported"
    assert fit_fail_vram.reason == "not_enough_vram"
    assert fit_fail_vram.details == {
        "needed_vram_gb": 8.0,
        "actual_vram_mb": 6144,
        "actual_vram_gb": 6.0,
    }

    # 4. Details populated for not_enough_vram, needs_nvidia_gpu, gpu_too_old, not_enough_ram.
    fit_vram = rate_model_fit(
        model_hw,
        _fake_hw(ram_gb=16.0, gpus=[_gpu(vram_mb=6144, driver="560.28.03")]),
    )
    assert fit_vram.reason == "not_enough_vram"
    assert fit_vram.details == {
        "needed_vram_gb": 8.0,
        "actual_vram_mb": 6144,
        "actual_vram_gb": 6.0,
    }

    fit_no_gpu = rate_model_fit(model_hw, _fake_hw(gpus=[]))
    assert fit_no_gpu.reason == "needs_nvidia_gpu"
    assert fit_no_gpu.details == {"needed_vram_gb": 8.0, "actual_gpus": 0}

    fit_kepler = rate_model_fit(
        model_hw,
        _fake_hw(gpus=[_gpu(vram_mb=12288, driver="560.28.03", compute_cap="3.5")]),
    )
    assert fit_kepler.reason == "gpu_too_old"
    assert fit_kepler.details == {"needed_compute_cap": "5.0", "actual_compute_cap": "3.5"}

    fit_ram = rate_model_fit(
        model_hw,
        _fake_hw(ram_gb=4.0, gpus=[_gpu(vram_mb=12288, driver="560.28.03")]),
    )
    assert fit_ram.reason == "not_enough_ram"
    assert fit_ram.details is not None
    assert fit_ram.details["needed_ram_gb"] == 8.0
    assert fit_ram.details["actual_ram_gb"] == 4.0

    assert CHARS_PER_SECOND_ESTIMATE == 15.0
