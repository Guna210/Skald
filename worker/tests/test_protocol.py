"""Unit tests for skald_worker JSON-RPC protocol, error handling, and isolation rules."""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest
import soundfile as sf
from pydantic import BaseModel, ConfigDict, Field

from skald_worker.adapters import ADAPTER_VERSIONS
from skald_worker.adapters.fake import FakeAdapter
from skald_worker.protocol import (
    APP_ERROR,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    Adapter,
    AudioResult,
    BlendVoiceSpec,
    Capability,
    CloneVoiceSpec,
    LoadResult,
    PresetVoiceSpec,
    VoiceInfo,
    WorkerError,
    WorkerErrorKind,
    WorkerRpcServer,
    write_wav_atomic,
)

_WORKER_PKG_DIR = Path(__file__).resolve().parents[1] / "skald_worker"


class _MinimalParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gain: float = Field(default=1.0, ge=0.1, le=2.0)


class _NoDesignAdapter(Adapter):
    name: ClassVar[str] = "no_design"
    version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar[tuple[Capability, ...]] = ("presets",)
    max_chars: ClassVar[int] = 100
    languages: ClassVar[tuple[str, ...]] = ("en",)
    deterministic_cpu: ClassVar[bool] = True
    params_model: ClassVar[type[BaseModel]] = _MinimalParams

    def load(
        self,
        checkpoint_id: str,
        files_dir: Path,
        device: str,
        dtype: str,
        threads: int | None,
    ) -> LoadResult:
        del checkpoint_id, files_dir, threads
        return LoadResult(device=device, dtype=dtype)

    def voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(id="v1", name="Voice 1", language="en")]

    def synthesize(
        self,
        *,
        text: str,
        language: str,
        voice: PresetVoiceSpec | BlendVoiceSpec | CloneVoiceSpec,
        params: BaseModel,
        seed: int,
    ) -> AudioResult:
        del text, language, voice, params, seed
        return AudioResult(samples=np.full(2400, 0.25, dtype=np.float32), sample_rate=24000)

    def unload(self) -> None:
        return None


def _make_server(
    lines: list[str] | None = None,
    adapter: Adapter | None = None,
) -> tuple[WorkerRpcServer, io.BytesIO]:
    raw = "".join(f"{line}\n" for line in (lines or [])).encode("utf-8")
    stdin = io.BytesIO(raw)
    stdout = io.BytesIO()
    return WorkerRpcServer(adapter=adapter or FakeAdapter(), stdin=stdin, stdout=stdout), stdout


def _read_messages(stdout: io.BytesIO) -> list[dict[str, Any]]:
    raw = stdout.getvalue()
    assert b"\r\n" not in raw
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]


def _assert_protocol_error(resp: dict[str, Any], code: int) -> None:
    err = resp["error"]
    assert err["code"] == code
    assert set(err["data"].keys()) == {"kind", "details", "hint"}
    assert err["data"]["kind"] == "internal"
    assert err["data"]["hint"] is None


def test_skald_worker_never_imports_skald_core() -> None:
    for py_file in sorted(_WORKER_PKG_DIR.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("skald_core"), (
                        f"{py_file} imports {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith("skald_core"), (
                    f"{py_file} imports from {node.module}"
                )


def test_adapter_registry_literal_is_empty() -> None:
    init_file = _WORKER_PKG_DIR / "adapters" / "__init__.py"
    tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    found = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "ADAPTER_VERSIONS" and node.value is not None:
                found = ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ADAPTER_VERSIONS":
                    found = ast.literal_eval(node.value)
    assert found == {}
    assert ADAPTER_VERSIONS == {}


def test_worker_error_kind_subset() -> None:
    from typing import get_args

    assert set(get_args(WorkerErrorKind)) == {
        "internal",
        "out_of_memory",
        "adapter_unavailable",
        "unsupported_format",
    }


def test_malformed_json_returns_parse_error() -> None:
    server, _ = _make_server()
    resp = server.handle_line("{not valid json")
    assert resp is not None
    assert resp["id"] is None
    _assert_protocol_error(resp, PARSE_ERROR)


def test_deeply_nested_json_returns_parse_error() -> None:
    server, _ = _make_server()
    resp = server.handle_line(("[" * 10000) + ("]" * 10000))
    assert resp is not None
    assert resp["id"] is None
    _assert_protocol_error(resp, PARSE_ERROR)


def test_invalid_utf8_emits_parse_error_and_continues() -> None:
    stdin = io.BytesIO(b"\xff\xfe\n" + b'{"jsonrpc":"2.0","id":2,"method":"worker.shutdown"}\n')
    stdout = io.BytesIO()
    server = WorkerRpcServer(adapter=FakeAdapter(), stdin=stdin, stdout=stdout)
    server.serve()
    msgs = _read_messages(stdout)
    assert len(msgs) == 2
    assert msgs[0]["id"] is None
    _assert_protocol_error(msgs[0], PARSE_ERROR)
    assert msgs[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


@pytest.mark.parametrize(
    "raw_line",
    [
        '[{"jsonrpc":"2.0","id":1,"method":"worker.hello"}]',
        "[]",
        "42",
        '"hello"',
        '{"id":1,"method":"worker.hello"}',
        '{"jsonrpc":"1.0","id":1,"method":"worker.hello"}',
        '{"jsonrpc":"2.0","id":1}',
        '{"jsonrpc":"2.0","id":1,"method":123}',
        '{"jsonrpc":"2.0","id":true,"method":"worker.hello"}',
        '{"jsonrpc":"2.0","id":[1],"method":"worker.hello"}',
    ],
)
def test_batch_and_invalid_requests_return_invalid_request(raw_line: str) -> None:
    server, _ = _make_server()
    resp = server.handle_line(raw_line)
    assert resp is not None
    _assert_protocol_error(resp, INVALID_REQUEST)
    if raw_line.startswith("["):
        assert resp["id"] is None


def test_unknown_method_returns_method_not_found() -> None:
    server, _ = _make_server()
    resp = server.handle_line('{"jsonrpc":"2.0","id":9,"method":"worker.unknown"}')
    assert resp is not None
    assert resp["id"] == 9
    _assert_protocol_error(resp, METHOD_NOT_FOUND)


def test_design_sample_not_registered_for_non_design_adapter() -> None:
    server, _ = _make_server(adapter=_NoDesignAdapter())
    resp = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "worker.design_sample",
                "params": {
                    "description": "warm narrator",
                    "sample_text": "Hello world.",
                    "language": "en",
                    "seed": 1,
                    "out_path": "out.wav",
                },
            }
        )
    )
    assert resp is not None
    _assert_protocol_error(resp, METHOD_NOT_FOUND)


def test_invalid_params_variants() -> None:
    server, _ = _make_server()
    # Array params for method taking object
    r_arr = server.handle_line('{"jsonrpc":"2.0","id":1,"method":"worker.load","params":["a"]}')
    assert r_arr is not None
    _assert_protocol_error(r_arr, INVALID_PARAMS)

    # Unexpected params for no-param method
    r_extra = server.handle_line(
        '{"jsonrpc":"2.0","id":2,"method":"worker.hello","params":{"x":1}}'
    )
    assert r_extra is not None
    _assert_protocol_error(r_extra, INVALID_PARAMS)

    # Load first, then test adapter param validation
    load_resp = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "worker.load",
                "params": {"checkpoint_id": "c1", "files_dir": ".", "device": "cpu"},
            }
        )
    )
    assert load_resp is not None and "result" in load_resp

    # Out-of-range speed and unknown field
    bad_synth = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "worker.synthesize",
                "params": {
                    "text": "Hello",
                    "language": "en",
                    "voice": {"kind": "preset", "id": "fake_narrator"},
                    "params": {"speed": 9.0},
                    "seed": 1,
                    "out_path": "out.wav",
                },
            }
        )
    )
    assert bad_synth is not None
    _assert_protocol_error(bad_synth, INVALID_PARAMS)
    assert bad_synth["error"]["data"]["details"]

    # Blank text
    blank_text = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "worker.synthesize",
                "params": {
                    "text": "   ",
                    "language": "en",
                    "voice": {"kind": "preset", "id": "fake_narrator"},
                    "params": {},
                    "seed": 1,
                    "out_path": "out.wav",
                },
            }
        )
    )
    assert blank_text is not None
    _assert_protocol_error(blank_text, INVALID_PARAMS)


def test_notifications_produce_no_response() -> None:
    lines = [
        '{"jsonrpc":"2.0","method":"worker.hello"}',
        '{"jsonrpc":"2.0","method":"worker.unknown"}',
        '{"jsonrpc":"2.0","method":"worker.load","params":{"bad":1}}',
        '{"jsonrpc":"2.0","method":"worker.voices"}',
        '{"jsonrpc":"2.0","id":10,"method":"worker.shutdown"}',
    ]
    server, stdout = _make_server(lines)
    server.serve()
    msgs = _read_messages(stdout)
    assert msgs == [{"jsonrpc": "2.0", "id": 10, "result": {"ok": True}}]


def test_worker_error_and_internal_error_mapping() -> None:
    server, _ = _make_server()

    def raise_worker_err() -> dict[str, Any]:
        raise WorkerError("out_of_memory", "CUDA OOM", details={"mb": 100}, hint="Use CPU.")

    def raise_unexpected() -> dict[str, Any]:
        raise RuntimeError("boom")

    server.register("test.worker_err", raise_worker_err)
    server.register("test.boom", raise_unexpected)

    r1 = server.handle_line('{"jsonrpc":"2.0","id":1,"method":"test.worker_err"}')
    assert r1 == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": APP_ERROR,
            "message": "CUDA OOM",
            "data": {"kind": "out_of_memory", "details": {"mb": 100}, "hint": "Use CPU."},
        },
    }

    r2 = server.handle_line('{"jsonrpc":"2.0","id":2,"method":"test.boom"}')
    assert r2 is not None
    _assert_protocol_error(r2, INTERNAL_ERROR)
    assert "boom" in r2["error"]["data"]["details"]


def test_surrogate_in_response_falls_back_to_internal_error() -> None:
    lines = [
        '{"jsonrpc":"2.0","id":1,"method":"test.surrogate"}',
        '{"jsonrpc":"2.0","id":2,"method":"worker.shutdown"}',
    ]
    server, stdout = _make_server(lines)
    server.register("test.surrogate", lambda: {"text": "bad\ud800char"})
    server.serve()
    msgs = _read_messages(stdout)
    assert len(msgs) == 2
    assert msgs[0]["id"] == 1
    _assert_protocol_error(msgs[0], INTERNAL_ERROR)
    assert msgs[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}


def test_utf8_round_trip_and_lf_only(tmp_path: Path) -> None:
    out_wav = tmp_path / "café_音声.wav"
    lines = [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "worker.load",
                "params": {"checkpoint_id": "cp", "files_dir": str(tmp_path), "device": "cpu"},
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "worker.synthesize",
                "params": {
                    "text": "Héllo — 日本語テスト!",
                    "language": "en",
                    "voice": {"kind": "preset", "id": "fake_narrator"},
                    "params": {},
                    "seed": 42,
                    "out_path": str(out_wav),
                },
            },
            ensure_ascii=False,
        ),
        '{"jsonrpc":"2.0","id":3,"method":"worker.shutdown"}',
    ]
    server, stdout = _make_server(lines)
    server.serve()
    msgs = _read_messages(stdout)
    assert len(msgs) == 3
    assert "result" in msgs[1]
    assert out_wav.is_file()
    info = sf.info(str(out_wav))
    assert info.format == "WAV"
    assert info.subtype == "PCM_16"
    assert info.channels == 1


def test_write_wav_atomic_cleans_temp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_wav = tmp_path / "target.wav"

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(sf, "write", boom)
    with pytest.raises(OSError, match="disk full"):
        write_wav_atomic(out_wav, np.ones(100, dtype=np.float32), 24000)

    assert not out_wav.exists()
    assert list(tmp_path.iterdir()) == []
