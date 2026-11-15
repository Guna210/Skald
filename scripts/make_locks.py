"""Regenerate and verify hash-locked engine pack lockfiles via bundled uv."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKS_DIR = REPO_ROOT / "packs"
DEFAULT_VENDOR_DIR = REPO_ROOT / "vendor"
DEFAULT_UV_CACHE_DIR = REPO_ROOT / ".cache" / "uv"

EXCLUDE_NEWER = "2026-11-13T00:00:00Z"
PYTHON_VERSION = "3.12"
CUSTOM_COMPILE_COMMAND = "python scripts/make_locks.py"

UV_BIN_BY_PLATFORM: dict[str, str] = {
    "win64": "uv.exe",
    "linux64": "uv",
}

UV_PLATFORM_BY_OS: dict[str, str] = {
    "linux": "x86_64-manylinux_2_28",
    "windows": "x86_64-pc-windows-msvc",
}

BACKEND_TO_ACCEL: dict[str, str] = {
    "cpu": "cpu",
    "cu126": "cu12",
}

# Per-OS measured cold-install free-space drop (docs/spikes/engine-packs.md section 3.4) x 1.2.
REQUIRED_BYTES_BY_OS_BACKEND: dict[tuple[str, str], int] = {
    ("linux", "cpu"): int(868 * 1_000_000 * 1.2),
    ("windows", "cpu"): int(623 * 1_000_000 * 1.2),
    ("linux", "cu126"): int(6669 * 1_000_000 * 1.2),
    ("windows", "cu126"): int(4326 * 1_000_000 * 1.2),
}

PYTORCH_INDEX_ALLOWLIST: frozenset[str] = frozenset({"torch", "triton"})
PYPI_HOSTS: frozenset[str] = frozenset({"pypi.org", "files.pythonhosted.org"})
PYTORCH_HOSTS: frozenset[str] = frozenset({"download.pytorch.org", "download-r2.pytorch.org"})

_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==")
_FROM_RE = re.compile(r"^\s*#\s*from\s+(\S+)\s*$")
_HASH_RE = re.compile(r"^\s*--hash=sha256:[0-9a-f]{64}\b")
_BACKENDS_HEADER_RE = re.compile(r"^\s*#\s*skald-backends:\s*(.+)$")


class LockValidationError(ValueError):
    """Raised when a generated or committed lockfile violates index or hash policy."""


def _normalize_pkg_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _detect_host_platform() -> str:
    sys_name = platform.system().lower()
    arch = platform.machine().lower()
    if sys_name == "windows" and arch in {"amd64", "x86_64", "x64"}:
        return "win64"
    if sys_name == "linux" and arch in {"x86_64", "amd64"}:
        return "linux64"
    raise RuntimeError(f"Unsupported platform: {sys_name} / {arch}")


def resolve_uv_binary(vendor_dir: Path | None = None) -> Path:
    root = DEFAULT_VENDOR_DIR if vendor_dir is None else vendor_dir
    plat = _detect_host_platform()
    return root / "uv" / plat / UV_BIN_BY_PLATFORM[plat]


def build_uv_env(
    uv_cache_dir: Path | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the clean uv environment keeping proxy/cert variables and stripping other UV_*."""
    source = os.environ if base_env is None else base_env
    env = {k: v for k, v in source.items() if not k.startswith("UV_")}
    cache_dir = DEFAULT_UV_CACHE_DIR if uv_cache_dir is None else uv_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    env.update(
        UV_NO_CONFIG="1",
        UV_CACHE_DIR=str(cache_dir),
        UV_LINK_MODE="hardlink",
        UV_PYTHON_DOWNLOADS="never",
        UV_SYSTEM_CERTS="1",
        UV_NO_PROGRESS="1",
    )
    return env


def parse_pack_backends(requirements_in: Path) -> list[str]:
    """Read `# skald-backends: ...` from requirements.in (default: cpu, cu126)."""
    for line in requirements_in.read_text(encoding="utf-8").splitlines():
        match = _BACKENDS_HEADER_RE.match(line)
        if match:
            backends = [item.strip() for item in match.group(1).split(",") if item.strip()]
            if not backends:
                raise LockValidationError(f"{requirements_in}: empty skald-backends header")
            for backend in backends:
                if backend not in BACKEND_TO_ACCEL:
                    raise LockValidationError(f"{requirements_in}: unsupported backend {backend!r}")
            return backends
    return ["cpu", "cu126"]


def lf_sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def validate_lock_content(
    text: str,
    allowlist: frozenset[str] = PYTORCH_INDEX_ALLOWLIST,
) -> None:
    """Ensure every pin has sha256 hashes, valid index provenance, and matches the allowlist."""
    normalized_allow = {_normalize_pkg_name(pkg) for pkg in allowlist}
    current_pkg: str | None = None
    has_hash = False
    index_url: str | None = None
    pin_count = 0

    def _finish_block() -> None:
        if current_pkg is None:
            return
        if not has_hash:
            raise LockValidationError(f"Package {current_pkg!r} is missing --hash=sha256")
        if not index_url:
            raise LockValidationError(f"Package {current_pkg!r} is missing '# from <index>'")
        host = (urlparse(index_url).hostname or "").lower()
        if host in PYTORCH_HOSTS:
            if current_pkg not in normalized_allow:
                raise LockValidationError(
                    f"Package {current_pkg!r} resolved from PyTorch index {index_url!r}, "
                    f"which is outside allowlist {sorted(normalized_allow)}"
                )
        elif host in PYPI_HOSTS:
            if current_pkg == "torch":
                raise LockValidationError(
                    f"Package 'torch' must resolve from PyTorch index, got {index_url!r}"
                )
        else:
            raise LockValidationError(
                f"Package {current_pkg!r} resolved from unexpected index {index_url!r}"
            )

    for raw_line in text.replace("\r\n", "\n").splitlines():
        pin_match = _PIN_RE.match(raw_line)
        if pin_match:
            _finish_block()
            current_pkg = _normalize_pkg_name(pin_match.group(1))
            has_hash = False
            index_url = None
            pin_count += 1
            continue
        if current_pkg is None:
            continue
        if _HASH_RE.match(raw_line):
            has_hash = True
            continue
        from_match = _FROM_RE.match(raw_line)
        if from_match:
            index_url = from_match.group(1)

    _finish_block()
    if pin_count == 0:
        raise LockValidationError("Lockfile contains no pinned packages")


def render_lock_text(compiled_text: str, os_name: str, backend: str) -> str:
    required_bytes = REQUIRED_BYTES_BY_OS_BACKEND[(os_name, backend)]
    header = f"# skald-backend: {backend}\n# skald-required-bytes: {required_bytes}\n"
    body = compiled_text.replace("\r\n", "\n")
    if not body.endswith("\n"):
        body += "\n"
    return header + body


def compile_lock(
    uv_bin: Path,
    requirements_in: Path,
    os_name: str,
    backend: str,
    *,
    env: Mapping[str, str],
    allowlist: frozenset[str] = PYTORCH_INDEX_ALLOWLIST,
) -> bytes:
    """Run uv pip compile for (os_name, backend), validate provenance, and return LF bytes."""
    with tempfile.TemporaryDirectory(prefix="skald-lock-") as tmp_dir:
        tmp_out = Path(tmp_dir) / "compiled.txt"
        cmd = [
            str(uv_bin),
            "pip",
            "compile",
            str(requirements_in),
            "--generate-hashes",
            "--only-binary",
            ":all:",
            "--python-version",
            PYTHON_VERSION,
            "--python-platform",
            UV_PLATFORM_BY_OS[os_name],
            "--torch-backend",
            backend,
            "--exclude-newer",
            EXCLUDE_NEWER,
            "--emit-index-annotation",
            "--custom-compile-command",
            CUSTOM_COMPILE_COMMAND,
            "--quiet",
            "-o",
            str(tmp_out),
        ]
        proc = subprocess.run(
            cmd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"uv pip compile failed for {requirements_in} ({os_name}/{backend}):\n"
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        compiled_text = tmp_out.read_text(encoding="utf-8")

    validate_lock_content(compiled_text, allowlist=allowlist)
    full_text = render_lock_text(compiled_text, os_name=os_name, backend=backend)
    return full_text.encode("utf-8")


def discover_packs(packs_dir: Path, pack_filter: str | None = None) -> list[Path]:
    if not packs_dir.is_dir():
        return []
    result: list[Path] = []
    for entry in sorted(packs_dir.iterdir()):
        if not entry.is_dir():
            continue
        if pack_filter is not None and entry.name != pack_filter:
            continue
        if (entry / "requirements.in").is_file():
            result.append(entry)
    return result


def process_packs(
    packs_dir: Path = DEFAULT_PACKS_DIR,
    *,
    check: bool = False,
    pack_filter: str | None = None,
    uv_bin: Path | None = None,
    uv_cache_dir: Path | None = None,
) -> int:
    uv_exe = resolve_uv_binary() if uv_bin is None else uv_bin
    if not uv_exe.is_file():
        print(f"error: uv binary not found at {uv_exe}", file=sys.stderr)
        return 1

    env = build_uv_env(uv_cache_dir=uv_cache_dir)
    pack_dirs = discover_packs(packs_dir, pack_filter=pack_filter)
    if not pack_dirs:
        print(f"error: no packs with requirements.in found in {packs_dir}", file=sys.stderr)
        return 1

    drifted: list[Path] = []
    for pack_dir in pack_dirs:
        req_in = pack_dir / "requirements.in"
        backends = parse_pack_backends(req_in)
        locks_dir = pack_dir / "locks"
        if not check:
            locks_dir.mkdir(parents=True, exist_ok=True)
        for backend in backends:
            accel = BACKEND_TO_ACCEL[backend]
            for os_name in UV_PLATFORM_BY_OS:
                target = locks_dir / f"{os_name}-{accel}.txt"
                generated = compile_lock(uv_exe, req_in, os_name, backend, env=env)
                if check:
                    if not target.is_file():
                        print(f"MISSING {target}", file=sys.stderr)
                        drifted.append(target)
                        continue
                    existing = target.read_bytes().replace(b"\r\n", b"\n")
                    if existing != generated:
                        print(f"DRIFT {target}", file=sys.stderr)
                        drifted.append(target)
                    else:
                        print(
                            f"OK {target.relative_to(packs_dir.parent)} ({lf_sha256(existing)[:8]})"
                        )
                else:
                    target.write_bytes(generated)
                    print(
                        f"WROTE {target.relative_to(packs_dir.parent)} ({lf_sha256(generated)[:8]})"
                    )

    if drifted:
        print(
            f"error: {len(drifted)} lockfile(s) out of date; run 'python scripts/make_locks.py'",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed lockfiles match fresh uv compile output (LF-normalised).",
    )
    parser.add_argument(
        "--pack",
        default=None,
        help="Process only the named pack directory under packs/.",
    )
    parser.add_argument(
        "--packs-dir",
        type=Path,
        default=DEFAULT_PACKS_DIR,
        help="Path to the packs directory.",
    )
    args = parser.parse_args(argv)
    return process_packs(
        packs_dir=args.packs_dir,
        check=args.check,
        pack_filter=args.pack,
    )


if __name__ == "__main__":
    raise SystemExit(main())
