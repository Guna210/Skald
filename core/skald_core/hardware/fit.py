"""Model hardware fit rating and synthesis time estimation (SPEC B4.3)."""

from __future__ import annotations

from typing import Any

from skald_core.catalog.schema import CatalogHardware, CudaHardware
from skald_core.hardware.probe import parse_numeric_version
from skald_core.packs.manager import CUDA_DRIVER_REQUIREMENTS
from skald_core.schemas import (
    FitRating,
    FitRatingLevel,
    FitReason,
    FitWarning,
    GpuInfo,
    HardwareInfo,
)

CHARS_PER_SECOND_ESTIMATE = 15.0

_BYTES_PER_GB = 1024**3
_MB_PER_GB = 1024
_MIN_COMPUTE_CAP = (5, 0)
_CONFIRMED_COMPUTE_CAP = (7, 0)
_GREAT_HEADROOM_MULTIPLIER = 1.5
_GREAT_MAX_RTF = 0.5
_SLOW_MIN_RTF = 1.0

# Within one GPU, unfixable hardware blockers take precedence over fixable driver/RAM issues.
_SINGLE_GPU_BLOCKER_ORDER: dict[FitReason, int] = {
    "gpu_too_old": 0,
    "not_enough_vram": 1,
    "driver_too_old": 2,
    "not_enough_ram": 3,
}

# Across multiple GPUs, prefer reporting a GPU whose blocker is software/fixable or closer to fit.
_MULTI_GPU_PREFERENCE_ORDER: dict[FitReason, int] = {
    "driver_too_old": 0,
    "not_enough_ram": 1,
    "not_enough_vram": 2,
    "gpu_too_old": 3,
}


def _version_lt(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    width = max(len(a), len(b))
    padded_a = a + (0,) * (width - len(a))
    padded_b = b + (0,) * (width - len(b))
    return padded_a < padded_b


def _parse_compute_cap_pair(compute_cap: str | None) -> tuple[int, int] | None:
    if compute_cap is None:
        return None
    try:
        parts = parse_numeric_version(compute_cap)
    except ValueError:
        return None
    return (parts[0], parts[1] if len(parts) > 1 else 0)


def _compute_tier_rating(*, headroom_ok: bool, rtf: float | None) -> FitRatingLevel:
    if rtf is not None and rtf > _SLOW_MIN_RTF:
        return "slow"
    if headroom_ok and rtf is not None and rtf <= _GREAT_MAX_RTF:
        return "great"
    return "good"


def _estimate_seconds(char_count: int | None, rtf: float | None) -> float | None:
    if char_count is None or rtf is None:
        return None
    return (char_count / CHARS_PER_SECOND_ESTIMATE) * rtf


def _driver_thresholds(os_name: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    os_key = "windows" if os_name.strip().lower() == "windows" else "linux"
    reqs = CUDA_DRIVER_REQUIREMENTS["cu126"][os_key]
    min_driver_str = str(reqs["min_driver"])
    toolkit_driver_str = str(reqs["toolkit_driver"])
    return (
        min_driver_str,
        parse_numeric_version(min_driver_str),
        parse_numeric_version(toolkit_driver_str),
    )


def _gpu_failure_reasons(
    gpu: GpuInfo,
    cuda: CudaHardware,
    hw: HardwareInfo,
    min_driver_ver: tuple[int, ...],
) -> list[FitReason]:
    reasons: list[FitReason] = []
    if gpu.compute_cap is not None:
        cap = _parse_compute_cap_pair(gpu.compute_cap)
        if cap is None or cap < _MIN_COMPUTE_CAP:
            reasons.append("gpu_too_old")

    if gpu.memory_total_mb < cuda.min_vram_gb * _MB_PER_GB:
        reasons.append("not_enough_vram")

    try:
        driver_ver = parse_numeric_version(gpu.driver_version)
    except ValueError:
        reasons.append("driver_too_old")
    else:
        if _version_lt(driver_ver, min_driver_ver):
            reasons.append("driver_too_old")

    if cuda.min_ram_gb is not None and hw.ram_total_bytes < cuda.min_ram_gb * _BYTES_PER_GB:
        reasons.append("not_enough_ram")

    return reasons


def _failure_details(
    reason: FitReason,
    gpu: GpuInfo,
    cuda: CudaHardware,
    hw: HardwareInfo,
    min_driver_str: str,
) -> dict[str, Any]:
    if reason == "gpu_too_old":
        return {"needed_compute_cap": "5.0", "actual_compute_cap": gpu.compute_cap}
    if reason == "not_enough_vram":
        return {
            "needed_vram_gb": cuda.min_vram_gb,
            "actual_vram_mb": gpu.memory_total_mb,
            "actual_vram_gb": round(gpu.memory_total_mb / _MB_PER_GB, 2),
        }
    if reason == "driver_too_old":
        return {"needed_driver": min_driver_str, "actual_driver": gpu.driver_version}
    return {
        "needed_ram_gb": cuda.min_ram_gb,
        "actual_ram_bytes": hw.ram_total_bytes,
        "actual_ram_gb": round(hw.ram_total_bytes / _BYTES_PER_GB, 2),
    }


def _rate_cuda_failure(
    cuda: CudaHardware,
    hw: HardwareInfo,
    min_driver_str: str,
    failures_by_gpu: list[tuple[GpuInfo, list[FitReason]]],
) -> FitRating:
    if not hw.gpus:
        return FitRating(
            rating="not_supported",
            tier=None,
            reason="needs_nvidia_gpu",
            details={"needed_vram_gb": cuda.min_vram_gb, "actual_gpus": 0},
        )

    best_candidate: tuple[tuple[int, int, int], GpuInfo, FitReason] | None = None
    for gpu, reasons in failures_by_gpu:
        primary = min(reasons, key=lambda r: _SINGLE_GPU_BLOCKER_ORDER[r])
        rank = (
            len(reasons),
            _MULTI_GPU_PREFERENCE_ORDER[primary],
            -gpu.memory_total_mb,
        )
        if best_candidate is None or rank < best_candidate[0]:
            best_candidate = (rank, gpu, primary)

    assert best_candidate is not None
    _, chosen_gpu, chosen_reason = best_candidate
    return FitRating(
        rating="not_supported",
        tier=None,
        reason=chosen_reason,
        details=_failure_details(chosen_reason, chosen_gpu, cuda, hw, min_driver_str),
    )


def rate_model_fit(
    model_hardware: CatalogHardware,
    hw: HardwareInfo,
    *,
    char_count: int | None = None,
) -> FitRating:
    """Rate how well `hw` runs a model with `model_hardware` and estimate duration."""
    cuda = model_hardware.cuda
    cpu = model_hardware.cpu

    min_driver_str = ""
    failures_by_gpu: list[tuple[GpuInfo, list[FitReason]]] = []

    if cuda is not None:
        min_driver_str, min_driver_ver, toolkit_driver_ver = _driver_thresholds(hw.os)
        eligible: list[tuple[int, GpuInfo]] = []
        for idx, gpu in enumerate(hw.gpus):
            reasons = _gpu_failure_reasons(gpu, cuda, hw, min_driver_ver)
            if not reasons:
                eligible.append((idx, gpu))
            else:
                failures_by_gpu.append((gpu, reasons))

        if eligible:
            best_idx, best_gpu = max(eligible, key=lambda item: (item[1].memory_total_mb, -item[0]))
            min_vram_mb = cuda.min_vram_gb * _MB_PER_GB
            headroom_ok = best_gpu.memory_total_mb >= _GREAT_HEADROOM_MULTIPLIER * min_vram_mb
            rtf = cuda.rtf_reference
            rating = _compute_tier_rating(headroom_ok=headroom_ok, rtf=rtf)

            warnings: list[FitWarning] = []
            if _version_lt(parse_numeric_version(best_gpu.driver_version), toolkit_driver_ver):
                warnings.append("driver_below_recommended")
            cap_pair = _parse_compute_cap_pair(best_gpu.compute_cap)
            if cap_pair is None or cap_pair < _CONFIRMED_COMPUTE_CAP:
                warnings.append("gpu_generation_unconfirmed")

            if warnings and rating == "great":
                rating = "good"

            return FitRating(
                rating=rating,
                tier="cuda",
                gpu_index=best_idx,
                warnings=warnings,
                rtf=rtf,
                estimate_seconds=_estimate_seconds(char_count, rtf),
            )

    if cpu is not None:
        min_ram_bytes = cpu.min_ram_gb * _BYTES_PER_GB
        if hw.ram_total_bytes >= min_ram_bytes:
            headroom_ok = hw.ram_total_bytes >= _GREAT_HEADROOM_MULTIPLIER * min_ram_bytes
            rtf = cpu.rtf_reference
            rating = _compute_tier_rating(headroom_ok=headroom_ok, rtf=rtf)
            return FitRating(
                rating=rating,
                tier="cpu",
                gpu_index=None,
                warnings=[],
                rtf=rtf,
                estimate_seconds=_estimate_seconds(char_count, rtf),
            )
        return FitRating(
            rating="not_supported",
            tier=None,
            reason="not_enough_ram",
            details={
                "needed_ram_gb": cpu.min_ram_gb,
                "actual_ram_bytes": hw.ram_total_bytes,
                "actual_ram_gb": round(hw.ram_total_bytes / _BYTES_PER_GB, 2),
            },
        )

    if cuda is not None:
        return _rate_cuda_failure(cuda, hw, min_driver_str, failures_by_gpu)

    return FitRating(rating="not_supported", tier=None)
