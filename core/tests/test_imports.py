"""Smoke tests verifying all runtime dependencies import and CLI basics work."""

import subprocess
import sys


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


def test_cli_no_args_prints_nothing_to_stdout() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.strip() != ""
