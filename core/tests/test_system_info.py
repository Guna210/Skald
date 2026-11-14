"""Tests for `system.info` and ffmpeg discovery."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import lxml
import numpy
import pydantic
import pytest

import skald_core
from skald_core.rpc.system import FFMPEG_BIN_BY_PLATFORM, get_system_info

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ffmpeg_bin_constant_matches_deps_lock() -> None:
    lock_path = _REPO_ROOT / "scripts" / "deps.lock.json"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    ffmpeg_assets = lock_data["ffmpeg"]["assets"]

    assert set(FFMPEG_BIN_BY_PLATFORM.keys()) == set(ffmpeg_assets.keys())
    for plat, asset in ffmpeg_assets.items():
        assert FFMPEG_BIN_BY_PLATFORM[plat] == asset["bin"]


def test_system_info_versions_and_ci_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKALD_FFMPEG", raising=False)
    monkeypatch.setenv("SKALD_VENDOR", str(_REPO_ROOT / "vendor"))

    info = get_system_info()
    assert info.core == skald_core.__version__
    assert info.python == platform.python_version()
    assert info.lxml == lxml.__version__
    assert info.pydantic == pydantic.__version__
    assert info.numpy == numpy.__version__

    if os.environ.get("CI") == "true":
        assert info.ffmpeg is not None
        assert info.ffmpeg.startswith("ffmpeg version")
    elif info.ffmpeg is not None:
        assert info.ffmpeg.startswith("ffmpeg version")


def test_system_info_skald_ffmpeg_precedence_and_subprocess_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg-custom"
    fake_ffmpeg.write_text("placeholder", encoding="utf-8")

    monkeypatch.setenv("SKALD_FFMPEG", str(fake_ffmpeg))
    monkeypatch.setenv("SKALD_VENDOR", str(tmp_path / "unused-vendor"))

    seen_calls: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        seen_calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(
            returncode=0,
            stdout="ffmpeg version 9.0.2-fake Copyright\nconfiguration: --enable-version3\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    info = get_system_info()
    assert info.ffmpeg == "ffmpeg version 9.0.2-fake Copyright"
    assert len(seen_calls) == 1
    assert seen_calls[0]["cmd"] == [str(fake_ffmpeg), "-version"]
    assert seen_calls[0]["stdin"] is subprocess.DEVNULL
    assert seen_calls[0]["capture_output"] is True
    assert isinstance(seen_calls[0]["timeout"], (int, float))


def test_system_info_uses_skald_vendor_platform_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plat = "win64" if platform.system().lower() == "windows" else "linux64"
    expected_bin = tmp_path / "ffmpeg" / plat / FFMPEG_BIN_BY_PLATFORM[plat]
    expected_bin.parent.mkdir(parents=True)
    expected_bin.write_text("placeholder", encoding="utf-8")

    monkeypatch.delenv("SKALD_FFMPEG", raising=False)
    monkeypatch.setenv("SKALD_VENDOR", str(tmp_path))

    seen_cmds: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        seen_cmds.append(cmd)
        return SimpleNamespace(returncode=0, stdout="ffmpeg version vendor-test\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    info = get_system_info()
    assert info.ffmpeg == "ffmpeg version vendor-test"
    assert seen_cmds == [[str(expected_bin), "-version"]]


def test_system_info_missing_ffmpeg_returns_none_and_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SKALD_FFMPEG", str(tmp_path / "does-not-exist"))
    monkeypatch.delenv("SKALD_VENDOR", raising=False)

    with caplog.at_level(logging.WARNING, logger="skald_core.rpc.system"):
        info = get_system_info()

    assert info.ffmpeg is None
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_system_info_failing_ffmpeg_returns_none_and_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg-bad"
    fake_ffmpeg.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("SKALD_FFMPEG", str(fake_ffmpeg))

    def fail_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="broken binary")

    monkeypatch.setattr(subprocess, "run", fail_run)

    with caplog.at_level(logging.WARNING, logger="skald_core.rpc.system"):
        info = get_system_info()

    assert info.ffmpeg is None
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_system_info_timeout_ffmpeg_returns_none_and_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg-slow"
    fake_ffmpeg.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("SKALD_FFMPEG", str(fake_ffmpeg))

    def slow_run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    monkeypatch.setattr(subprocess, "run", slow_run)

    with caplog.at_level(logging.WARNING, logger="skald_core.rpc.system"):
        info = get_system_info()

    assert info.ffmpeg is None
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


@pytest.mark.timeout(10)
def test_system_info_over_rpc_subprocess(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "SKALD_LOG_DIR": str(tmp_path),
        "SKALD_VENDOR": str(_REPO_ROOT / "vendor"),
    }
    env.pop("SKALD_FFMPEG", None)

    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.info"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "system.shutdown"}),
        ]
    )
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core"],
        input=f"{requests}\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    messages = [json.loads(line) for line in proc.stdout.splitlines() if line]
    assert len(messages) == 2
    assert messages[0]["id"] == 1
    result = messages[0]["result"]
    assert result["core"] == skald_core.__version__
    assert result["python"] == platform.python_version()
    assert result["lxml"] == lxml.__version__
    assert result["pydantic"] == pydantic.__version__
    assert result["numpy"] == numpy.__version__
    if os.environ.get("CI") == "true":
        assert isinstance(result["ffmpeg"], str)
        assert result["ffmpeg"].startswith("ffmpeg version")
    assert messages[1] == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}
