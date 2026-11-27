"""Reusable V3 adapter contract suite driving `python -m skald_worker` over stdio."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from skald_worker.protocol import INVALID_PARAMS, METHOD_NOT_FOUND
from tests.contract.conftest import WorkerClient

pytestmark = pytest.mark.timeout(30)

ALLOWED_CAPABILITIES = {"presets", "blend", "clone", "design", "speed", "style"}
ALLOWED_WORKER_ERROR_KINDS = {
    "internal",
    "out_of_memory",
    "adapter_unavailable",
    "unsupported_format",
}


def _select_device(hello: dict[str, Any], target_device: str | None) -> str:
    if target_device is not None:
        return target_device
    devices = hello["device_options"]
    assert isinstance(devices, list) and devices
    return str(devices[0])


def _load_default_checkpoint(
    client: WorkerClient,
    checkpoint_id: str,
    checkpoint_dir: Path,
    target_device: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hello_resp = client.call("worker.hello")
    assert "result" in hello_resp, hello_resp
    hello = hello_resp["result"]
    device = _select_device(hello, target_device)

    load_resp = client.call(
        "worker.load",
        {
            "checkpoint_id": checkpoint_id,
            "files_dir": str(checkpoint_dir),
            "device": device,
            "dtype": "auto",
        },
    )
    assert "result" in load_resp, load_resp

    voices_resp = client.call("worker.voices")
    assert "result" in voices_resp, voices_resp
    voices = voices_resp["result"]["voices"]
    assert isinstance(voices, list)
    return hello, voices


def _assert_valid_mono_wav(wav_path: Path, expected_rate: int) -> tuple[np.ndarray[Any, Any], int]:
    assert wav_path.is_file(), f"Missing output WAV: {wav_path}"
    info = sf.info(str(wav_path))
    assert info.format == "WAV"
    assert info.subtype == "PCM_16"
    assert info.channels == 1
    assert info.samplerate == expected_rate
    assert info.frames > 0
    samples, rate = sf.read(str(wav_path), dtype="int16")
    assert rate == expected_rate
    assert samples.ndim == 1
    assert samples.size > 0
    return samples, rate


def test_check_cli_succeeds_with_empty_stdout(adapter_name: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "skald_worker", "--adapter", adapter_name, "--check"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=20.0,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert proc.stdout == b""
    stderr_text = proc.stderr.decode("utf-8")
    assert stderr_text.strip()
    lines = [line for line in stderr_text.splitlines() if line.strip()]
    parsed = json.loads(lines[-1])
    assert parsed["ok"] is True
    assert parsed["adapter"] == adapter_name
    assert isinstance(parsed["adapter_version"], str) and parsed["adapter_version"]
    assert isinstance(parsed["worker_version"], str) and parsed["worker_version"]
    assert isinstance(parsed["devices"], list) and parsed["devices"]


def test_check_cli_unknown_adapter_fails_with_empty_stdout() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "skald_worker", "--adapter", "__unknown_adapter__", "--check"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=20.0,
        check=False,
    )
    assert proc.returncode != 0
    assert proc.stdout == b""
    assert proc.stderr.strip()


def test_hello_contract(worker_client: WorkerClient, adapter_name: str) -> None:
    resp = worker_client.call("worker.hello")
    assert "result" in resp, resp
    hello = resp["result"]

    assert hello["adapter"] == adapter_name
    assert isinstance(hello["adapter_version"], str) and hello["adapter_version"]
    assert isinstance(hello["worker_version"], str) and hello["worker_version"]
    assert isinstance(hello["python"], str) and hello["python"]
    assert hello["torch"] is None or isinstance(hello["torch"], str)
    assert isinstance(hello["device_options"], list) and len(hello["device_options"]) >= 1
    assert set(hello["capabilities"]).issubset(ALLOWED_CAPABILITIES)
    assert isinstance(hello["max_chars"], int) and hello["max_chars"] > 0
    assert isinstance(hello["languages"], list) and len(hello["languages"]) >= 1
    assert isinstance(hello["deterministic_cpu"], bool)
    assert isinstance(hello["params_schema"], dict)
    assert "properties" in hello["params_schema"]

    shutdown_resp = worker_client.call("worker.shutdown")
    assert shutdown_resp["result"] == {"ok": True}
    assert worker_client.wait() == 0
    worker_client.assert_all_stdout_valid_jsonrpc()


def test_load_voices_unload_and_shutdown_lifecycle(
    worker_client: WorkerClient,
    checkpoint_dir: Path,
    checkpoint_id: str,
    target_device: str | None,
    tmp_path: Path,
) -> None:
    # Calling voices or synthesize before load must return adapter_unavailable.
    pre_voices = worker_client.call("worker.voices")
    assert pre_voices["error"]["data"]["kind"] == "adapter_unavailable"

    pre_synth = worker_client.call(
        "worker.synthesize",
        {
            "text": "Hello",
            "language": "en",
            "voice": {"kind": "preset", "id": "any"},
            "params": {},
            "seed": 1,
            "out_path": str(tmp_path / "pre.wav"),
        },
    )
    assert pre_synth["error"]["data"]["kind"] == "adapter_unavailable"

    # Unavailable device fails cleanly.
    bad_load = worker_client.call(
        "worker.load",
        {
            "checkpoint_id": checkpoint_id,
            "files_dir": str(checkpoint_dir),
            "device": "cuda:99",
        },
    )
    assert bad_load["error"]["data"]["kind"] == "adapter_unavailable"

    hello, voices = _load_default_checkpoint(
        worker_client, checkpoint_id, checkpoint_dir, target_device
    )
    if "presets" in hello["capabilities"]:
        assert len(voices) >= 1
        for voice in voices:
            assert isinstance(voice["id"], str) and voice["id"]
            assert isinstance(voice["name"], str) and voice["name"]
            assert isinstance(voice["language"], str) and voice["language"]

    unload_resp = worker_client.call("worker.unload")
    assert unload_resp["result"] == {"ok": True}

    post_voices = worker_client.call("worker.voices")
    assert post_voices["error"]["data"]["kind"] == "adapter_unavailable"

    shutdown_resp = worker_client.call("worker.shutdown")
    assert shutdown_resp["result"] == {"ok": True}
    assert worker_client.wait() == 0
    worker_client.assert_all_stdout_valid_jsonrpc()


def test_synthesize_wav_and_cpu_determinism(
    worker_client: WorkerClient,
    checkpoint_dir: Path,
    checkpoint_id: str,
    target_device: str | None,
    tmp_path: Path,
) -> None:
    hello, voices = _load_default_checkpoint(
        worker_client, checkpoint_id, checkpoint_dir, target_device
    )
    language = str(hello["languages"][0])
    if "presets" in hello["capabilities"]:
        voice: dict[str, Any] = {"kind": "preset", "id": voices[0]["id"]}
    elif "clone" in hello["capabilities"]:
        ref_wav = tmp_path / "ref.wav"
        sf.write(str(ref_wav), np.full(24000, 0.1, dtype=np.float32), 24000, subtype="PCM_16")
        voice = {"kind": "clone", "reference_wav": str(ref_wav)}
    else:
        pytest.skip("Adapter supports neither presets nor clone.")

    out1 = tmp_path / "out one.wav"
    out2 = tmp_path / "out_two_音声.wav"

    r1 = worker_client.call(
        "worker.synthesize",
        {
            "text": "The quick brown fox jumps over the lazy dog.",
            "language": language,
            "voice": voice,
            "params": {},
            "seed": 1234,
            "out_path": str(out1),
        },
    )
    assert "result" in r1, r1
    res1 = r1["result"]
    assert res1["sample_rate"] > 0
    assert res1["duration_s"] > 0
    assert res1["rtf"] >= 0
    _assert_valid_mono_wav(out1, res1["sample_rate"])

    if hello["deterministic_cpu"] and _select_device(hello, target_device) == "cpu":
        r2 = worker_client.call(
            "worker.synthesize",
            {
                "text": "The quick brown fox jumps over the lazy dog.",
                "language": language,
                "voice": voice,
                "params": {},
                "seed": 1234,
                "out_path": str(out2),
            },
        )
        assert "result" in r2, r2
        assert out1.read_bytes() == out2.read_bytes()

    shutdown_resp = worker_client.call("worker.shutdown")
    assert shutdown_resp["result"] == {"ok": True}
    assert worker_client.wait() == 0
    worker_client.assert_all_stdout_valid_jsonrpc()


def test_param_validation_and_errors(
    worker_client: WorkerClient,
    checkpoint_dir: Path,
    checkpoint_id: str,
    target_device: str | None,
    tmp_path: Path,
) -> None:
    hello, _ = _load_default_checkpoint(worker_client, checkpoint_id, checkpoint_dir, target_device)
    language = str(hello["languages"][0])

    # Missing required field -> -32602
    missing_text = worker_client.call(
        "worker.synthesize",
        {
            "language": language,
            "voice": {"kind": "preset", "id": "any"},
            "params": {},
            "seed": 1,
            "out_path": str(tmp_path / "bad1.wav"),
        },
    )
    assert missing_text["error"]["code"] == INVALID_PARAMS
    assert missing_text["error"]["data"]["kind"] == "internal"
    assert missing_text["error"]["data"]["details"]

    # Unknown adapter parameter -> -32602
    unknown_param = worker_client.call(
        "worker.synthesize",
        {
            "text": "Hello",
            "language": language,
            "voice": {"kind": "preset", "id": "any"},
            "params": {"__unknown_param__": 123},
            "seed": 1,
            "out_path": str(tmp_path / "bad2.wav"),
        },
    )
    assert unknown_param["error"]["code"] == INVALID_PARAMS
    assert unknown_param["error"]["data"]["kind"] == "internal"

    # Unknown preset voice -> application error from allowed subset
    if "presets" in hello["capabilities"]:
        bad_voice = worker_client.call(
            "worker.synthesize",
            {
                "text": "Hello",
                "language": language,
                "voice": {"kind": "preset", "id": "__nonexistent_voice__"},
                "params": {},
                "seed": 1,
                "out_path": str(tmp_path / "bad3.wav"),
            },
        )
        assert "error" in bad_voice
        assert bad_voice["error"]["data"]["kind"] in ALLOWED_WORKER_ERROR_KINDS

    assert worker_client.call("worker.shutdown")["result"] == {"ok": True}
    assert worker_client.wait() == 0
    worker_client.assert_all_stdout_valid_jsonrpc()


def test_optional_capabilities_blend_clone_design(
    worker_client: WorkerClient,
    checkpoint_dir: Path,
    checkpoint_id: str,
    target_device: str | None,
    tmp_path: Path,
) -> None:
    hello, voices = _load_default_checkpoint(
        worker_client, checkpoint_id, checkpoint_dir, target_device
    )
    language = str(hello["languages"][0])
    caps = set(hello["capabilities"])

    if "blend" in caps:
        assert len(voices) >= 1
        second_id = voices[1]["id"] if len(voices) > 1 else voices[0]["id"]
        blend_wav = tmp_path / "blend.wav"
        blend_resp = worker_client.call(
            "worker.synthesize",
            {
                "text": "Blended voice check.",
                "language": language,
                "voice": {
                    "kind": "blend",
                    "parts": [
                        {"id": voices[0]["id"], "weight": 0.6},
                        {"id": second_id, "weight": 0.4},
                    ],
                },
                "params": {},
                "seed": 7,
                "out_path": str(blend_wav),
            },
        )
        assert "result" in blend_resp, blend_resp
        _assert_valid_mono_wav(blend_wav, blend_resp["result"]["sample_rate"])

    if "clone" in caps:
        ref_wav = tmp_path / "reference.wav"
        sf.write(str(ref_wav), np.full(24000, 0.2, dtype=np.float32), 24000, subtype="PCM_16")
        clone_wav = tmp_path / "clone.wav"
        clone_resp = worker_client.call(
            "worker.synthesize",
            {
                "text": "Cloned voice check.",
                "language": language,
                "voice": {
                    "kind": "clone",
                    "reference_wav": str(ref_wav),
                    "reference_text": "Reference clip.",
                },
                "params": {},
                "seed": 8,
                "out_path": str(clone_wav),
            },
        )
        assert "result" in clone_resp, clone_resp
        _assert_valid_mono_wav(clone_wav, clone_resp["result"]["sample_rate"])

        missing_clone = worker_client.call(
            "worker.synthesize",
            {
                "text": "Missing ref.",
                "language": language,
                "voice": {"kind": "clone", "reference_wav": str(tmp_path / "missing.wav")},
                "params": {},
                "seed": 8,
                "out_path": str(tmp_path / "clone_missing.wav"),
            },
        )
        assert "error" in missing_clone
        assert missing_clone["error"]["data"]["kind"] in ALLOWED_WORKER_ERROR_KINDS

    design_wav = tmp_path / "design.wav"
    design_resp = worker_client.call(
        "worker.design_sample",
        {
            "description": "Warm calm narrator with steady pacing.",
            "sample_text": "Once upon a time in a quiet valley.",
            "language": language,
            "seed": 9,
            "out_path": str(design_wav),
        },
    )
    if "design" in caps:
        assert "result" in design_resp, design_resp
        _assert_valid_mono_wav(design_wav, design_resp["result"]["sample_rate"])
    else:
        assert design_resp["error"]["code"] == METHOD_NOT_FOUND

    assert worker_client.call("worker.shutdown")["result"] == {"ok": True}
    assert worker_client.wait() == 0
    worker_client.assert_all_stdout_valid_jsonrpc()


def test_fake_modes_and_stdout_protection(
    worker_client: WorkerClient,
    adapter_name: str,
    checkpoint_dir: Path,
    checkpoint_id: str,
    target_device: str | None,
    tmp_path: Path,
) -> None:
    if adapter_name != "fake":
        pytest.skip("Fake-mode tests only run against the fake adapter.")

    _, voices = _load_default_checkpoint(
        worker_client, checkpoint_id, checkpoint_dir, target_device
    )
    voice = {"kind": "preset", "id": voices[0]["id"]}

    # Duration scales with len(text), and seed/voice alter waveform.
    short_wav = tmp_path / "short.wav"
    long_wav = tmp_path / "long.wav"
    diff_seed_wav = tmp_path / "diff_seed.wav"
    r_short = worker_client.call(
        "worker.synthesize",
        {
            "text": "Short.",
            "language": "en",
            "voice": voice,
            "params": {"fake_mode": "ok"},
            "seed": 1,
            "out_path": str(short_wav),
        },
    )["result"]
    r_long = worker_client.call(
        "worker.synthesize",
        {
            "text": "This is a substantially longer passage of text for duration scaling.",
            "language": "en",
            "voice": voice,
            "params": {"fake_mode": "ok"},
            "seed": 1,
            "out_path": str(long_wav),
        },
    )["result"]
    assert r_short["sample_rate"] == 24000
    assert r_long["duration_s"] > r_short["duration_s"]

    worker_client.call(
        "worker.synthesize",
        {
            "text": "Short.",
            "language": "en",
            "voice": voice,
            "params": {"fake_mode": "ok"},
            "seed": 99,
            "out_path": str(diff_seed_wav),
        },
    )
    assert short_wav.read_bytes() != diff_seed_wav.read_bytes()

    # fail mode
    fail_resp = worker_client.call(
        "worker.synthesize",
        {
            "text": "Fail test.",
            "language": "en",
            "voice": voice,
            "params": {"fake_mode": "fail"},
            "seed": 1,
            "out_path": str(tmp_path / "fail.wav"),
        },
    )
    assert fail_resp["error"]["data"]["kind"] == "internal"
    assert not (tmp_path / "fail.wav").exists()

    # silence mode
    silence_wav = tmp_path / "silence.wav"
    silence_resp = worker_client.call(
        "worker.synthesize",
        {
            "text": "Silence test.",
            "language": "en",
            "voice": voice,
            "params": {"fake_mode": "silence"},
            "seed": 1,
            "out_path": str(silence_wav),
        },
    )
    assert "result" in silence_resp
    silence_samples, _ = _assert_valid_mono_wav(silence_wav, 24000)
    assert np.all(silence_samples == 0)

    # clip mode
    clip_wav = tmp_path / "clip.wav"
    clip_resp = worker_client.call(
        "worker.synthesize",
        {
            "text": "Clip test.",
            "language": "en",
            "voice": voice,
            "params": {"fake_mode": "clip"},
            "seed": 1,
            "out_path": str(clip_wav),
        },
    )
    assert "result" in clip_resp
    clip_samples, _ = _assert_valid_mono_wav(clip_wav, 24000)
    assert np.all(np.abs(clip_samples.astype(np.int32)) >= 32767)

    # stdout_noise mode: print(), os.write(1, ...), child process inheriting stdout
    noise_wav = tmp_path / "noise.wav"
    noise_resp = worker_client.call(
        "worker.synthesize",
        {
            "text": "Noise test.",
            "language": "en",
            "voice": voice,
            "params": {"fake_mode": "stdout_noise"},
            "seed": 1,
            "out_path": str(noise_wav),
        },
    )
    assert "result" in noise_resp
    _assert_valid_mono_wav(noise_wav, 24000)

    assert worker_client.call("worker.shutdown")["result"] == {"ok": True}
    assert worker_client.wait() == 0
    worker_client.assert_all_stdout_valid_jsonrpc()

    stderr_text = worker_client.stderr_text()
    assert "fake stdout noise via print" in stderr_text
    assert "fake stdout noise via os.write(1)" in stderr_text
    assert "fake child stdout noise" in stderr_text


def test_fake_crash_mode(
    worker_client: WorkerClient,
    adapter_name: str,
    checkpoint_dir: Path,
    checkpoint_id: str,
    target_device: str | None,
    tmp_path: Path,
) -> None:
    if adapter_name != "fake":
        pytest.skip("Crash mode test only runs against the fake adapter.")

    _, voices = _load_default_checkpoint(
        worker_client, checkpoint_id, checkpoint_dir, target_device
    )
    crash_wav = tmp_path / "crash.wav"
    with pytest.raises(EOFError):
        worker_client.call(
            "worker.synthesize",
            {
                "text": "Crash now.",
                "language": "en",
                "voice": {"kind": "preset", "id": voices[0]["id"]},
                "params": {"fake_mode": "crash"},
                "seed": 1,
                "out_path": str(crash_wav),
            },
        )
    assert worker_client.wait() == 3
    assert not crash_wav.exists()
    worker_client.assert_all_stdout_valid_jsonrpc()


def test_cancel_by_kill_leaves_no_partial_wav_and_fresh_worker_works(
    worker_client: WorkerClient,
    adapter_name: str,
    checkpoint_dir: Path,
    checkpoint_id: str,
    target_device: str | None,
    tmp_path: Path,
) -> None:
    if adapter_name != "fake":
        pytest.skip("Cancel hang test uses fake_mode='hang'.")

    _, voices = _load_default_checkpoint(
        worker_client, checkpoint_id, checkpoint_dir, target_device
    )
    cancel_wav = tmp_path / "cancelled.wav"
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 999,
            "method": "worker.synthesize",
            "params": {
                "text": "Hang until killed.",
                "language": "en",
                "voice": {"kind": "preset", "id": voices[0]["id"]},
                "params": {"fake_mode": "hang"},
                "seed": 1,
                "out_path": str(cancel_wav),
            },
        }
    )
    worker_client.send_raw_line((payload + "\n").encode("utf-8"))
    time.sleep(0.25)
    assert worker_client.proc.poll() is None

    worker_client.kill()
    assert not cancel_wav.exists()
    worker_client.assert_all_stdout_valid_jsonrpc()

    # Verify a fresh worker starts and synthesizes cleanly after kill.
    fresh = WorkerClient(adapter_name)
    try:
        _, fresh_voices = _load_default_checkpoint(
            fresh, checkpoint_id, checkpoint_dir, target_device
        )
        ok_wav = tmp_path / "fresh_ok.wav"
        ok_resp = fresh.call(
            "worker.synthesize",
            {
                "text": "Fresh worker works.",
                "language": "en",
                "voice": {"kind": "preset", "id": fresh_voices[0]["id"]},
                "params": {},
                "seed": 1,
                "out_path": str(ok_wav),
            },
        )
        assert "result" in ok_resp, ok_resp
        _assert_valid_mono_wav(ok_wav, 24000)
        assert fresh.call("worker.shutdown")["result"] == {"ok": True}
        assert fresh.wait() == 0
        fresh.assert_all_stdout_valid_jsonrpc()
    finally:
        fresh.close()
