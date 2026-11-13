"""Tests for skald_core.net HTTP helper and verified resumable downloader."""

from __future__ import annotations

import hashlib
import http.server
import os
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from skald_core import __version__, net
from skald_core.net import DownloadCancelled, download, get_json, get_text
from skald_core.rpc import SkaldError

PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@pytest.fixture(autouse=True)
def _clear_proxy_env_and_speed_up_retries(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Clear ambient cloud proxy vars and set zero backoff by default for fast tests."""
    for var in PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    if request.node.name != "test_default_constants":
        monkeypatch.setattr(net, "BACKOFF_SECONDS", 0.0)


@contextmanager
def _run_server(
    handler_cls: type[http.server.BaseHTTPRequestHandler],
) -> Iterator[tuple[http.server.ThreadingHTTPServer, str]]:
    class _QuietServer(http.server.ThreadingHTTPServer):
        daemon_threads = True

    server = _QuietServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_default_constants() -> None:
    assert net.CONNECT_TIMEOUT == 10.0
    assert net.READ_TIMEOUT == 60.0
    assert net.MAX_RETRIES == 2
    assert net.BACKOFF_SECONDS == 1.0
    assert net.user_agent() == f"Skald/{__version__}"


def test_get_text_and_json_and_user_agent() -> None:
    seen_user_agents: list[str | None] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            seen_user_agents.append(self.headers.get("User-Agent"))
            if self.path == "/text":
                body = "Halló, Skáld! — café".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/json":
                body = b'{"ok": true, "items": [1, 2, 3]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/bad-json":
                body = b"{not-json"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    with _run_server(Handler) as (_, base_url):
        assert get_text(f"{base_url}/text") == "Halló, Skáld! — café"
        assert get_json(f"{base_url}/json") == {"ok": True, "items": [1, 2, 3]}
        with pytest.raises(SkaldError) as exc_info:
            get_json(f"{base_url}/bad-json")
        assert exc_info.value.kind == "http_error"

    assert seen_user_agents == [f"Skald/{__version__}"] * 3


def test_retries_on_5xx_and_backoff_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    sleep_calls: list[float] = []
    monkeypatch.setattr(net, "BACKOFF_SECONDS", 0.5)
    monkeypatch.setattr(time, "sleep", sleep_calls.append)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            nonlocal attempts
            attempts += 1
            if self.path == "/flaky" and attempts < 3:
                self.send_response(503)
                self.end_headers()
                return
            if self.path == "/always-500":
                self.send_response(500)
                self.end_headers()
                return
            body = b"recovered"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with _run_server(Handler) as (_, base_url):
        assert get_text(f"{base_url}/flaky") == "recovered"
        assert attempts == 3
        assert sleep_calls == [0.5, 1.0]

        attempts = 0
        sleep_calls.clear()
        with pytest.raises(SkaldError) as exc_info:
            get_text(f"{base_url}/always-500")
        assert exc_info.value.kind == "http_error"
        assert attempts == 3
        assert sleep_calls == [0.5, 1.0]


def test_4xx_never_retries_and_404_kind() -> None:
    calls: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            calls.append(self.path)
            if self.path == "/missing":
                self.send_response(404)
            else:
                self.send_response(403)
            self.end_headers()

    with _run_server(Handler) as (_, base_url):
        with pytest.raises(SkaldError) as exc_404:
            get_text(f"{base_url}/missing")
        assert exc_404.value.kind == "http_not_found"

        with pytest.raises(SkaldError) as exc_403:
            get_text(f"{base_url}/forbidden")
        assert exc_403.value.kind == "http_error"

    assert calls == ["/missing", "/forbidden"]


def test_offline_closed_port_retries_and_raises() -> None:
    closed_port = _unused_local_port()
    with pytest.raises(SkaldError) as exc_info:
        get_text(f"http://127.0.0.1:{closed_port}/status")
    assert exc_info.value.kind == "offline"


def test_https_proxy_env_is_honoured_and_proxy_failure_is_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_requests: list[str] = []

    class ProxyHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_CONNECT(self) -> None:
            seen_requests.append(f"CONNECT {self.path}")
            self.send_response(502, "Bad Gateway")
            self.end_headers()

        def do_GET(self) -> None:
            seen_requests.append(f"GET {self.path}")
            body = b"proxied-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with _run_server(ProxyHandler) as (_, proxy_url):
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        monkeypatch.setenv("HTTPS_PROXY", proxy_url)

        assert get_text("http://example.invalid/ping") == "proxied-ok"
        with pytest.raises(SkaldError) as exc_info:
            get_text("https://example.invalid/secure", retries=0)
        assert exc_info.value.kind == "offline"

    assert "GET http://example.invalid/ping" in seen_requests
    assert "CONNECT example.invalid:443" in seen_requests


def test_timeout_on_stalled_headers_and_stalled_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release_stall = threading.Event()
    attempts = 0
    monkeypatch.setattr(net, "CONNECT_TIMEOUT", 1.0)
    monkeypatch.setattr(net, "READ_TIMEOUT", 0.1)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            nonlocal attempts
            attempts += 1
            if self.path == "/stall-headers":
                release_stall.wait(timeout=2.0)
                return
            if self.path == "/stall-body":
                self.send_response(200)
                self.send_header("Content-Length", "1000")
                self.end_headers()
                self.wfile.write(b"12345")
                self.wfile.flush()
                release_stall.wait(timeout=2.0)

    with _run_server(Handler) as (_, base_url):
        try:
            with pytest.raises(SkaldError) as exc_headers:
                get_text(f"{base_url}/stall-headers")
            assert exc_headers.value.kind == "timeout"
            assert attempts == 3

            attempts = 0
            dest = tmp_path / "stalled.bin"
            with pytest.raises(SkaldError) as exc_body:
                download(
                    f"{base_url}/stall-body",
                    dest,
                    sha256="0" * 64,
                    size=1000,
                )
            assert exc_body.value.kind == "timeout"
            assert attempts == 3
            assert not dest.exists()
        finally:
            release_stall.set()


def test_download_happy_path_creates_parent_and_reports_progress(tmp_path: Path) -> None:
    payload = os.urandom(150_000)
    expected_sha = hashlib.sha256(payload).hexdigest()
    progress: list[tuple[int, int]] = []
    seen_ua: list[str | None] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            seen_ua.append(self.headers.get("User-Agent"))
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    dest = tmp_path / "nested" / "dir" / "model.bin"
    with _run_server(Handler) as (_, base_url):
        result = download(
            f"{base_url}/model.bin",
            dest,
            sha256=expected_sha.upper(),
            size=len(payload),
            progress_cb=lambda done, total: progress.append((done, total)),
        )

    assert result == dest
    assert dest.read_bytes() == payload
    assert not dest.with_name("model.bin.part").exists()
    assert seen_ua == [f"Skald/{__version__}"]
    assert progress
    assert progress[-1] == (len(payload), len(payload))
    assert [done for done, _ in progress] == sorted(done for done, _ in progress)


def test_download_resumes_from_part_and_retries_mid_body_drop(tmp_path: Path) -> None:
    payload = b"ABCD" * 35_000  # 140,000 bytes (> DOWNLOAD_CHUNK_SIZE)
    expected_sha = hashlib.sha256(payload).hexdigest()
    range_headers: list[str | None] = []
    attempt_num = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            nonlocal attempt_num
            attempt_num += 1
            rng = self.headers.get("Range")
            range_headers.append(rng)

            start = 0
            if rng and rng.startswith("bytes=") and rng.endswith("-"):
                start = int(rng[len("bytes=") : -1])

            if attempt_num == 1:
                # Send >1 full chunk (80,000 bytes) then drop connection mid-body.
                remaining = len(payload) - start
                self.send_response(206 if start > 0 else 200)
                self.send_header("Content-Length", str(remaining))
                if start > 0:
                    self.send_header(
                        "Content-Range",
                        f"bytes {start}-{len(payload) - 1}/{len(payload)}",
                    )
                self.end_headers()
                self.wfile.write(payload[start : start + 80_000])
                self.wfile.flush()
                return

            body = payload[start:]
            if start > 0:
                self.send_response(206)
                self.send_header(
                    "Content-Range",
                    f"bytes {start}-{len(payload) - 1}/{len(payload)}",
                )
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    dest = tmp_path / "weights.safetensors"
    part = tmp_path / "weights.safetensors.part"
    part.write_bytes(payload[:300])

    with _run_server(Handler) as (_, base_url):
        download(f"{base_url}/weights", dest, sha256=expected_sha, size=len(payload))

    assert dest.read_bytes() == payload
    assert not part.exists()
    expected_resume = 300 + net.DOWNLOAD_CHUNK_SIZE
    assert range_headers == ["bytes=300-", f"bytes={expected_resume}-"]


def test_download_restarts_when_server_ignores_range_or_part_too_large(tmp_path: Path) -> None:
    payload = b"0123456789" * 100
    expected_sha = hashlib.sha256(payload).hexdigest()
    range_headers: list[str | None] = []

    class IgnoreRangeHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            range_headers.append(self.headers.get("Range"))
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    dest1 = tmp_path / "ignore_range.bin"
    dest1.with_name("ignore_range.bin.part").write_bytes(payload[:250])

    dest2 = tmp_path / "oversize_part.bin"
    dest2.with_name("oversize_part.bin.part").write_bytes(b"X" * (len(payload) + 50))

    with _run_server(IgnoreRangeHandler) as (_, base_url):
        download(f"{base_url}/file", dest1, sha256=expected_sha, size=len(payload))
        download(f"{base_url}/file", dest2, sha256=expected_sha, size=len(payload))

    assert dest1.read_bytes() == payload
    assert dest2.read_bytes() == payload
    assert range_headers == ["bytes=250-", None]


def test_download_part_already_exact_size_verifies_without_http(tmp_path: Path) -> None:
    payload = b"already-downloaded-payload"
    expected_sha = hashlib.sha256(payload).hexdigest()
    requests_seen = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            nonlocal requests_seen
            requests_seen += 1
            self.send_response(200)
            self.end_headers()

    with _run_server(Handler) as (_, base_url):
        good_dest = tmp_path / "good.bin"
        good_part = tmp_path / "good.bin.part"
        good_part.write_bytes(payload)
        progress: list[tuple[int, int]] = []

        download(
            f"{base_url}/good",
            good_dest,
            sha256=expected_sha,
            size=len(payload),
            progress_cb=lambda done, total: progress.append((done, total)),
        )
        assert good_dest.read_bytes() == payload
        assert not good_part.exists()
        assert progress == [(len(payload), len(payload))]
        assert requests_seen == 0

        bad_dest = tmp_path / "bad.bin"
        bad_part = tmp_path / "bad.bin.part"
        bad_part.write_bytes(b"X" * len(payload))
        with pytest.raises(SkaldError) as exc_info:
            download(f"{base_url}/bad", bad_dest, sha256=expected_sha, size=len(payload))
        assert exc_info.value.kind == "checksum_mismatch"
        assert not bad_part.exists()
        assert not bad_dest.exists()
        assert requests_seen == 0


def test_download_checksum_and_size_mismatch_delete_part(tmp_path: Path) -> None:
    real_payload = b"correct-bytes"
    real_sha = hashlib.sha256(real_payload).hexdigest()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/wrong-bytes":
                body = b"corrupt-bytes"
            else:
                body = b"short"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with _run_server(Handler) as (_, base_url):
        dest1 = tmp_path / "wrong_sha.bin"
        part1 = tmp_path / "wrong_sha.bin.part"
        with pytest.raises(SkaldError) as exc1:
            download(f"{base_url}/wrong-bytes", dest1, sha256=real_sha, size=len(real_payload))
        assert exc1.value.kind == "checksum_mismatch"
        assert not part1.exists()
        assert not dest1.exists()

        dest2 = tmp_path / "wrong_size.bin"
        part2 = tmp_path / "wrong_size.bin.part"
        with pytest.raises(SkaldError) as exc2:
            download(f"{base_url}/short", dest2, sha256=real_sha, size=len(real_payload))
        assert exc2.value.kind == "checksum_mismatch"
        assert not part2.exists()
        assert not dest2.exists()


def test_download_cancel_keeps_part_and_later_resumes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = b"Z" * 1024
    expected_sha = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(net, "DOWNLOAD_CHUNK_SIZE", 256)
    range_headers: list[str | None] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            rng = self.headers.get("Range")
            range_headers.append(rng)
            start = 0
            if rng and rng.startswith("bytes=") and rng.endswith("-"):
                start = int(rng[len("bytes=") : -1])
            body = payload[start:]
            if start > 0:
                self.send_response(206)
                self.send_header(
                    "Content-Range",
                    f"bytes {start}-{len(payload) - 1}/{len(payload)}",
                )
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            for offset in range(0, len(body), 256):
                self.wfile.write(body[offset : offset + 256])
                self.wfile.flush()

    dest = tmp_path / "cancelled.bin"
    part = tmp_path / "cancelled.bin.part"
    should_cancel = False

    def on_progress(done: int, total: int) -> None:
        nonlocal should_cancel
        if done >= 256:
            should_cancel = True

    with _run_server(Handler) as (_, base_url):
        with pytest.raises(DownloadCancelled) as exc_info:
            download(
                f"{base_url}/file",
                dest,
                sha256=expected_sha,
                size=len(payload),
                progress_cb=on_progress,
                cancel=lambda: should_cancel,
            )
        assert not isinstance(exc_info.value, SkaldError)
        assert part.exists()
        partial_len = part.stat().st_size
        assert 256 <= partial_len < len(payload)
        assert not dest.exists()

        # Resume after cancel; only the missing bytes should be requested.
        download(
            f"{base_url}/file",
            dest,
            sha256=expected_sha,
            size=len(payload),
            cancel=lambda: False,
        )

    assert dest.read_bytes() == payload
    assert not part.exists()
    assert range_headers == [None, f"bytes={partial_len}-"]


def test_download_500_raises_http_error_after_retries(tmp_path: Path) -> None:
    calls = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            nonlocal calls
            calls += 1
            self.send_response(502)
            self.end_headers()

    dest = tmp_path / "fail.bin"
    with _run_server(Handler) as (_, base_url):
        with pytest.raises(SkaldError) as exc_info:
            download(f"{base_url}/err", dest, sha256="0" * 64, size=10)
    assert exc_info.value.kind == "http_error"
    assert calls == 3
    assert not dest.exists()
