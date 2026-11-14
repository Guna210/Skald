"""Handler for the `system.info` JSON-RPC method."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from pathlib import Path

import lxml  # type: ignore[import-untyped]
import numpy
import pydantic

from skald_core import __version__
from skald_core.schemas import SystemInfo

logger = logging.getLogger(__name__)

FFMPEG_BIN_BY_PLATFORM: dict[str, str] = {
    "win64": "bin/ffmpeg.exe",
    "linux64": "bin/ffmpeg",
}
_FFMPEG_TIMEOUT_S = 5.0


def _detect_platform() -> str | None:
    sys_name = platform.system().lower()
    arch = platform.machine().lower()
    if sys_name == "windows" and arch in {"amd64", "x86_64", "x64"}:
        return "win64"
    if sys_name == "linux" and arch in {"x86_64", "amd64"}:
        return "linux64"
    return None


def _resolve_ffmpeg_path() -> Path | None:
    env_ffmpeg = os.environ.get("SKALD_FFMPEG", "").strip()
    if env_ffmpeg:
        return Path(env_ffmpeg)

    env_vendor = os.environ.get("SKALD_VENDOR", "").strip()
    if not env_vendor:
        return None

    plat = _detect_platform()
    if plat is None:
        logger.warning(
            "Unsupported platform for vendored ffmpeg lookup: %s/%s",
            platform.system(),
            platform.machine(),
        )
        return None

    return Path(env_vendor) / "ffmpeg" / plat / FFMPEG_BIN_BY_PLATFORM[plat]


def _probe_ffmpeg_version() -> str | None:
    ffmpeg_path = _resolve_ffmpeg_path()
    if ffmpeg_path is None:
        logger.warning("ffmpeg not configured (set SKALD_FFMPEG or SKALD_VENDOR)")
        return None
    if not ffmpeg_path.is_file():
        logger.warning("ffmpeg binary not found at %s", ffmpeg_path)
        return None

    try:
        proc = subprocess.run(
            [str(ffmpeg_path), "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_FFMPEG_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Failed to run ffmpeg at %s: %s", ffmpeg_path, exc)
        return None

    if proc.returncode != 0:
        logger.warning(
            "ffmpeg -version exited with %d (%s)",
            proc.returncode,
            proc.stderr.strip() or "no stderr",
        )
        return None

    first_line = proc.stdout.splitlines()[0].strip() if proc.stdout.strip() else ""
    if not first_line:
        logger.warning("ffmpeg -version produced empty output")
        return None
    return first_line


def get_system_info() -> SystemInfo:
    """Return core, dependency, and ffmpeg versions."""
    return SystemInfo(
        core=__version__,
        python=platform.python_version(),
        lxml=str(lxml.__version__),
        pydantic=pydantic.__version__,
        numpy=numpy.__version__,
        ffmpeg=_probe_ffmpeg_version(),
    )
