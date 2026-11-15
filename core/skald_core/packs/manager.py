"""Engine pack builder: base Python copy, uv sync, worker install, check, repair, remove."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from skald_core.jobs.manager import JobContext, JobManager
from skald_core.project.store import atomic_write_json
from skald_core.rpc.server import SkaldError
from skald_core.rpc.system import _detect_platform
from skald_core.storage import get_storage_dir, packs_dir, python_dir, uv_cache_dir

UV_BIN_BY_PLATFORM: dict[str, str] = {
    "win64": "uv.exe",
    "linux64": "uv",
}

PYTHON_BIN_BY_PLATFORM: dict[str, str] = {
    "win64": "python.exe",
    "linux64": "bin/python",
}

PACK_META_FILENAME = "pack.json"
MAX_PACK_NAME_LEN = 40
WINDOWS_MAX_PACK_PATH_LEN = 150
_ERROR_LOG_TAIL_LINES = 30

# Minimum NVIDIA driver versions from NVIDIA CUDA Toolkit 12.6 Release Notes & Compatibility Guide
# (https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html, Tables 3 & 4).
# PyTorch cu126 wheels bundle the CUDA 12.6 runtime, so the CUDA 12.x minor-version compatibility
# floor applies; the native 12.6 toolkit driver is recorded alongside it.
CUDA_DRIVER_REQUIREMENTS: dict[str, dict[str, dict[str, str]]] = {
    "cu126": {
        "linux": {
            "min_driver": "525.60.13",
            "toolkit_driver": "560.28.03",
            "source_url": "https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html",
            "reason": (
                "CUDA 12.x minor-version compatibility floor; "
                "PyTorch wheels bundle the CUDA 12.6 runtime."
            ),
        },
        "windows": {
            "min_driver": "528.33",
            "toolkit_driver": "560.76",
            "source_url": "https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html",
            "reason": (
                "CUDA 12.x minor-version compatibility floor; "
                "PyTorch wheels bundle the CUDA 12.6 runtime."
            ),
        },
    }
}

_BACKEND_RE = re.compile(r"^\s*#\s*skald-backend:\s*([A-Za-z0-9_.-]+)\s*$")
_REQUIRED_BYTES_RE = re.compile(r"^\s*#\s*skald-required-bytes:\s*(\d+)\s*$")
_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==")
_PYVENV_HOME_RE = re.compile(r"^\s*home\s*=\s*(.+?)\s*$")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OFFLINE_PATTERNS = (
    "connection refused",
    "dns error",
    "failed to lookup address",
    "could not resolve host",
    "network is unreachable",
    "temporary failure in name resolution",
    "error sending request for url",
    "timed out",
    "offline mode",
)


@dataclass(frozen=True)
class LockInfo:
    """Parsed metadata, LF-normalised SHA-256, and package list from a lockfile."""

    path: Path
    backend: str
    accel: str
    required_bytes: int
    sha256: str
    hash8: str
    packages: tuple[str, ...]


class PackMetadata(BaseModel):
    """Metadata written to `<pack_dir>/pack.json` only after step 4 passes."""

    family: str
    os: str
    accel: str
    backend: str
    lock_sha256: str
    lock_hash8: str
    packages: list[str] = Field(default_factory=list)
    base_python_dir: str
    python_version: str
    uv_version: str
    worker_version: str | None = None
    min_nvidia_driver: str | None = None
    min_nvidia_driver_reason: str | None = None
    nvidia_driver_source: str | None = None
    cuda_toolkit_driver: str | None = None
    created_at: str


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_pkg_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _current_pack_os() -> str:
    return "windows" if platform.system().lower() == "windows" else "linux"


def _backend_to_accel(backend: str) -> str:
    if backend == "cpu":
        return "cpu"
    if backend.startswith("cu12"):
        return "cu12"
    return backend


def lock_sha256(lockfile: Path) -> str:
    """Compute the SHA-256 hex digest of a lockfile after LF normalisation."""
    raw = lockfile.read_bytes()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def parse_lockfile(lockfile: Path) -> LockInfo:
    """Read backend header, required-bytes header, LF-normalised hash, and package names."""
    if not lockfile.is_file():
        raise SkaldError(
            "pack_install_failed",
            f"Lockfile not found: {lockfile}",
            details={"lockfile": str(lockfile)},
        )

    raw = lockfile.read_bytes()
    norm_bytes = raw.replace(b"\r\n", b"\n")
    digest = hashlib.sha256(norm_bytes).hexdigest()
    text = norm_bytes.decode("utf-8")

    backend: str | None = None
    required_bytes: int | None = None
    packages: list[str] = []

    for line in text.splitlines():
        if backend is None:
            match = _BACKEND_RE.match(line)
            if match:
                backend = match.group(1)
                continue
        if required_bytes is None:
            match = _REQUIRED_BYTES_RE.match(line)
            if match:
                required_bytes = int(match.group(1))
                continue
        pin_match = _PIN_RE.match(line)
        if pin_match:
            packages.append(_normalize_pkg_name(pin_match.group(1)))

    if not backend:
        raise SkaldError(
            "pack_install_failed",
            f"Lockfile is missing '# skald-backend:' header: {lockfile}",
            details={"lockfile": str(lockfile)},
        )
    if required_bytes is None:
        raise SkaldError(
            "pack_install_failed",
            f"Lockfile is missing '# skald-required-bytes:' header: {lockfile}",
            details={"lockfile": str(lockfile)},
        )
    if not packages:
        raise SkaldError(
            "pack_install_failed",
            f"Lockfile contains no pinned packages: {lockfile}",
            details={"lockfile": str(lockfile)},
        )

    return LockInfo(
        path=lockfile,
        backend=backend,
        accel=_backend_to_accel(backend),
        required_bytes=required_bytes,
        sha256=digest,
        hash8=digest[:8],
        packages=tuple(packages),
    )


def build_uv_env(
    storage_dir: Path,
    base_env: Mapping[str, str] | None = None,
    *,
    offline: bool = False,
) -> dict[str, str]:
    """Construct the fixed B5 environment for uv subprocesses.

    Strips every user `UV_*` variable while keeping proxy and `SSL_CERT_FILE` settings.
    """
    source = os.environ if base_env is None else base_env
    env = {k: v for k, v in source.items() if not k.startswith("UV_")}
    env.update(
        UV_NO_CONFIG="1",
        UV_CACHE_DIR=str(uv_cache_dir(storage_dir)),
        UV_LINK_MODE="hardlink",
        UV_PYTHON_DOWNLOADS="never",
        UV_SYSTEM_CERTS="1",
        UV_NO_PROGRESS="1",
    )
    if offline:
        env["UV_OFFLINE"] = "1"
    return env


def _lp(path: Path) -> str:
    if platform.system().lower() == "windows":
        resolved = os.path.abspath(path)
        return resolved if resolved.startswith("\\\\?\\") else "\\\\?\\" + resolved
    return str(path)


def _rmtree(path: Path) -> None:
    target = _lp(path)
    if not os.path.exists(target):
        return

    def _onexc(func: Any, p: str, _exc: BaseException) -> None:
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(target, onexc=_onexc)


def _pack_python_path(pack_dir: Path, os_name: str | None = None) -> Path:
    target_os = _current_pack_os() if os_name is None else os_name
    if target_os == "windows":
        return pack_dir / "Scripts" / "python.exe"
    return pack_dir / "bin" / "python"


def _read_pyvenv_home(pack_dir: Path) -> Path | None:
    cfg = pack_dir / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _PYVENV_HOME_RE.match(line)
        if match:
            return Path(match.group(1))
    return None


def _paths_equal(a: Path, b: Path) -> bool:
    norm_a = os.path.normcase(os.path.abspath(a))
    norm_b = os.path.normcase(os.path.abspath(b))
    return norm_a == norm_b


def _read_installed_version(python_vendor_dir: Path) -> str:
    marker = python_vendor_dir / ".installed.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            ver = data.get("version")
            if isinstance(ver, str) and ver.strip():
                return ver.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return f"{platform.python_version()}-bundled"


def _classify_failure(stage: str, rc: int, log_lines: list[str]) -> SkaldError:
    joined = "\n".join(log_lines).lower()
    details = {"stage": stage, "returncode": rc, "log_tail": log_lines[-_ERROR_LOG_TAIL_LINES:]}

    if "unknownissuer" in joined or "invalid peer certificate" in joined:
        return SkaldError(
            "pack_install_failed",
            f"Pack install failed at stage '{stage}' due to TLS certificate verification.",
            details=details,
            hint=(
                "Your network appears to inspect HTTPS traffic. "
                "Ask IT for the proxy CA certificate or install it in the OS trust store."
            ),
        )

    if any(pattern in joined for pattern in _OFFLINE_PATTERNS):
        return SkaldError(
            "offline",
            f"Pack install failed at stage '{stage}' because the network is unreachable.",
            details=details,
            hint="Check your internet connection or proxy settings and try again.",
        )

    return SkaldError(
        "pack_install_failed",
        f"Pack install failed at stage '{stage}' (exit code {rc}).",
        details=details,
        hint="Open logs for details or repair the pack.",
    )


class PackManager:
    """Manages engine pack installation, verification, repair, and removal."""

    def __init__(
        self,
        storage_dir: Path | None = None,
        packs_source_dir: Path | None = None,
        vendor_dir: Path | None = None,
        uv_cmd: Sequence[str | Path] | None = None,
    ) -> None:
        self._storage_dir = storage_dir
        self._packs_source_dir = (
            (_REPO_ROOT / "packs") if packs_source_dir is None else packs_source_dir
        )
        self._vendor_dir = vendor_dir
        self._uv_cmd = [str(part) for part in uv_cmd] if uv_cmd is not None else None

    def storage_root(self) -> Path:
        return get_storage_dir() if self._storage_dir is None else self._storage_dir

    def vendor_root(self) -> Path:
        if self._vendor_dir is not None:
            return self._vendor_dir
        env_vendor = os.environ.get("SKALD_VENDOR", "").strip()
        if env_vendor:
            return Path(env_vendor)
        return _REPO_ROOT / "vendor"

    def uv_command_prefix(self) -> list[str]:
        if self._uv_cmd is not None:
            return list(self._uv_cmd)
        plat = _detect_platform()
        if plat is None:
            raise SkaldError(
                "pack_install_failed",
                f"Unsupported platform: {platform.system()}/{platform.machine()}",
            )
        uv_path = self.vendor_root() / "uv" / plat / UV_BIN_BY_PLATFORM[plat]
        if not uv_path.is_file():
            raise SkaldError(
                "pack_install_failed",
                f"Bundled uv binary not found at {uv_path}",
                hint="Run setup to fetch pinned binaries into vendor/.",
            )
        return [str(uv_path)]

    def bundled_python_info(self) -> tuple[Path, str, str]:
        """Return `(python_vendor_dir, bin_relpath, pbs_version)` for the current platform."""
        plat = _detect_platform()
        if plat is None:
            raise SkaldError(
                "pack_install_failed",
                f"Unsupported platform: {platform.system()}/{platform.machine()}",
            )
        vendor_py_dir = self.vendor_root() / "python" / plat
        bin_rel = PYTHON_BIN_BY_PLATFORM[plat]
        if not (vendor_py_dir / bin_rel).is_file():
            raise SkaldError(
                "pack_install_failed",
                f"Bundled Python not found at {vendor_py_dir / bin_rel}",
                hint="Run setup to fetch pinned binaries into vendor/.",
            )
        return vendor_py_dir, bin_rel, _read_installed_version(vendor_py_dir)

    def ensure_base_python(self, storage_dir: Path | None = None) -> tuple[Path, Path, str]:
        """Copy bundled CPython into `<storage>/python/<pbs-version>/` once and return paths."""
        storage = self.storage_root() if storage_dir is None else storage_dir
        vendor_py_dir, bin_rel, pbs_version = self.bundled_python_info()
        dest_dir = python_dir(storage) / pbs_version
        dest_exe = dest_dir / bin_rel
        if dest_exe.is_file():
            return dest_exe, dest_dir, pbs_version

        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = dest_dir.parent / f".{pbs_version}.{secrets.token_hex(4)}.tmp"
        try:
            shutil.copytree(vendor_py_dir, tmp_dir, symlinks=True)
            try:
                os.replace(tmp_dir, dest_dir)
            except OSError:
                if not dest_exe.is_file():
                    raise
        finally:
            if tmp_dir.exists():
                _rmtree(tmp_dir)
        return dest_exe, dest_dir, pbs_version

    def resolve_lockfile(
        self,
        family: str,
        accel: str | None = None,
        os_name: str | None = None,
    ) -> Path:
        """Find the committed lockfile for `(family, os_name, accel)`."""
        target_os = _current_pack_os() if os_name is None else os_name
        locks_dir = self._packs_source_dir / family / "locks"
        if accel is not None:
            candidate = locks_dir / f"{target_os}-{accel}.txt"
            if not candidate.is_file():
                raise SkaldError(
                    "pack_install_failed",
                    f"Lockfile not found for {family} ({target_os}-{accel}): {candidate}",
                )
            return candidate

        matches = sorted(locks_dir.glob(f"{target_os}-*.txt")) if locks_dir.is_dir() else []
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise SkaldError(
                "pack_install_failed",
                f"No lockfiles found for {family} on {target_os} in {locks_dir}",
            )
        raise ValueError(
            f"Multiple lockfiles found for {family} on {target_os}; pass accel explicitly"
        )

    def pack_dir_for(
        self,
        family: str,
        lock_info: LockInfo,
        *,
        storage_dir: Path | None = None,
        os_name: str | None = None,
    ) -> Path:
        """Compute pack folder path and enforce the 40-char name & Windows 150-char limits."""
        storage = self.storage_root() if storage_dir is None else storage_dir
        target_os = _current_pack_os() if os_name is None else os_name
        dir_name = f"{family}-{target_os}-{lock_info.accel}-{lock_info.hash8}"
        if len(dir_name) > MAX_PACK_NAME_LEN:
            raise SkaldError(
                "pack_install_failed",
                f"Pack folder name exceeds {MAX_PACK_NAME_LEN} characters: {dir_name}",
                details={"pack_name": dir_name, "length": len(dir_name)},
            )
        target = packs_dir(storage) / dir_name
        if target_os == "windows" and len(str(target)) > WINDOWS_MAX_PACK_PATH_LEN:
            raise SkaldError(
                "pack_install_failed",
                (
                    f"Pack path exceeds {WINDOWS_MAX_PACK_PATH_LEN} characters on Windows "
                    f"({len(str(target))} characters): {target}"
                ),
                details={
                    "path": str(target),
                    "length": len(str(target)),
                    "limit": WINDOWS_MAX_PACK_PATH_LEN,
                },
                hint="Choose a shorter model storage folder in Settings.",
            )
        return target

    def read_pack_metadata(self, pack_dir: Path) -> PackMetadata | None:
        meta_path = pack_dir / PACK_META_FILENAME
        if not meta_path.is_file():
            return None
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            return PackMetadata.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError):
            return None

    def is_valid_pack(self, pack_dir: Path, expected_lock_sha256: str | None = None) -> bool:
        meta = self.read_pack_metadata(pack_dir)
        if meta is None:
            return False
        if expected_lock_sha256 is not None and meta.lock_sha256 != expected_lock_sha256:
            return False
        return True

    def list_packs(self, storage_dir: Path | None = None) -> dict[Path, PackMetadata]:
        """Return all valid packs (those with a valid `pack.json`) under `<storage>/packs/`."""
        storage = self.storage_root() if storage_dir is None else storage_dir
        root = packs_dir(storage)
        if not root.is_dir():
            return {}
        found: dict[Path, PackMetadata] = {}
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            meta = self.read_pack_metadata(entry)
            if meta is not None:
                found[entry] = meta
        return found

    def _run_subprocess(
        self,
        ctx: JobContext,
        cmd: Sequence[str],
        env: Mapping[str, str],
        stage: str,
        recent_logs: deque[str],
    ) -> list[str]:
        ctx.log("info", f"+ {' '.join(cmd)}")
        captured_lines: list[str] = []
        with subprocess.Popen(
            list(cmd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(env),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as proc:
            ctx.register_subprocess(proc)
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\r\n")
                captured_lines.append(line)
                if line:
                    recent_logs.append(line)
                    ctx.log("info", line)
            rc = proc.wait()

        ctx.checkpoint()
        if rc != 0:
            raise _classify_failure(stage, rc, list(recent_logs))
        return captured_lines

    def _probe_version(self, cmd: Sequence[str], env: Mapping[str, str], default: str) -> str:
        try:
            proc = subprocess.run(
                list(cmd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=dict(env),
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10.0,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            pass
        return default

    def _repoint_base_python_if_needed(
        self,
        ctx: JobContext,
        pack_dir: Path,
        base_python_exe: Path,
        env: Mapping[str, str],
        recent_logs: deque[str],
    ) -> bool:
        current_home = _read_pyvenv_home(pack_dir)
        expected_home = base_python_exe.parent
        if current_home is not None and _paths_equal(current_home, expected_home):
            return False
        uv_prefix = self.uv_command_prefix()
        self._run_subprocess(
            ctx,
            [
                *uv_prefix,
                "venv",
                "--allow-existing",
                "--relocatable",
                "--python",
                str(base_python_exe),
                str(pack_dir),
            ],
            env=env,
            stage="venv",
            recent_logs=recent_logs,
        )
        return True

    def submit_install(
        self,
        job_manager: JobManager,
        family: str,
        *,
        accel: str | None = None,
        lockfile: Path | None = None,
        expected_lock_sha256: str | None = None,
        worker_wheel: Path | None = None,
        offline: bool = False,
    ) -> str:
        """Submit `install_job` to a `JobManager` and return its `job_id`."""
        return job_manager.submit(
            "pack.install",
            self.install_job,
            family=family,
            accel=accel,
            lockfile=lockfile,
            expected_lock_sha256=expected_lock_sha256,
            worker_wheel=worker_wheel,
            offline=offline,
        )

    def submit_repair(
        self,
        job_manager: JobManager,
        family: str,
        *,
        accel: str | None = None,
        lockfile: Path | None = None,
        worker_wheel: Path | None = None,
        offline: bool = False,
    ) -> str:
        """Submit `repair_job` to a `JobManager` and return its `job_id`."""
        return job_manager.submit(
            "pack.repair",
            self.repair_job,
            family=family,
            accel=accel,
            lockfile=lockfile,
            worker_wheel=worker_wheel,
            offline=offline,
        )

    def install_job(
        self,
        ctx: JobContext,
        family: str,
        *,
        accel: str | None = None,
        lockfile: Path | None = None,
        expected_lock_sha256: str | None = None,
        worker_wheel: Path | None = None,
        offline: bool = False,
    ) -> dict[str, Any]:
        """JobManager entry point implementing B5 steps 1–5 with stage progress."""
        storage = self.storage_root()
        target_os = _current_pack_os()
        resolved_lock = (
            self.resolve_lockfile(family, accel=accel, os_name=target_os)
            if lockfile is None
            else lockfile
        )
        lock_info = parse_lockfile(resolved_lock)

        if expected_lock_sha256 is not None and lock_info.sha256 != expected_lock_sha256:
            raise SkaldError(
                "checksum_mismatch",
                f"Lockfile SHA-256 mismatch for {resolved_lock.name}",
                details={
                    "expected": expected_lock_sha256,
                    "actual": lock_info.sha256,
                    "lockfile": str(resolved_lock),
                },
            )

        pack_dir = self.pack_dir_for(family, lock_info, storage_dir=storage, os_name=target_os)
        uv_prefix = self.uv_command_prefix()
        env = build_uv_env(storage, offline=offline)
        recent_logs: deque[str] = deque(maxlen=_ERROR_LOG_TAIL_LINES)

        existing_meta = self.read_pack_metadata(pack_dir)
        if existing_meta is not None and existing_meta.lock_sha256 == lock_info.sha256:
            base_python_exe, base_python_dir, _ = self.ensure_base_python(storage)
            if self._repoint_base_python_if_needed(
                ctx, pack_dir, base_python_exe, env, recent_logs
            ):
                updated_meta = existing_meta.model_copy(
                    update={"base_python_dir": str(base_python_dir)}
                )
                atomic_write_json(
                    pack_dir / PACK_META_FILENAME, updated_meta.model_dump(mode="json")
                )
                existing_meta = updated_meta
            ctx.progress(1.0, f"Pack {family} already installed", "finalize")
            return {"pack_dir": str(pack_dir), "metadata": existing_meta.model_dump(mode="json")}

        # Clean up any half-built directory (missing or invalid pack.json) before rebuilding.
        if pack_dir.exists():
            ctx.log("warning", f"Removing half-built or invalid pack folder: {pack_dir}")
            _rmtree(pack_dir)

        storage.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(storage).free
        if free_bytes < lock_info.required_bytes:
            raise SkaldError(
                "not_enough_disk",
                (
                    f"Not enough disk space in {storage}: need {lock_info.required_bytes} bytes, "
                    f"have {free_bytes} bytes"
                ),
                details={
                    "required_bytes": lock_info.required_bytes,
                    "free_bytes": free_bytes,
                    "path": str(storage),
                },
                hint="Free disk space or choose another storage folder in Settings.",
            )

        base_python_exe, base_python_dir, pbs_version = self.ensure_base_python(storage)
        pack_python = _pack_python_path(pack_dir, target_os)

        completed = False
        try:
            ctx.checkpoint()
            ctx.progress(0.05, f"Creating environment for {family}", "venv")
            self._run_subprocess(
                ctx,
                [
                    *uv_prefix,
                    "venv",
                    "--python",
                    str(base_python_exe),
                    "--no-project",
                    "--relocatable",
                    str(pack_dir),
                ],
                env=env,
                stage="venv",
                recent_logs=recent_logs,
            )

            ctx.checkpoint()
            ctx.progress(0.25, f"Syncing packages for {family}", "sync")
            self._run_subprocess(
                ctx,
                [
                    *uv_prefix,
                    "pip",
                    "sync",
                    "--python",
                    str(pack_python),
                    "--require-hashes",
                    "--no-build",
                    "--torch-backend",
                    lock_info.backend,
                    str(resolved_lock),
                ],
                env=env,
                stage="sync",
                recent_logs=recent_logs,
            )

            ctx.checkpoint()
            if worker_wheel is not None:
                ctx.progress(0.70, "Installing skald_worker wheel", "worker")
                offline_env = build_uv_env(storage, offline=True)
                self._run_subprocess(
                    ctx,
                    [
                        *uv_prefix,
                        "pip",
                        "install",
                        "--python",
                        str(pack_python),
                        "--offline",
                        "--no-index",
                        "--no-deps",
                        str(worker_wheel),
                    ],
                    env=offline_env,
                    stage="worker",
                    recent_logs=recent_logs,
                )
            else:
                ctx.progress(0.70, "Skipping worker wheel (none provided)", "worker")

            ctx.checkpoint()
            ctx.progress(0.85, f"Checking {family} environment", "check")
            custom_check = self._packs_source_dir / family / "check.py"
            if custom_check.is_file():
                check_cmd = [str(pack_python), str(custom_check)]
            else:
                check_cmd = [str(pack_python), "-m", "skald_worker", "--adapter", family, "--check"]
            check_lines = self._run_subprocess(
                ctx,
                check_cmd,
                env=os.environ,
                stage="check",
                recent_logs=recent_logs,
            )

            ctx.checkpoint()
            ctx.progress(0.95, f"Writing {PACK_META_FILENAME}", "finalize")
            uv_ver = self._probe_version([*uv_prefix, "--version"], env, "unknown")
            py_ver = self._probe_version([str(pack_python), "--version"], os.environ, pbs_version)
            worker_ver: str | None = None
            for line in reversed(check_lines):
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict) and isinstance(parsed.get("worker_version"), str):
                        worker_ver = parsed["worker_version"]
                        break
                except json.JSONDecodeError:
                    continue

            driver_info = CUDA_DRIVER_REQUIREMENTS.get(lock_info.backend, {}).get(target_os)
            meta = PackMetadata(
                family=family,
                os=target_os,
                accel=lock_info.accel,
                backend=lock_info.backend,
                lock_sha256=lock_info.sha256,
                lock_hash8=lock_info.hash8,
                packages=list(lock_info.packages),
                base_python_dir=str(base_python_dir),
                python_version=py_ver,
                uv_version=uv_ver,
                worker_version=worker_ver,
                min_nvidia_driver=driver_info["min_driver"] if driver_info else None,
                min_nvidia_driver_reason=driver_info["reason"] if driver_info else None,
                nvidia_driver_source=driver_info["source_url"] if driver_info else None,
                cuda_toolkit_driver=driver_info["toolkit_driver"] if driver_info else None,
                created_at=_utc_now_iso(),
            )
            atomic_write_json(pack_dir / PACK_META_FILENAME, meta.model_dump(mode="json"))
            completed = True
            ctx.progress(1.0, f"Pack {family} ready", "finalize")
            return {"pack_dir": str(pack_dir), "metadata": meta.model_dump(mode="json")}
        finally:
            if not completed and pack_dir.exists():
                _rmtree(pack_dir)

    def repair_job(
        self,
        ctx: JobContext,
        family: str,
        *,
        accel: str | None = None,
        lockfile: Path | None = None,
        worker_wheel: Path | None = None,
        offline: bool = False,
    ) -> dict[str, Any]:
        """Delete an existing or half-built pack folder and rebuild it from its lockfile."""
        storage = self.storage_root()
        target_os = _current_pack_os()
        resolved_lock = (
            self.resolve_lockfile(family, accel=accel, os_name=target_os)
            if lockfile is None
            else lockfile
        )
        lock_info = parse_lockfile(resolved_lock)
        pack_dir = self.pack_dir_for(family, lock_info, storage_dir=storage, os_name=target_os)
        if pack_dir.exists():
            ctx.log("info", f"Removing pack folder for repair: {pack_dir}")
            _rmtree(pack_dir)
        return self.install_job(
            ctx,
            family,
            accel=accel,
            lockfile=resolved_lock,
            worker_wheel=worker_wheel,
            offline=offline,
        )

    def remove(
        self,
        family: str,
        *,
        accel: str | None = None,
        storage_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Delete matching pack(s), unused `python/<ver>` copies, and clean orphaned uv cache."""
        storage = self.storage_root() if storage_dir is None else storage_dir
        p_root = packs_dir(storage)
        os_name = _current_pack_os()

        removed_dirs: list[Path] = []
        removed_packages: set[str] = set()

        half_built_pattern = (
            re.compile(
                rf"^{re.escape(family)}-{re.escape(os_name)}-{re.escape(accel)}-[0-9a-f]{{8}}$"
            )
            if accel is not None
            else re.compile(rf"^{re.escape(family)}-{re.escape(os_name)}-[a-z0-9]+-[0-9a-f]{{8}}$")
        )
        if p_root.is_dir():
            for entry in sorted(p_root.iterdir()):
                if not entry.is_dir():
                    continue
                meta = self.read_pack_metadata(entry)
                if meta is not None:
                    matches = meta.family == family and (accel is None or meta.accel == accel)
                else:
                    matches = bool(half_built_pattern.match(entry.name))
                if matches:
                    if meta is not None:
                        removed_packages.update(meta.packages)
                    _rmtree(entry)
                    removed_dirs.append(entry)

        remaining = self.list_packs(storage)
        used_python_dirs = {
            os.path.normcase(os.path.abspath(m.base_python_dir)) for m in remaining.values()
        }
        removed_pythons: list[Path] = []
        py_root = python_dir(storage)
        if py_root.is_dir():
            for entry in sorted(py_root.iterdir()):
                if (
                    entry.is_dir()
                    and os.path.normcase(os.path.abspath(entry)) not in used_python_dirs
                ):
                    _rmtree(entry)
                    removed_pythons.append(entry)

        cache_cleaned: str = "none"
        cache_dir = uv_cache_dir(storage)
        if removed_dirs and cache_dir.exists():
            uv_prefix = self.uv_command_prefix()
            env = build_uv_env(storage)
            if not remaining:
                self._run_cache_clean(uv_prefix, [], env)
                cache_cleaned = "all"
            else:
                keep_packages: set[str] = set()
                for meta in remaining.values():
                    keep_packages.update(meta.packages)
                orphaned = sorted(removed_packages - keep_packages)
                if orphaned:
                    self._run_cache_clean(uv_prefix, orphaned, env)
                    cache_cleaned = "packages"

        return {
            "removed_packs": [str(p) for p in removed_dirs],
            "removed_python_dirs": [str(p) for p in removed_pythons],
            "cache_cleaned": cache_cleaned,
        }

    def _run_cache_clean(
        self, uv_prefix: Sequence[str], packages: Sequence[str], env: Mapping[str, str]
    ) -> None:
        cmd = [*uv_prefix, "cache", "clean", *packages]
        subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(env),
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
