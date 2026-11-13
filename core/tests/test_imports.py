"""Smoke tests verifying all runtime dependencies import and CLI basics work."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_runtime_imports() -> None:
    import lxml.etree
    import numpy
    import psutil
    import pydantic
    import pysbd
    import requests
    import soundfile

    import skald_core

    assert skald_core.__version__ == "0.1.0"
    assert lxml.etree is not None
    assert numpy.__version__
    assert psutil.__version__
    assert pydantic.__version__
    assert pysbd.__version__
    assert requests.__version__
    assert soundfile.__version__


def test_cli_version() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "0.1.0"
    assert proc.stderr == ""


@pytest.mark.parametrize("arg", ["--versio", "--unknown", "extra"])
def test_cli_unknown_or_abbreviated_arg_exits_2(arg: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core", arg],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    lines = proc.stderr.strip().splitlines()
    assert len(lines) == 1
    assert "Usage:" in lines[0]


@pytest.mark.timeout(10)
def test_cli_no_args_starts_server_and_exits_cleanly_on_eof(tmp_path: Path) -> None:
    env = {**os.environ, "SKALD_LOG_DIR": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core"],
        input="",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert "Traceback" not in proc.stderr
