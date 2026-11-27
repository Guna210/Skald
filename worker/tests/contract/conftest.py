"""Fixtures and subprocess JSON-RPC client for the V3 worker contract suite."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--adapter",
        action="store",
        default="fake",
        help="Worker adapter name to run the contract suite against (default: fake).",
    )
    parser.addoption(
        "--checkpoint-dir",
        action="store",
        default=None,
        help="Checkpoint directory path passed to worker.load (default: empty temp dir).",
    )
    parser.addoption(
        "--checkpoint-id",
        action="store",
        default="default",
        help="Checkpoint id passed to worker.load (default: default).",
    )
    parser.addoption(
        "--device",
        action="store",
        default=None,
        help="Device passed to worker.load (default: first entry in worker.hello device_options).",
    )


class WorkerClient:
    """Drives `python -m skald_worker --adapter <name>` over stdio with timeouts."""

    def __init__(self, adapter: str) -> None:
        self.adapter = adapter
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "skald_worker", "--adapter", adapter],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        assert self.proc.stderr is not None

        self._next_id = 1
        self._stdout_queue: queue.Queue[bytes | None] = queue.Queue()
        self._stderr_lines: list[bytes] = []
        self._raw_stdout_lines: list[bytes] = []
        self._stdout_parse_errors: list[str] = []

        self._stdout_thread = threading.Thread(
            target=self._read_stdout_loop,
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr_loop,
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout_loop(self) -> None:
        assert self.proc.stdout is not None
        try:
            while True:
                line = self.proc.stdout.readline()
                if line == b"":
                    break
                self._raw_stdout_lines.append(line)
                self._stdout_queue.put(line)
        finally:
            self._stdout_queue.put(None)

    def _read_stderr_loop(self) -> None:
        assert self.proc.stderr is not None
        while True:
            line = self.proc.stderr.readline()
            if line == b"":
                break
            self._stderr_lines.append(line)

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        assert self.proc.stdin is not None
        req_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        raw_req = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.proc.stdin.write(raw_req)
        self.proc.stdin.flush()

        while True:
            try:
                raw_line = self._stdout_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise TimeoutError(
                    f"Timed out waiting {timeout}s for response to {method!r} "
                    f"(stderr: {self.stderr_text()!r})"
                ) from exc

            if raw_line is None:
                raise EOFError(
                    f"Worker closed stdout before responding to {method!r} "
                    f"(returncode={self.proc.poll()}, stderr={self.stderr_text()!r})"
                )

            if raw_line.endswith(b"\r\n") or not raw_line.endswith(b"\n"):
                self._stdout_parse_errors.append(f"Invalid line ending: {raw_line!r}")
                raise AssertionError(f"Non-LF line ending on worker stdout: {raw_line!r}")

            try:
                msg = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._stdout_parse_errors.append(f"Invalid JSON-RPC line {raw_line!r}: {exc}")
                raise AssertionError(
                    f"Worker stdout emitted non-JSON-RPC line: {raw_line!r}"
                ) from exc

            if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
                self._stdout_parse_errors.append(f"Invalid JSON-RPC object: {msg!r}")
                raise AssertionError(f"Worker stdout line is not JSON-RPC 2.0: {msg!r}")

            if msg.get("id") == req_id:
                return msg

    def send_raw_line(self, raw_bytes: bytes) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(raw_bytes)
        self.proc.stdin.flush()

    def stderr_text(self) -> str:
        return b"".join(self._stderr_lines).decode("utf-8", errors="replace")

    def assert_all_stdout_valid_jsonrpc(self) -> None:
        assert not self._stdout_parse_errors, self._stdout_parse_errors
        for raw_line in self._raw_stdout_lines:
            assert raw_line.endswith(b"\n") and not raw_line.endswith(b"\r\n")
            parsed = json.loads(raw_line.decode("utf-8"))
            assert isinstance(parsed, dict)
            assert parsed.get("jsonrpc") == "2.0"

    def wait(self, timeout: float = 10.0) -> int:
        rc = self.proc.wait(timeout=timeout)
        self._stdout_thread.join(timeout=2.0)
        self._stderr_thread.join(timeout=2.0)
        return rc

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.wait(timeout=5.0)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                if self.proc.stdin and not self.proc.stdin.closed:
                    self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3.0)
        self._stdout_thread.join(timeout=2.0)
        self._stderr_thread.join(timeout=2.0)


@pytest.fixture(scope="session")
def adapter_name(pytestconfig: pytest.Config) -> str:
    return str(pytestconfig.getoption("--adapter"))


@pytest.fixture
def checkpoint_dir(pytestconfig: pytest.Config, tmp_path: Path) -> Path:
    opt = pytestconfig.getoption("--checkpoint-dir")
    if opt is not None:
        return Path(str(opt))
    cp_dir = tmp_path / "checkpoint"
    cp_dir.mkdir(parents=True, exist_ok=True)
    return cp_dir


@pytest.fixture(scope="session")
def checkpoint_id(pytestconfig: pytest.Config) -> str:
    return str(pytestconfig.getoption("--checkpoint-id"))


@pytest.fixture(scope="session")
def target_device(pytestconfig: pytest.Config) -> str | None:
    opt = pytestconfig.getoption("--device")
    return None if opt is None else str(opt)


@pytest.fixture
def worker_client(adapter_name: str) -> Iterator[WorkerClient]:
    client = WorkerClient(adapter_name)
    try:
        yield client
    finally:
        client.close()
