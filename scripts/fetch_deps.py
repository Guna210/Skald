"""Download, SHA-256 verify, and safely extract pinned build binaries into vendor/."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import ntpath
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

CHUNK_SIZE = 65536
DEFAULT_LOCKFILE = Path(__file__).resolve().with_name("deps.lock.json")
DEFAULT_VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor"
MARKER_NAME = ".installed.json"
USER_AGENT = "Skald-fetch-deps/1.0"


class ChecksumError(RuntimeError):
    """Raised when a downloaded archive does not match its expected SHA-256."""


def detect_platform(system: str | None = None, machine: str | None = None) -> str:
    sys_name = (system if system is not None else platform.system()).lower()
    arch = (machine if machine is not None else platform.machine()).lower()
    if sys_name == "windows" and arch in {"amd64", "x86_64", "x64"}:
        return "win64"
    if sys_name == "linux" and arch in {"x86_64", "amd64"}:
        return "linux64"
    raise RuntimeError(f"Unsupported platform: {sys_name} / {arch}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest.with_name(f"{dest.name}.part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, part_path.open("wb") as out:
            expected_len: int | None = None
            if hasattr(resp, "length"):
                raw_len = resp.length
                if isinstance(raw_len, int) and not isinstance(raw_len, bool) and raw_len >= 0:
                    expected_len = raw_len
            elif not getattr(resp, "chunked", False):
                headers = getattr(resp, "headers", None)
                if hasattr(headers, "get"):
                    te = headers.get("Transfer-Encoding")
                    if not (isinstance(te, str) and "chunked" in te.lower()):
                        raw_cl = headers.get("Content-Length")
                        if isinstance(raw_cl, int) and not isinstance(raw_cl, bool) and raw_cl >= 0:
                            expected_len = raw_cl
                        elif isinstance(raw_cl, str):
                            stripped = raw_cl.strip()
                            if stripped.isascii() and stripped.isdigit():
                                expected_len = int(stripped)

            bytes_written = 0
            while chunk := resp.read(CHUNK_SIZE):
                out.write(chunk)
                bytes_written += len(chunk)
        if expected_len is not None and bytes_written < expected_len:
            raise http.client.IncompleteRead(b"", expected_len - bytes_written)
        os.replace(part_path, dest)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def download_with_fallback(mirror_url: str | None, source_url: str, dest: Path) -> str:
    if mirror_url:
        try:
            download_file(mirror_url, dest)
            print(f"using mirror: {mirror_url}")
            return mirror_url
        except (
            http.client.HTTPException,
            urllib.error.URLError,
            urllib.error.HTTPError,
            OSError,
            TimeoutError,
        ) as exc:
            print(f"mirror unavailable ({exc}); falling back to source: {source_url}")
    download_file(source_url, dest)
    print(f"using source: {source_url}")
    return source_url


def validate_member_path(name: str) -> list[str]:
    if not name or "\x00" in name:
        raise ValueError(f"Invalid archive member path: {name!r}")
    if name.startswith(("/", "\\")):
        raise ValueError(f"Absolute archive member path rejected: {name!r}")
    drive, _ = ntpath.splitdrive(name)
    if drive or (len(name) >= 2 and name[1] == ":" and name[0].isalpha()):
        raise ValueError(f"Drive-prefixed archive member path rejected: {name!r}")
    parts = name.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        raise ValueError(f"Path traversal rejected in archive member: {name!r}")
    return [part for part in parts if part and part != "."]


def _check_within_root(target: Path, root: Path, raw_name: str) -> Path:
    try:
        resolved = target.resolve(strict=False)
    except RuntimeError as exc:
        raise ValueError(f"Symlink loop in archive member: {raw_name!r}") from exc
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"Archive member escapes staging directory: {raw_name!r}")
    return resolved


def _select_payload_dir(staging_root: Path, bin_rel: str, archive_name: str) -> Path:
    if (staging_root / bin_rel).exists():
        return staging_root
    top_entries = list(staging_root.iterdir())
    if len(top_entries) == 1 and top_entries[0].is_dir() and (top_entries[0] / bin_rel).exists():
        return top_entries[0]
    raise RuntimeError(f"Expected binary {bin_rel!r} not found in extracted archive {archive_name}")


def _replace_dir(src_dir: Path, dest_dir: Path) -> None:
    backup_dir: Path | None = None
    if dest_dir.exists():
        backup_dir = dest_dir.parent / f".old-{dest_dir.name}-{os.getpid()}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        os.replace(dest_dir, backup_dir)
    try:
        shutil.move(str(src_dir), str(dest_dir))
    except Exception:
        if backup_dir is not None and backup_dir.exists() and not dest_dir.exists():
            os.replace(backup_dir, dest_dir)
        raise
    else:
        if backup_dir is not None and backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)


def safe_extract(archive_path: Path, dest_dir: Path, bin_rel: str) -> None:
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".tmp-{dest_dir.name}-", dir=dest_dir.parent))
    try:
        resolved_root = staging_root.resolve()
        if archive_path.name.lower().endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    rel_parts = validate_member_path(info.filename)
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError(f"Symlink not allowed in zip archive: {info.filename!r}")
                    target = resolved_root.joinpath(*rel_parts) if rel_parts else resolved_root
                    _check_within_root(target, resolved_root, info.filename)
                zf.extractall(staging_root)
        else:
            if not hasattr(tarfile, "data_filter"):
                raise RuntimeError("fetch_deps.py needs Python 3.12 or newer")
            with tarfile.open(archive_path, "r:*") as tf:
                tf.extractall(staging_root, filter="data")

        payload_dir = _select_payload_dir(staging_root, bin_rel, archive_path.name)
        _replace_dir(payload_dir, dest_dir)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)


def ensure_executable(bin_path: Path) -> None:
    if os.name == "nt":
        return
    exec_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    non_exec_suffixes = {".txt", ".json", ".so", ".dll", ".dylib", ".a", ".lib", ".h", ".py"}
    resolved_bin = bin_path.resolve()
    if resolved_bin.is_file():
        resolved_bin.chmod(resolved_bin.stat().st_mode | exec_bits)
    for sibling in bin_path.parent.iterdir():
        if sibling.is_symlink() or not sibling.is_file():
            continue
        if sibling.suffix.lower() in non_exec_suffixes or ".so." in sibling.name:
            continue
        sibling.chmod(sibling.stat().st_mode | exec_bits)


def _read_marker(marker_path: Path) -> dict[str, Any] | None:
    if not marker_path.is_file():
        return None
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_marker(marker_path: Path, payload: dict[str, str]) -> None:
    tmp_path = marker_path.with_name(f"{marker_path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, marker_path)


def ensure_tool(name: str, tool: dict[str, Any], target_platform: str, vendor_dir: Path) -> Path:
    assets = tool.get("assets", {})
    if target_platform not in assets:
        raise RuntimeError(f"Tool {name!r} has no asset for platform {target_platform!r}")
    asset = assets[target_platform]
    expected_sha = asset["sha256"].lower()
    bin_rel = asset["bin"]

    downloads_dir = vendor_dir / ".downloads"
    archive_path = downloads_dir / asset["file"]
    dest_dir = vendor_dir / name / target_platform
    bin_path = dest_dir / bin_rel
    marker_path = dest_dir / MARKER_NAME

    cache_tampered = False
    if archive_path.is_file():
        cached_sha = sha256_file(archive_path)
        if cached_sha != expected_sha:
            print(
                f"{name}: warning: cached archive {archive_path} failed SHA-256 check "
                f"(expected {expected_sha}, got {cached_sha}); removing and re-downloading",
                file=sys.stderr,
            )
            archive_path.unlink()
            cache_tampered = True

    if not cache_tampered:
        marker = _read_marker(marker_path)
        if (
            marker is not None
            and marker.get("file") == asset["file"]
            and marker.get("version") == tool["version"]
            and marker.get("sha256") == expected_sha
            and marker.get("bin") == bin_rel
            and bin_path.is_file()
            and sha256_file(bin_path) == marker.get("bin_sha256")
        ):
            print(f"{name}: up to date ({dest_dir}), skipping")
            return bin_path

    if not archive_path.is_file():
        download_with_fallback(asset.get("mirror_url"), asset["url"], archive_path)
        actual_sha = sha256_file(archive_path)
        if actual_sha != expected_sha:
            archive_path.unlink(missing_ok=True)
            raise ChecksumError(
                f"{name}: SHA-256 mismatch for {asset['file']} "
                f"(expected {expected_sha}, got {actual_sha})"
            )
        print(f"{name}: verified SHA-256 ({expected_sha})")

    safe_extract(archive_path, dest_dir, bin_rel)
    ensure_executable(bin_path)
    _write_marker(
        marker_path,
        {
            "file": asset["file"],
            "version": tool["version"],
            "sha256": expected_sha,
            "bin": bin_rel,
            "bin_sha256": sha256_file(bin_path),
        },
    )
    print(f"{name}: installed to {dest_dir}")
    return bin_path


def verify_binary(name: str, bin_path: Path, version_args: list[str]) -> str:
    res = subprocess.run(
        [str(bin_path), *version_args],
        check=True,
        capture_output=True,
        text=True,
    )
    output = (res.stdout or res.stderr).strip()
    print(f"--- {name} {' '.join(version_args)} ---")
    print(output)
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and verify pinned binaries into vendor/.")
    parser.add_argument(
        "--platform",
        choices=("win64", "linux64"),
        default=None,
        help="Target platform (default: auto-detect host).",
    )
    parser.add_argument(
        "--lockfile",
        type=Path,
        default=DEFAULT_LOCKFILE,
        help="Path to deps.lock.json.",
    )
    parser.add_argument(
        "--vendor-dir",
        type=Path,
        default=DEFAULT_VENDOR_DIR,
        help="Target vendor directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if not hasattr(tarfile, "data_filter"):
        print("fetch_deps.py needs Python 3.12 or newer", file=sys.stderr)
        return 1
    args = parse_args(argv)
    try:
        host_platform = detect_platform()
    except RuntimeError as exc:
        if args.platform is None:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        host_platform = None
    target_platform = args.platform or host_platform
    assert target_platform is not None

    lock_data = json.loads(args.lockfile.read_text(encoding="utf-8"))
    installed: list[tuple[str, Path, list[str]]] = []
    try:
        for name, tool in lock_data.items():
            bin_path = ensure_tool(name, tool, target_platform, args.vendor_dir)
            installed.append((name, bin_path, list(tool.get("version_args", ["--version"]))))
    except ChecksumError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if target_platform == host_platform:
        for name, bin_path, version_args in installed:
            verify_binary(name, bin_path, version_args)
    else:
        print(f"cross-platform fetch ({target_platform}); skipping host binary execution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
