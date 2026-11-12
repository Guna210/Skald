"""Unit tests for scripts/fetch_deps.py using stdlib unittest only."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_deps  # noqa: E402


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_targz_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in entries:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


class TestFetchDeps(unittest.TestCase):
    def test_detect_platform(self) -> None:
        self.assertEqual(fetch_deps.detect_platform("Windows", "AMD64"), "win64")
        self.assertEqual(fetch_deps.detect_platform("Windows", "x86_64"), "win64")
        self.assertEqual(fetch_deps.detect_platform("Linux", "x86_64"), "linux64")
        self.assertEqual(fetch_deps.detect_platform("Linux", "amd64"), "linux64")
        with self.assertRaises(RuntimeError):
            fetch_deps.detect_platform("Darwin", "arm64")
        with self.assertRaises(RuntimeError):
            fetch_deps.detect_platform("Linux", "aarch64")

    def test_mirror_first_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "tool.tar.gz"

            with mock.patch.object(fetch_deps, "download_file") as dl:
                used = fetch_deps.download_with_fallback(
                    "https://mirror.example/tool.tar.gz",
                    "https://source.example/tool.tar.gz",
                    dest,
                )
                self.assertEqual(used, "https://mirror.example/tool.tar.gz")
                dl.assert_called_once_with("https://mirror.example/tool.tar.gz", dest)

            calls: list[str] = []

            def fail_mirror(url: str, target: Path, timeout: int = 120) -> None:
                calls.append(url)
                if "mirror" in url:
                    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
                target.write_bytes(b"ok")

            with mock.patch.object(fetch_deps, "download_file", side_effect=fail_mirror):
                used = fetch_deps.download_with_fallback(
                    "https://mirror.example/tool.tar.gz",
                    "https://source.example/tool.tar.gz",
                    dest,
                )
            self.assertEqual(used, "https://source.example/tool.tar.gz")
            self.assertEqual(
                calls,
                ["https://mirror.example/tool.tar.gz", "https://source.example/tool.tar.gz"],
            )

            def fail_urlerror(url: str, target: Path, timeout: int = 120) -> None:
                if "mirror" in url:
                    raise urllib.error.URLError("dns error")
                target.write_bytes(b"ok")

            with mock.patch.object(fetch_deps, "download_file", side_effect=fail_urlerror):
                used = fetch_deps.download_with_fallback(
                    "https://mirror.example/tool.tar.gz",
                    "https://source.example/tool.tar.gz",
                    dest,
                )
            self.assertEqual(used, "https://source.example/tool.tar.gz")

    def test_checksum_mismatch_deletes_archive_and_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lockfile = root / "deps.lock.json"
            vendor_dir = root / "vendor"
            lock_data = {
                "uv": {
                    "version": "1.0.0",
                    "source_url": "https://source.example/uv",
                    "license": "MIT",
                    "version_args": ["--version"],
                    "assets": {
                        "linux64": {
                            "file": "uv.tar.gz",
                            "url": "https://source.example/uv.tar.gz",
                            "mirror_url": "https://mirror.example/uv.tar.gz",
                            "sha256": "0" * 64,
                            "bin": "uv",
                        }
                    },
                }
            }
            lockfile.write_text(json.dumps(lock_data), encoding="utf-8")

            def fake_dl(_url: str, dest: Path, timeout: int = 120) -> None:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"corrupted-payload")

            with (
                mock.patch.object(fetch_deps, "detect_platform", return_value="linux64"),
                mock.patch.object(fetch_deps, "download_file", side_effect=fake_dl),
            ):
                rc = fetch_deps.main(["--lockfile", str(lockfile), "--vendor-dir", str(vendor_dir)])

            self.assertEqual(rc, 1)
            self.assertFalse((vendor_dir / ".downloads" / "uv.tar.gz").exists())
            self.assertFalse((vendor_dir / "uv" / "linux64").exists())

    def test_path_traversal_rejected_zip_and_tar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.txt"

            bad_zip_traversal = root / "traversal.zip"
            bad_zip_traversal.write_bytes(_make_zip_bytes([("../outside.txt", b"pwn")]))
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_zip_traversal, root / "dest1", "bin/tool")
            self.assertFalse(outside.exists())

            bad_zip_abs = root / "abs.zip"
            bad_zip_abs.write_bytes(_make_zip_bytes([("/abs.txt", b"pwn")]))
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_zip_abs, root / "dest2", "bin/tool")

            bad_zip_sym = root / "sym.zip"
            with zipfile.ZipFile(bad_zip_sym, "w") as zf:
                zi = zipfile.ZipInfo("link")
                zi.external_attr = 0o120777 << 16
                zf.writestr(zi, "../outside.txt")
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_zip_sym, root / "dest3", "bin/tool")

            bad_zip_backslash = root / "backslash.zip"
            bad_zip_backslash.write_bytes(_make_zip_bytes([("..\\outside.txt", b"pwn")]))
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_zip_backslash, root / "dest3b", "bin/tool")

            bad_zip_drive = root / "drive.zip"
            bad_zip_drive.write_bytes(_make_zip_bytes([("C:\\outside.txt", b"pwn")]))
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_zip_drive, root / "dest3c", "bin/tool")

            bad_tar_traversal = root / "traversal.tar.gz"
            bad_tar_traversal.write_bytes(_make_targz_bytes([("../outside.txt", b"pwn")]))
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_tar_traversal, root / "dest4", "bin/tool")
            self.assertFalse(outside.exists())

            bad_tar_sym = root / "sym.tar.gz"
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                sym = tarfile.TarInfo("sub/escape")
                sym.type = tarfile.SYMTYPE
                sym.linkname = "../../outside.txt"
                tf.addfile(sym)
            bad_tar_sym.write_bytes(buf.getvalue())
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_tar_sym, root / "dest5", "bin/tool")

            bad_tar_abs_sym = root / "abs_sym.tar.gz"
            buf2 = io.BytesIO()
            with tarfile.open(fileobj=buf2, mode="w:gz") as tf:
                sym = tarfile.TarInfo("escape")
                sym.type = tarfile.SYMTYPE
                sym.linkname = "/etc/passwd"
                tf.addfile(sym)
            bad_tar_abs_sym.write_bytes(buf2.getvalue())
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_tar_abs_sym, root / "dest6", "bin/tool")

            bad_tar_hardlink = root / "hardlink.tar.gz"
            buf3 = io.BytesIO()
            with tarfile.open(fileobj=buf3, mode="w:gz") as tf:
                lnk = tarfile.TarInfo("escape")
                lnk.type = tarfile.LNKTYPE
                lnk.linkname = "../outside.txt"
                tf.addfile(lnk)
            bad_tar_hardlink.write_bytes(buf3.getvalue())
            with self.assertRaises(ValueError):
                fetch_deps.safe_extract(bad_tar_hardlink, root / "dest7", "bin/tool")

    def test_tar_uses_data_filter_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "uv.tar.gz"
            archive.write_bytes(_make_targz_bytes([("uv", b"bin")]))
            dest = root / "dest"

            extract_calls: list[dict[str, object]] = []

            class FakeTar:
                def __enter__(self) -> "FakeTar":
                    return self

                def __exit__(self, *args: object) -> None:
                    return None

                def getmembers(self) -> list[tarfile.TarInfo]:
                    info = tarfile.TarInfo("uv")
                    info.size = 3
                    return [info]

                def extractall(self, path: Path, **kwargs: object) -> None:
                    extract_calls.append(kwargs)
                    (Path(path) / "uv").write_bytes(b"bin")

            with (
                mock.patch.object(fetch_deps.tarfile, "open", return_value=FakeTar()),
                mock.patch.object(fetch_deps.tarfile, "data_filter", object(), create=True),
            ):
                fetch_deps.safe_extract(archive, dest, "uv")

            self.assertEqual(extract_calls, [{"filter": "data"}])
            self.assertEqual((dest / "uv").read_bytes(), b"bin")

    def test_noop_skip_and_tamper_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lockfile = root / "deps.lock.json"
            vendor_dir = root / "vendor"
            good_payload = b"#!/bin/sh\necho uv 0.13.8\n"
            archive_bytes = _make_targz_bytes([("uv-x86_64/uv", good_payload)])
            expected_sha = _sha256_bytes(archive_bytes)

            lock_data = {
                "uv": {
                    "version": "0.13.8",
                    "source_url": "https://source.example/uv",
                    "license": "MIT",
                    "version_args": ["--version"],
                    "assets": {
                        "linux64": {
                            "file": "uv.tar.gz",
                            "url": "https://source.example/uv.tar.gz",
                            "mirror_url": "https://mirror.example/uv.tar.gz",
                            "sha256": expected_sha,
                            "bin": "uv",
                        }
                    },
                }
            }
            lockfile.write_text(json.dumps(lock_data), encoding="utf-8")

            dl_count = 0

            def fake_dl(_url: str, dest: Path, timeout: int = 120) -> None:
                nonlocal dl_count
                dl_count += 1
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive_bytes)

            fake_proc = mock.Mock(stdout="uv 0.13.8\n", stderr="")
            with (
                mock.patch.object(fetch_deps, "detect_platform", return_value="linux64"),
                mock.patch.object(fetch_deps, "download_file", side_effect=fake_dl),
                mock.patch.object(fetch_deps.subprocess, "run", return_value=fake_proc),
            ):
                # 1. Fresh install downloads once.
                rc1 = fetch_deps.main(["--lockfile", str(lockfile), "--vendor-dir", str(vendor_dir)])
                self.assertEqual(rc1, 0)
                self.assertEqual(dl_count, 1)
                installed_bin = vendor_dir / "uv" / "linux64" / "uv"
                self.assertEqual(installed_bin.read_bytes(), good_payload)

                # 2. Second run is a no-op.
                rc2 = fetch_deps.main(["--lockfile", str(lockfile), "--vendor-dir", str(vendor_dir)])
                self.assertEqual(rc2, 0)
                self.assertEqual(dl_count, 1)

                # 3. Flip 1 byte in cached archive -> triggers re-download.
                cached = vendor_dir / ".downloads" / "uv.tar.gz"
                tampered = bytearray(cached.read_bytes())
                tampered[0] ^= 0xFF
                cached.write_bytes(bytes(tampered))

                rc3 = fetch_deps.main(["--lockfile", str(lockfile), "--vendor-dir", str(vendor_dir)])
                self.assertEqual(rc3, 0)
                self.assertEqual(dl_count, 2)
                self.assertEqual(_sha256_bytes(cached.read_bytes()), expected_sha)

                # 4. Flip 1 byte in installed binary -> triggers re-install from valid cache.
                bin_bytes = bytearray(installed_bin.read_bytes())
                bin_bytes[0] ^= 0xFF
                installed_bin.write_bytes(bytes(bin_bytes))

                rc4 = fetch_deps.main(["--lockfile", str(lockfile), "--vendor-dir", str(vendor_dir)])
                self.assertEqual(rc4, 0)
                self.assertEqual(dl_count, 2)
                self.assertEqual(installed_bin.read_bytes(), good_payload)

    def test_wrapper_dir_unwrap_and_flat_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            wrapped_tar = root / "ffmpeg.tar.gz"
            wrapped_tar.write_bytes(
                _make_targz_bytes(
                    [
                        ("ffmpeg-n9.0/bin/ffmpeg", b"ffmpeg-bin"),
                        ("ffmpeg-n9.0/LICENSE.txt", b"LGPL"),
                    ]
                )
            )
            dest_tar = root / "vendor" / "ffmpeg" / "linux64"
            fetch_deps.safe_extract(wrapped_tar, dest_tar, "bin/ffmpeg")
            self.assertEqual((dest_tar / "bin" / "ffmpeg").read_bytes(), b"ffmpeg-bin")
            self.assertEqual((dest_tar / "LICENSE.txt").read_bytes(), b"LGPL")
            self.assertFalse((dest_tar / "ffmpeg-n9.0").exists())

            flat_zip = root / "uv.zip"
            flat_zip.write_bytes(_make_zip_bytes([("uv.exe", b"uv-win"), ("uvx.exe", b"uvx-win")]))
            dest_zip = root / "vendor" / "uv" / "win64"
            fetch_deps.safe_extract(flat_zip, dest_zip, "uv.exe")
            self.assertEqual((dest_zip / "uv.exe").read_bytes(), b"uv-win")
            self.assertEqual((dest_zip / "uvx.exe").read_bytes(), b"uvx-win")


if __name__ == "__main__":
    unittest.main()
