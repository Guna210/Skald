"""Unit and subprocess integration tests for the JSON-RPC 2.0 stdio server."""

from __future__ import annotations

import io
import json
import logging
import math
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from skald_core.rpc import (
    APP_ERROR,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    RpcServer,
    SkaldError,
    configure_logging,
    notify,
)
from skald_core.rpc.server import close_managed_logging


class EchoParams(BaseModel):
    text: str
    count: int = Field(default=1, gt=0)


class EchoResult(BaseModel):
    echoed: str
    count: int


def _make_server(lines: list[str] | None = None) -> tuple[RpcServer, io.BytesIO]:
    raw = "".join(f"{line}\n" for line in (lines or [])).encode("utf-8")
    stdin = io.BytesIO(raw)
    stdout = io.BytesIO()
    return RpcServer(stdin=stdin, stdout=stdout), stdout


def _read_json_lines(buf: io.BytesIO) -> list[dict[str, Any]]:
    raw = buf.getvalue().decode("utf-8")
    return [json.loads(line) for line in raw.splitlines() if line]


def _assert_protocol_error_shape(resp: dict[str, Any], code: int) -> None:
    err = resp["error"]
    assert err["code"] == code
    assert set(err["data"].keys()) == {"kind", "details", "hint"}
    assert err["data"]["kind"] == "internal"
    assert err["data"]["hint"] is None


def test_dispatch_with_pydantic_models() -> None:
    server, _ = _make_server()

    def handle_echo(params: EchoParams) -> EchoResult:
        return EchoResult(echoed=params.text, count=params.count)

    server.register("test.echo", handle_echo, EchoParams, EchoResult)

    resp = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.echo",
                "params": {"text": "hello", "count": 3},
            }
        )
    )
    assert resp == {"jsonrpc": "2.0", "id": 1, "result": {"echoed": "hello", "count": 3}}


def test_dispatch_without_models_and_omitted_or_null_params() -> None:
    server, _ = _make_server()
    server.register("test.ping", lambda: {"pong": True})

    r1 = server.handle_line('{"jsonrpc":"2.0","id":"a","method":"test.ping"}')
    r2 = server.handle_line('{"jsonrpc":"2.0","id":"b","method":"test.ping","params":null}')
    r3 = server.handle_line('{"jsonrpc":"2.0","id":"c","method":"test.ping","params":{}}')
    assert r1 == {"jsonrpc": "2.0", "id": "a", "result": {"pong": True}}
    assert r2 == {"jsonrpc": "2.0", "id": "b", "result": {"pong": True}}
    assert r3 == {"jsonrpc": "2.0", "id": "c", "result": {"pong": True}}


def test_standard_error_parse_error() -> None:
    server, _ = _make_server()
    resp = server.handle_line("{not valid json")
    assert resp is not None
    assert resp["id"] is None
    _assert_protocol_error_shape(resp, PARSE_ERROR)


def test_deeply_nested_json_returns_parse_error() -> None:
    server, _ = _make_server()
    deep = ("[" * 10000) + ("]" * 10000)
    resp = server.handle_line(deep)
    assert resp is not None
    assert resp["id"] is None
    _assert_protocol_error_shape(resp, PARSE_ERROR)


def test_invalid_utf8_on_stdin_emits_parse_error_and_continues() -> None:
    stdin = io.BytesIO(b"\xff\xfe\n" + b'{"jsonrpc":"2.0","id":7,"method":"system.shutdown"}\n')
    stdout = io.BytesIO()
    server = RpcServer(stdin=stdin, stdout=stdout)
    server.serve()

    messages = _read_json_lines(stdout)
    assert len(messages) == 2
    assert messages[0]["id"] is None
    _assert_protocol_error_shape(messages[0], PARSE_ERROR)
    assert messages[1] == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}


@pytest.mark.parametrize(
    "raw_line",
    [
        '[{"jsonrpc":"2.0","id":1,"method":"system.shutdown"}]',
        "[]",
        "42",
        '"just a string"',
        '{"id":1,"method":"system.shutdown"}',
        '{"jsonrpc":"1.0","id":1,"method":"system.shutdown"}',
        '{"jsonrpc":"2.0","id":1}',
        '{"jsonrpc":"2.0","id":1,"method":123}',
        '{"jsonrpc":"2.0","id":true,"method":"system.shutdown"}',
        '{"jsonrpc":"2.0","id":[1],"method":"system.shutdown"}',
    ],
)
def test_standard_error_invalid_request_and_no_batches(raw_line: str) -> None:
    server, _ = _make_server()
    resp = server.handle_line(raw_line)
    assert resp is not None
    _assert_protocol_error_shape(resp, INVALID_REQUEST)
    if raw_line.startswith("["):
        assert resp["id"] is None


def test_standard_error_method_not_found() -> None:
    server, _ = _make_server()
    resp = server.handle_line('{"jsonrpc":"2.0","id":9,"method":"no.such.method"}')
    assert resp is not None
    assert resp["id"] == 9
    _assert_protocol_error_shape(resp, METHOD_NOT_FOUND)


def test_standard_error_invalid_params_with_pydantic_details() -> None:
    server, _ = _make_server()
    server.register("test.echo", lambda p: EchoResult(echoed=p.text, count=p.count), EchoParams)

    resp = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "test.echo",
                "params": {"count": 0},
            }
        )
    )
    assert resp is not None
    assert resp["id"] == 2
    _assert_protocol_error_shape(resp, INVALID_PARAMS)
    details = resp["error"]["data"]["details"]
    assert isinstance(details, list)
    assert len(details) >= 2
    locs = {tuple(item["loc"]) for item in details}
    assert ("text",) in locs
    assert ("count",) in locs


def test_array_params_rejected_with_invalid_params() -> None:
    server, _ = _make_server()
    server.register("test.echo", lambda p: EchoResult(echoed=p.text, count=p.count), EchoParams)
    server.register("test.ping", lambda: {"ok": True})

    r1 = server.handle_line('{"jsonrpc":"2.0","id":1,"method":"test.echo","params":["hi",1]}')
    r2 = server.handle_line('{"jsonrpc":"2.0","id":2,"method":"test.ping","params":[1,2]}')
    assert r1 is not None
    assert r2 is not None
    _assert_protocol_error_shape(r1, INVALID_PARAMS)
    _assert_protocol_error_shape(r2, INVALID_PARAMS)


def test_standard_error_invalid_params_for_no_param_method() -> None:
    server, _ = _make_server()
    server.register("test.ping", lambda: {"ok": True})
    resp = server.handle_line('{"jsonrpc":"2.0","id":3,"method":"test.ping","params":{"x":1}}')
    assert resp is not None
    _assert_protocol_error_shape(resp, INVALID_PARAMS)
    assert resp["error"]["data"]["details"]


def test_standard_error_internal_error() -> None:
    server, _ = _make_server()

    def boom() -> dict[str, Any]:
        raise RuntimeError("unexpected failure")

    server.register("test.boom", boom)
    resp = server.handle_line('{"jsonrpc":"2.0","id":4,"method":"test.boom"}')
    assert resp is not None
    assert resp["id"] == 4
    _assert_protocol_error_shape(resp, INTERNAL_ERROR)
    assert "unexpected failure" in resp["error"]["data"]["details"]


def test_standard_error_internal_error_on_bad_result_model() -> None:
    server, _ = _make_server()
    server.register("test.bad_result", lambda: {"wrong": "shape"}, None, EchoResult)
    resp = server.handle_line('{"jsonrpc":"2.0","id":5,"method":"test.bad_result"}')
    assert resp is not None
    _assert_protocol_error_shape(resp, INTERNAL_ERROR)


def test_write_message_surrogate_in_method_name_survives_and_keeps_serving() -> None:
    lines = [
        '{"jsonrpc":"2.0","id":1,"method":"no\\ud800such"}',
        '{"jsonrpc":"2.0","id":2,"method":"system.shutdown"}',
    ]
    server, stdout = _make_server(lines)
    server.serve()

    messages = _read_json_lines(stdout)
    assert len(messages) == 2
    assert messages[0]["id"] == 1
    _assert_protocol_error_shape(messages[0], INTERNAL_ERROR)
    assert messages[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


def test_write_message_surrogate_in_result_survives_and_keeps_serving() -> None:
    lines = [
        '{"jsonrpc":"2.0","id":1,"method":"test.surrogate"}',
        '{"jsonrpc":"2.0","id":2,"method":"system.shutdown"}',
    ]
    server, stdout = _make_server(lines)
    server.register("test.surrogate", lambda: {"text": "bad\ud800char"})
    server.serve()

    messages = _read_json_lines(stdout)
    assert len(messages) == 2
    assert messages[0]["id"] == 1
    _assert_protocol_error_shape(messages[0], INTERNAL_ERROR)
    assert messages[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


def test_write_message_nan_result_survives_and_keeps_serving() -> None:
    lines = [
        '{"jsonrpc":"2.0","id":1,"method":"test.nan"}',
        '{"jsonrpc":"2.0","id":2,"method":"system.shutdown"}',
    ]
    server, stdout = _make_server(lines)
    server.register("test.nan", lambda: {"value": math.nan})
    server.serve()

    raw_text = stdout.getvalue().decode("utf-8")
    assert "NaN" not in raw_text
    messages = [json.loads(line, parse_constant=_reject_constant) for line in raw_text.splitlines()]
    assert len(messages) == 2
    assert messages[0]["id"] == 1
    _assert_protocol_error_shape(messages[0], INTERNAL_ERROR)
    assert messages[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


def _reject_constant(val: str) -> Any:
    raise ValueError(f"Non-standard JSON constant: {val}")


def test_write_message_circular_result_survives_and_keeps_serving() -> None:
    lines = [
        '{"jsonrpc":"2.0","id":1,"method":"test.circular"}',
        '{"jsonrpc":"2.0","id":2,"method":"system.shutdown"}',
    ]
    server, stdout = _make_server(lines)

    def make_circular() -> dict[str, Any]:
        d: dict[str, Any] = {}
        d["self"] = d
        return d

    server.register("test.circular", make_circular)
    server.serve()

    messages = _read_json_lines(stdout)
    assert len(messages) == 2
    assert messages[0]["id"] == 1
    _assert_protocol_error_shape(messages[0], INTERNAL_ERROR)
    assert messages[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


def test_skald_error_mapping() -> None:
    server, _ = _make_server()

    def fail_drm() -> None:
        raise SkaldError(
            kind="epub_drm",
            message="This book is protected by DRM.",
            details={"file": "book.epub"},
            hint="Use a DRM-free EPUB.",
        )

    server.register("test.fail", fail_drm)
    resp = server.handle_line('{"jsonrpc":"2.0","id":6,"method":"test.fail"}')
    assert resp == {
        "jsonrpc": "2.0",
        "id": 6,
        "error": {
            "code": APP_ERROR,
            "message": "This book is protected by DRM.",
            "data": {
                "kind": "epub_drm",
                "details": {"file": "book.epub"},
                "hint": "Use a DRM-free EPUB.",
            },
        },
    }


def test_notifications_receive_no_response_and_null_id_is_request() -> None:
    seen: list[str] = []
    server, _ = _make_server()
    server.register("test.note", lambda p: seen.append(p.text), EchoParams)
    server.register("test.fail", lambda: (_ for _ in ()).throw(SkaldError("internal", "err")))

    note_line = '{"jsonrpc":"2.0","method":"test.note","params":{"text":"hi"}}'
    assert server.handle_line(note_line) is None
    assert seen == ["hi"]

    # Errors/unknown methods on notifications also produce no response.
    assert server.handle_line('{"jsonrpc":"2.0","method":"missing"}') is None
    assert server.handle_line('{"jsonrpc":"2.0","method":"test.note","params":{}}') is None
    assert server.handle_line('{"jsonrpc":"2.0","method":"test.fail"}') is None

    # Explicit id: null is a request, not a notification.
    resp = server.handle_line('{"jsonrpc":"2.0","id":null,"method":"missing"}')
    assert resp is not None
    assert resp["id"] is None
    _assert_protocol_error_shape(resp, METHOD_NOT_FOUND)


def test_notify_helper_and_thread_safe_writes() -> None:
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "test.burst"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "system.shutdown"}),
    ]
    server, stdout = _make_server(lines)

    def burst() -> dict[str, bool]:
        errors: list[BaseException] = []

        def worker(idx: int) -> None:
            try:
                for step in range(20):
                    notify("job.progress", EchoResult(echoed=f"w{idx}", count=step))
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        return {"ok": True}

    server.register("test.burst", burst)
    server.serve()

    raw_bytes = stdout.getvalue()
    assert b"\r\n" not in raw_bytes
    messages = _read_json_lines(stdout)
    notes = [m for m in messages if "method" in m]
    responses = [m for m in messages if "id" in m]
    assert len(notes) == 80
    assert all(m["method"] == "job.progress" for m in notes)
    assert responses == [
        {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
        {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
    ]


def test_configure_logging_uses_skald_log_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKALD_LOG_DIR", str(tmp_path))
    try:
        log_file = configure_logging()
        assert log_file == tmp_path / "skald-core.log"
        logging.getLogger("skald_core.test").info("hello log file")
    finally:
        close_managed_logging()

    assert log_file.is_file()
    assert "hello log file" in log_file.read_text(encoding="utf-8")


@pytest.mark.timeout(10)
def test_unwritable_log_dir_falls_back_to_stderr_and_keeps_serving(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "occupied_file"
    not_a_dir.write_text("blocker", encoding="utf-8")
    env = {**os.environ, "SKALD_LOG_DIR": str(not_a_dir)}

    proc = subprocess.run(
        [sys.executable, "-m", "skald_core"],
        input=b'{"jsonrpc":"2.0","id":1,"method":"system.shutdown"}\n',
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    responses = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line]
    assert responses == [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}]
    stderr_text = proc.stderr.decode("utf-8")
    assert "logging to stderr only" in stderr_text
    assert "Traceback" not in stderr_text


@pytest.mark.timeout(10)
def test_subprocess_popen_flushes_response_before_stdin_eof(tmp_path: Path) -> None:
    env = {**os.environ, "SKALD_LOG_DIR": str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "skald_core"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None

        proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"unknown.ping"}\n')
        proc.stdin.flush()

        first_line = proc.stdout.readline()
        assert first_line.endswith(b"\n")
        assert not first_line.endswith(b"\r\n")
        first_msg = json.loads(first_line.decode("utf-8"))
        assert first_msg["id"] == 1
        _assert_protocol_error_shape(first_msg, METHOD_NOT_FOUND)

        proc.stdin.write(b'{"jsonrpc":"2.0","id":2,"method":"system.shutdown"}\n')
        proc.stdin.flush()

        second_line = proc.stdout.readline()
        second_msg = json.loads(second_line.decode("utf-8"))
        assert second_msg == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}

        rc = proc.wait(timeout=5)
        assert rc == 0
        assert "Traceback" not in proc.stderr.read().decode("utf-8")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest.mark.timeout(10)
def test_subprocess_main_errors_and_shutdown(tmp_path: Path) -> None:
    env = {**os.environ, "SKALD_LOG_DIR": str(tmp_path)}
    requests = [
        "{bad json",
        '[{"jsonrpc":"2.0","id":1,"method":"system.shutdown"}]',
        '{"jsonrpc":"2.0","id":2,"method":"unknown.method"}',
        '{"jsonrpc":"2.0","id":3,"method":"system.shutdown"}',
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core"],
        input=("\n".join(requests) + "\n").encode("utf-8"),
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert b"\r\n" not in proc.stdout
    stderr_text = proc.stderr.decode("utf-8")
    assert "Traceback" not in stderr_text

    responses = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line]
    assert [r["id"] for r in responses] == [None, None, 2, 3]
    _assert_protocol_error_shape(responses[0], PARSE_ERROR)
    _assert_protocol_error_shape(responses[1], INVALID_REQUEST)
    _assert_protocol_error_shape(responses[2], METHOD_NOT_FOUND)
    assert responses[3] == {"jsonrpc": "2.0", "id": 3, "result": {"ok": True}}

    log_file = tmp_path / "skald-core.log"
    assert log_file.is_file()
    assert "Skald core JSON-RPC server started" in log_file.read_text(encoding="utf-8")


@pytest.mark.timeout(10)
def test_subprocess_stray_print_utf8_roundtrip_and_errors(tmp_path: Path) -> None:
    script = """
from pydantic import BaseModel, Field
from skald_core.rpc import SkaldError, notify, run_stdio_server

class TextIn(BaseModel):
    text: str = Field(min_length=1)

class TextOut(BaseModel):
    text: str

def echo_and_print(params: TextIn) -> TextOut:
    print("STRAY_STDOUT_MUST_GO_TO_STDERR")
    notify("test.progress", {"label": params.text})
    return TextOut(text=params.text)

def fail_app() -> None:
    raise SkaldError("adapter_unavailable", "Missing adapter", details={"id": "x"}, hint="Install")

def setup(server):
    server.register("test.echo", echo_and_print, TextIn, TextOut)
    server.register("test.fail", fail_app)

raise SystemExit(run_stdio_server(setup=setup))
"""
    non_ascii = "Skald — Þórsmörk, café, 日本語 🎙️"
    requests = [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "test.echo",
                "params": {"text": non_ascii},
            },
            ensure_ascii=False,
        ),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "test.echo", "params": {"text": ""}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "test.fail"}),
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "system.shutdown"}),
    ]
    env = {**os.environ, "SKALD_LOG_DIR": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-c", script],
        input=("\n".join(requests) + "\n").encode("utf-8"),
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert b"\r\n" not in proc.stdout

    stdout_text = proc.stdout.decode("utf-8")
    stderr_text = proc.stderr.decode("utf-8")
    assert "STRAY_STDOUT_MUST_GO_TO_STDERR" not in stdout_text
    assert "STRAY_STDOUT_MUST_GO_TO_STDERR" in stderr_text
    assert "Traceback" not in stderr_text

    messages = [json.loads(line) for line in stdout_text.splitlines() if line]
    assert len(messages) == 5
    assert messages[0] == {
        "jsonrpc": "2.0",
        "method": "test.progress",
        "params": {"label": non_ascii},
    }
    assert messages[1] == {"jsonrpc": "2.0", "id": 1, "result": {"text": non_ascii}}
    assert messages[2]["id"] == 2
    _assert_protocol_error_shape(messages[2], INVALID_PARAMS)
    assert messages[2]["error"]["data"]["details"]
    assert messages[3] == {
        "jsonrpc": "2.0",
        "id": 3,
        "error": {
            "code": APP_ERROR,
            "message": "Missing adapter",
            "data": {"kind": "adapter_unavailable", "details": {"id": "x"}, "hint": "Install"},
        },
    }
    assert messages[4] == {"jsonrpc": "2.0", "id": 4, "result": {"ok": True}}
