"""Tests for PackManager (unit tests with fake uv + slow real CPU smoke test)."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from skald_core.jobs import JobManager
from skald_core.packs import (
    MAX_PACK_NAME_LEN,
    PYTHON_BIN_BY_PLATFORM,
    UV_BIN_BY_PLATFORM,
    WINDOWS_MAX_PACK_PATH_LEN,
    PackManager,
    PackMetadata,
    lock_sha256,
    parse_lockfile,
)
from skald_core.rpc.server import SkaldError
from skald_core.storage import packs_dir, python_dir, uv_cache_dir

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE_UV_SCRIPT = """\
import json
import os
import sys
import time
from pathlib import Path

log_file = Path(os.environ["SKALD_FAKE_UV_LOG"])
with log_file.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "env": dict(os.environ)}) + "\\n")

args = sys.argv[1:]
if args == ["--version"]:
    print("uv 0.13.8-fake")
    sys.exit(0)

mode = os.environ.get("SKALD_FAKE_UV_MODE", "ok")

if args and args[0] == "venv":
    pack_dir = Path(args[-1])
    base_py = Path(args[args.index("--python") + 1])
    pack_dir.mkdir(parents=True, exist_ok=True)
    cfg = pack_dir / "pyvenv.cfg"
    cfg.write_text(f"home = {base_py.parent}\\nrelocatable = true\\n", encoding="utf-8")
    if os.name == "nt":
        py_bin = pack_dir / "Scripts" / "python.exe"
        py_bin.parent.mkdir(parents=True, exist_ok=True)
        if not py_bin.exists():
            launcher = base_py.parent / "Lib" / "venv" / "scripts" / "nt" / "python.exe"
            src = launcher if launcher.is_file() else Path(sys.executable)
            py_bin.write_bytes(src.read_bytes())
    else:
        py_bin = pack_dir / "bin" / "python"
        py_bin.parent.mkdir(parents=True, exist_ok=True)
        if not py_bin.exists():
            py_bin.symlink_to(sys.executable)
    print(f"Created venv at {pack_dir}")
    sys.exit(0)

if args[:2] == ["pip", "sync"]:
    if mode == "spam_35_and_fail":
        for idx in range(1, 36):
            print(f"sync line {idx:02d}")
        print("error: synthetic sync failure")
        sys.exit(1)
    if mode == "hash_mismatch":
        print("error: Hash mismatch for package torch")
        sys.exit(1)
    if mode == "offline":
        print("error: error sending request for url: Connection refused")
        sys.exit(2)
    if mode == "unknown_issuer":
        print("error: invalid peer certificate: UnknownIssuer")
        sys.exit(2)
    if mode == "sleep":
        marker = Path(os.environ["SKALD_FAKE_UV_SLEEP_MARKER"])
        marker.write_text("sleeping", encoding="utf-8")
        time.sleep(60)
        sys.exit(0)
    # Create cache dir artifact to simulate populated uv cache
    cache_dir = Path(os.environ["UV_CACHE_DIR"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "dummy.whl").write_text("cached", encoding="utf-8")
    print("Resolved and installed packages")
    sys.exit(0)

if args[:2] == ["pip", "install"]:
    print("Installed offline wheel")
    sys.exit(0)

if args[:2] == ["cache", "clean"]:
    print(f"Cleaned cache args={args[2:]}")
    sys.exit(0)

print(f"Unexpected args: {args}", file=sys.stderr)
sys.exit(2)
"""


class _NotifierRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.finished: dict[str, threading.Event] = {}

    def __call__(self, method: str, params: BaseModel | dict[str, Any]) -> None:
        payload = params.model_dump(mode="json") if isinstance(params, BaseModel) else dict(params)
        with self._lock:
            self.events.append((method, payload))
            if method == "job.finished":
                self.finished.setdefault(payload["job_id"], threading.Event()).set()

    def wait_finished(self, job_id: str, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            ev = self.finished.setdefault(job_id, threading.Event())
        assert ev.wait(timeout=timeout), f"Timed out waiting for job {job_id}"
        for method, payload in self.events:
            if method == "job.finished" and payload["job_id"] == job_id:
                return payload
        raise AssertionError(f"No job.finished event recorded for {job_id}")

    def stages(self, job_id: str) -> list[str]:
        with self._lock:
            out: list[str] = []
            for method, payload in self.events:
                if method == "job.progress" and payload["job_id"] == job_id:
                    stage = payload.get("stage", "")
                    if stage and (not out or out[-1] != stage):
                        out.append(stage)
            return out

    def logs(self, job_id: str) -> list[str]:
        with self._lock:
            return [
                payload["message"]
                for method, payload in self.events
                if method == "job.log" and payload["job_id"] == job_id
            ]


@pytest.fixture
def notifier() -> _NotifierRecorder:
    return _NotifierRecorder()


@pytest.fixture
def job_manager(notifier: _NotifierRecorder) -> Iterator[JobManager]:
    jm = JobManager(max_workers=2, notify_fn=notifier, progress_interval_s=0.0)
    try:
        yield jm
    finally:
        jm.shutdown(timeout=3.0)


@pytest.fixture
def short_tmp() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="sk_", ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


def _setup_fake_env(
    root_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    family: str = "demo-pack",
    check_code: str = 'print(\'{"worker_version": "0.1.0-test"}\')\n',
    write_check_py: bool = True,
    backend: str = "cpu",
    required_bytes: int = 1024,
    packages: tuple[str, ...] = ("torch==2.14.1+cpu", "filelock==4.2.10"),
) -> dict[str, Any]:
    storage = root_dir / "s"
    vendor = root_dir / "v"
    packs_src = root_dir / "p"
    log_file = root_dir / "fake_uv_calls.jsonl"
    fake_uv_script = root_dir / "fake_uv.py"
    fake_uv_script.write_text(_FAKE_UV_SCRIPT, encoding="utf-8")

    plat = "win64" if platform.system().lower() == "windows" else "linux64"
    os_name = "windows" if plat == "win64" else "linux"
    py_rel = PYTHON_BIN_BY_PLATFORM[plat]
    vendor_py_dir = vendor / "python" / plat
    vendor_py_bin = vendor_py_dir / py_rel
    vendor_py_bin.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        ignore = shutil.ignore_patterns(
            "site-packages",
            "test",
            "idlelib",
            "tkinter",
            "ensurepip",
            "__pycache__",
            "Tools",
            "include",
            "libs",
            "Scripts",
            "Doc",
            "tcl",
            "pydoc_data",
        )
        shutil.copytree(Path(sys.base_prefix), vendor_py_dir, dirs_exist_ok=True, ignore=ignore)
    else:
        vendor_py_bin.symlink_to(sys.executable)
    (vendor_py_dir / ".installed.json").write_text(
        json.dumps({"version": "3.12.16+20261110"}), encoding="utf-8"
    )

    pack_src = packs_src / family
    locks_dir = pack_src / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    accel = "cpu" if backend == "cpu" else "cu12"
    lock_file = locks_dir / f"{os_name}-{accel}.txt"
    lock_lines = [
        f"# skald-backend: {backend}",
        f"# skald-required-bytes: {required_bytes}",
        "# This file was autogenerated by uv",
    ]
    for pkg in packages:
        lock_lines.append(f"{pkg} \\")
        lock_lines.append(f"    --hash=sha256:{'a' * 64}")
    lock_file.write_text("\n".join(lock_lines) + "\n", encoding="utf-8")

    if write_check_py:
        (pack_src / "check.py").write_text(check_code, encoding="utf-8")

    monkeypatch.setenv("SKALD_FAKE_UV_LOG", str(log_file))
    monkeypatch.setenv("SKALD_FAKE_UV_MODE", "ok")
    monkeypatch.setenv("SKALD_STORAGE_DIR", str(storage))
    monkeypatch.setenv("SKALD_VENDOR", str(vendor))

    pm = PackManager(
        storage_dir=storage,
        packs_source_dir=packs_src,
        vendor_dir=vendor,
        uv_cmd=[sys.executable, fake_uv_script],
    )
    return {
        "pm": pm,
        "storage": storage,
        "vendor": vendor,
        "packs_src": packs_src,
        "lock_file": lock_file,
        "log_file": log_file,
        "os_name": os_name,
        "plat": plat,
        "py_rel": py_rel,
        "accel": accel,
    }


def _read_uv_calls(log_file: Path) -> list[dict[str, Any]]:
    if not log_file.is_file():
        return []
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line]


def test_uv_and_python_bin_constants_match_deps_lock() -> None:
    lock_data = json.loads((_REPO_ROOT / "scripts" / "deps.lock.json").read_text(encoding="utf-8"))

    uv_assets = lock_data["uv"]["assets"]
    assert set(UV_BIN_BY_PLATFORM.keys()) == set(uv_assets.keys())
    for plat, asset in uv_assets.items():
        assert UV_BIN_BY_PLATFORM[plat] == asset["bin"]

    py_assets = lock_data["python"]["assets"]
    assert set(PYTHON_BIN_BY_PLATFORM.keys()) == set(py_assets.keys())
    for plat, asset in py_assets.items():
        assert PYTHON_BIN_BY_PLATFORM[plat] == asset["bin"]


def test_lock_sha256_is_lf_normalised(tmp_path: Path) -> None:
    lf = tmp_path / "linux-cpu.txt"
    crlf = tmp_path / "windows-cpu.txt"
    content = (
        "# skald-backend: cpu\n# skald-required-bytes: 100\n"
        f"torch==2.14.1+cpu \\\n    --hash=sha256:{'a' * 64}\n"
    )
    lf.write_bytes(content.encode("utf-8"))
    crlf.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

    assert lock_sha256(lf) == lock_sha256(crlf)
    assert parse_lockfile(lf).hash8 == parse_lockfile(crlf).hash8


def test_fake_uv_install_checks_b5_env_base_python_and_idempotence(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    monkeypatch.setenv("UV_INDEX_URL", "https://should-be-stripped.example")
    monkeypatch.setenv("UV_EXTRA_INDEX_URL", "https://also-stripped.example")
    monkeypatch.setenv("UV_INSECURE_HOST", "evil.example")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9998")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/custom-ca.pem")

    env_info = _setup_fake_env(short_tmp, monkeypatch)
    pm: PackManager = env_info["pm"]
    storage: Path = env_info["storage"]
    vendor: Path = env_info["vendor"]
    log_file: Path = env_info["log_file"]

    j1 = pm.submit_install(job_manager, "demo-pack")
    fin1 = notifier.wait_finished(j1)
    assert fin1["status"] == "succeeded"
    assert notifier.stages(j1) == ["venv", "sync", "worker", "check", "finalize"]

    calls = _read_uv_calls(log_file)
    # Expect venv, sync, --version (worker skipped because None)
    assert [c["argv"][:2] for c in calls] == [
        ["venv", "--python"],
        ["pip", "sync"],
        ["--version"],
    ]
    sync_argv = calls[1]["argv"]
    assert "--require-hashes" in sync_argv
    assert "--no-build" in sync_argv
    assert "--torch-backend" in sync_argv

    for call in calls:
        uv_env = call["env"]
        assert uv_env["UV_NO_CONFIG"] == "1"
        assert uv_env["UV_CACHE_DIR"] == str(uv_cache_dir(storage))
        assert uv_env["UV_LINK_MODE"] == "hardlink"
        assert uv_env["UV_PYTHON_DOWNLOADS"] == "never"
        assert uv_env["UV_SYSTEM_CERTS"] == "1"
        assert uv_env["UV_NO_PROGRESS"] == "1"
        assert "UV_INDEX_URL" not in uv_env
        assert "UV_EXTRA_INDEX_URL" not in uv_env
        assert "UV_INSECURE_HOST" not in uv_env
        assert uv_env["HTTPS_PROXY"] == "http://127.0.0.1:9999"
        assert uv_env["HTTP_PROXY"] == "http://127.0.0.1:9998"
        assert uv_env["NO_PROXY"] == "localhost,127.0.0.1"
        assert uv_env["SSL_CERT_FILE"] == "/tmp/custom-ca.pem"

    # Base Python copied into <storage>/python/<pbs-version>/ and used for venv
    copied_base_dir = python_dir(storage) / "3.12.16+20261110"
    copied_base_exe = copied_base_dir / env_info["py_rel"]
    assert copied_base_exe.is_file()
    venv_python_arg = Path(calls[0]["argv"][calls[0]["argv"].index("--python") + 1])
    assert venv_python_arg == copied_base_exe
    assert vendor not in venv_python_arg.parents

    pack_dir = Path(fin1["result"]["pack_dir"])
    assert len(pack_dir.name) <= MAX_PACK_NAME_LEN
    assert pm.is_valid_pack(pack_dir)
    meta = PackMetadata.model_validate(fin1["result"]["metadata"])
    assert meta.worker_version == "0.1.0-test"
    assert meta.min_nvidia_driver is None

    # Installing a second time is idempotent: no new venv/sync calls
    before_count = len(_read_uv_calls(log_file))
    j2 = pm.submit_install(job_manager, "demo-pack")
    fin2 = notifier.wait_finished(j2)
    assert fin2["status"] == "succeeded"
    assert fin2["result"]["pack_dir"] == str(pack_dir)
    assert len(_read_uv_calls(log_file)) == before_count


def test_worker_wheel_installed_and_default_check_command(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    env_info = _setup_fake_env(short_tmp, monkeypatch, write_check_py=False)
    pm: PackManager = env_info["pm"]
    fake_wheel = short_tmp / "skald_worker-0.1.0-py3-none-any.whl"
    fake_wheel.write_text("wheel", encoding="utf-8")

    seen_cmds: list[list[str]] = []
    orig_popen = subprocess.Popen

    class _MockCheckPopen:
        def __init__(self, cmd: list[str], **_kwargs: Any) -> None:
            self.pid = os.getpid()
            self.returncode = 0
            self.stdout = iter(['{"worker_version": "0.1.0"}\n'])

        def __enter__(self) -> _MockCheckPopen:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def spy_popen(cmd: list[str], **kwargs: Any) -> Any:
        assert kwargs.get("stdout") is subprocess.PIPE
        if "-m" in cmd and "skald_worker" in cmd:
            seen_cmds.append(cmd)
            return _MockCheckPopen(cmd)
        return orig_popen(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy_popen)

    job_id = pm.submit_install(job_manager, "demo-pack", worker_wheel=fake_wheel)
    fin = notifier.wait_finished(job_id)
    assert fin["status"] == "succeeded"

    calls = _read_uv_calls(env_info["log_file"])
    assert [c["argv"][:2] for c in calls] == [
        ["venv", "--python"],
        ["pip", "sync"],
        ["pip", "install"],
        ["--version"],
    ]
    worker_argv = calls[2]["argv"]
    assert "--offline" in worker_argv
    assert "--no-index" in worker_argv
    assert "--no-deps" in worker_argv
    assert str(fake_wheel) in worker_argv
    assert len(seen_cmds) == 1
    assert seen_cmds[0][-5:] == [
        "-m",
        "skald_worker",
        "--adapter",
        "demo-pack",
        "--check",
    ]
    assert "--check" in seen_cmds[0]


def test_lock_hash_mismatch_and_tampered_sync_fail_without_valid_pack(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    env_info = _setup_fake_env(short_tmp, monkeypatch)
    pm: PackManager = env_info["pm"]

    # 1. Expected lockfile SHA-256 mismatch fails before touching disk
    j_expected = pm.submit_install(job_manager, "demo-pack", expected_lock_sha256="0" * 64)
    fin_expected = notifier.wait_finished(j_expected)
    assert fin_expected["status"] == "failed"
    assert fin_expected["error"]["data"]["kind"] == "checksum_mismatch"
    assert pm.list_packs() == {}

    # 2. Tampered package hash during `uv pip sync --require-hashes` fails cleanly
    monkeypatch.setenv("SKALD_FAKE_UV_MODE", "hash_mismatch")
    j_tamper = pm.submit_install(job_manager, "demo-pack")
    fin_tamper = notifier.wait_finished(j_tamper)
    assert fin_tamper["status"] == "failed"
    assert fin_tamper["error"]["data"]["kind"] == "pack_install_failed"
    assert any("Hash mismatch" in ln for ln in fin_tamper["error"]["data"]["details"]["log_tail"])
    assert pm.list_packs() == {}


def test_sync_succeeds_but_step4_check_fails_leaves_no_valid_pack(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    env_info = _setup_fake_env(
        short_tmp,
        monkeypatch,
        check_code='import sys; print("simulated DLL path failure"); sys.exit(1)\n',
    )
    pm: PackManager = env_info["pm"]

    job_id = pm.submit_install(job_manager, "demo-pack")
    fin = notifier.wait_finished(job_id)
    assert fin["status"] == "failed"
    assert fin["error"]["data"]["kind"] == "pack_install_failed"
    assert fin["error"]["data"]["details"]["stage"] == "check"
    assert pm.list_packs() == {}
    p_dir = packs_dir(env_info["storage"])
    assert not any(p_dir.iterdir()) if p_dir.exists() else True


def test_kill_midway_leaves_no_valid_pack_and_repair_rebuilds(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    sleep_marker = short_tmp / "sync_sleeping"
    monkeypatch.setenv("SKALD_FAKE_UV_SLEEP_MARKER", str(sleep_marker))
    env_info = _setup_fake_env(short_tmp, monkeypatch)
    pm: PackManager = env_info["pm"]
    monkeypatch.setenv("SKALD_FAKE_UV_MODE", "sleep")

    job_id = pm.submit_install(job_manager, "demo-pack")
    deadline = time.monotonic() + 5.0
    while not sleep_marker.is_file():
        assert time.monotonic() < deadline
        time.sleep(0.01)

    job_manager.cancel(job_id)
    fin = notifier.wait_finished(job_id, timeout=3.0)
    assert fin["status"] == "cancelled"
    assert pm.list_packs() == {}

    # A leftover half-built folder without pack.json is never valid; repair rebuilds it.
    lock_info = parse_lockfile(env_info["lock_file"])
    pack_dir = pm.pack_dir_for("demo-pack", lock_info)
    (pack_dir / "lib").mkdir(parents=True)
    (pack_dir / "lib" / "partial.txt").write_text("half built", encoding="utf-8")
    assert not pm.is_valid_pack(pack_dir)
    assert pm.list_packs() == {}

    monkeypatch.setenv("SKALD_FAKE_UV_MODE", "ok")
    repair_id = pm.submit_repair(job_manager, "demo-pack")
    fin_repair = notifier.wait_finished(repair_id)
    assert fin_repair["status"] == "succeeded"
    assert pm.is_valid_pack(pack_dir)
    assert list(pm.list_packs().keys()) == [pack_dir]


def test_clean_only_when_no_pack_remains_and_unused_python_removed(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    env_info = _setup_fake_env(
        short_tmp,
        monkeypatch,
        family="pack-one",
        packages=("torch==2.14.1+cpu", "unique-one==1.0.0"),
    )
    pm: PackManager = env_info["pm"]
    packs_src: Path = env_info["packs_src"]
    log_file: Path = env_info["log_file"]
    os_name: str = env_info["os_name"]

    pack_two_src = packs_src / "pack-two" / "locks"
    pack_two_src.mkdir(parents=True)
    (pack_two_src / f"{os_name}-cpu.txt").write_text(
        "# skald-backend: cpu\n# skald-required-bytes: 1024\n"
        f"torch==2.14.1+cpu \\\n    --hash=sha256:{'b' * 64}\n",
        encoding="utf-8",
    )
    (packs_src / "pack-two" / "check.py").write_text("print('ok')\n", encoding="utf-8")

    j1 = pm.submit_install(job_manager, "pack-one")
    j2 = pm.submit_install(job_manager, "pack-two")
    assert notifier.wait_finished(j1)["status"] == "succeeded"
    assert notifier.wait_finished(j2)["status"] == "succeeded"
    assert len(pm.list_packs()) == 2

    # Remove pack-two (whose only package `torch` is still used by pack-one) -> NO `cache clean`!
    before_calls = len(_read_uv_calls(log_file))
    res_two = pm.remove("pack-two")
    assert res_two["cache_cleaned"] == "none"
    after_two = _read_uv_calls(log_file)[before_calls:]
    assert not any(c["argv"][:2] == ["cache", "clean"] for c in after_two)
    assert (python_dir(env_info["storage"]) / "3.12.16+20261110").is_dir()

    # Reinstall pack-two, then remove pack-one first: `unique-one` is orphaned, `torch` is kept
    j2_again = pm.submit_install(job_manager, "pack-two")
    assert notifier.wait_finished(j2_again)["status"] == "succeeded"
    before_one = len(_read_uv_calls(log_file))
    res_one = pm.remove("pack-one")
    assert res_one["cache_cleaned"] == "packages"
    after_one = _read_uv_calls(log_file)[before_one:]
    assert ["cache", "clean", "unique-one"] in [c["argv"] for c in after_one]
    assert ["cache", "clean"] not in [c["argv"] for c in after_one]

    # Removing the final pack runs bare `cache clean` and removes unused python dir
    before_last = len(_read_uv_calls(log_file))
    res_last = pm.remove("pack-two")
    assert res_last["cache_cleaned"] == "all"
    after_last = _read_uv_calls(log_file)[before_last:]
    assert ["cache", "clean"] in [c["argv"] for c in after_last]
    assert not (python_dir(env_info["storage"]) / "3.12.16+20261110").exists()


def test_error_mapping_log_tail_limit_and_disk_check(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    env_info = _setup_fake_env(short_tmp, monkeypatch)
    pm: PackManager = env_info["pm"]

    # 1. >30 log lines -> pack_install_failed keeps only the last 30 lines
    monkeypatch.setenv("SKALD_FAKE_UV_MODE", "spam_35_and_fail")
    j_spam = pm.submit_install(job_manager, "demo-pack")
    fin_spam = notifier.wait_finished(j_spam)
    assert fin_spam["status"] == "failed"
    assert fin_spam["error"]["data"]["kind"] == "pack_install_failed"
    tail = fin_spam["error"]["data"]["details"]["log_tail"]
    assert len(tail) == 30
    assert tail[-1] == "error: synthetic sync failure"
    assert tail[0] == "sync line 07"

    # 2. Offline detection
    monkeypatch.setenv("SKALD_FAKE_UV_MODE", "offline")
    j_off = pm.submit_install(job_manager, "demo-pack")
    fin_off = notifier.wait_finished(j_off)
    assert fin_off["status"] == "failed"
    assert fin_off["error"]["data"]["kind"] == "offline"

    # 3. UnknownIssuer proxy hint
    monkeypatch.setenv("SKALD_FAKE_UV_MODE", "unknown_issuer")
    j_tls = pm.submit_install(job_manager, "demo-pack")
    fin_tls = notifier.wait_finished(j_tls)
    assert fin_tls["status"] == "failed"
    assert fin_tls["error"]["data"]["kind"] == "pack_install_failed"
    assert "HTTPS" in fin_tls["error"]["data"]["hint"]

    # 4. Free-disk check
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _p: SimpleNamespace(total=1000, used=900, free=100)
    )
    j_disk = pm.submit_install(job_manager, "demo-pack")
    fin_disk = notifier.wait_finished(j_disk)
    assert fin_disk["status"] == "failed"
    assert fin_disk["error"]["data"]["kind"] == "not_enough_disk"


def test_windows_150_char_path_limit_and_name_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deep_storage = tmp_path / ("x" * 110)
    pm = PackManager(storage_dir=deep_storage)
    lock_file = _REPO_ROOT / "packs" / "torch-cpu-smoke" / "locks" / "windows-cpu.txt"
    lock_info = parse_lockfile(lock_file)

    with pytest.raises(SkaldError) as exc_info:
        pm.pack_dir_for("torch-cpu-smoke", lock_info, storage_dir=deep_storage, os_name="windows")
    assert exc_info.value.kind == "pack_install_failed"
    assert str(WINDOWS_MAX_PACK_PATH_LEN) in exc_info.value.message

    with pytest.raises(SkaldError) as name_exc:
        pm.pack_dir_for(
            "very-long-model-family-name", lock_info, storage_dir=tmp_path, os_name="windows"
        )
    assert name_exc.value.kind == "pack_install_failed"


def test_cu12_lockfile_records_cuda_driver_metadata_without_gpu(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    env_info = _setup_fake_env(
        short_tmp,
        monkeypatch,
        family="torch-cu12-smoke",
        backend="cu126",
        required_bytes=1024,
    )
    pm: PackManager = env_info["pm"]

    job_id = pm.submit_install(job_manager, "torch-cu12-smoke")
    fin = notifier.wait_finished(job_id)
    assert fin["status"] == "succeeded", fin

    meta = PackMetadata.model_validate(fin["result"]["metadata"])
    expected_driver = "528.33" if env_info["os_name"] == "windows" else "525.60.13"
    assert meta.min_nvidia_driver == expected_driver
    assert (
        meta.nvidia_driver_source
        == "https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html"
    )
    assert meta.min_nvidia_driver_reason is not None
    assert "PyTorch wheels bundle the CUDA 12.6 runtime" in meta.min_nvidia_driver_reason


def test_repoints_base_python_when_pyvenv_cfg_home_differs(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    env_info = _setup_fake_env(short_tmp, monkeypatch)
    pm: PackManager = env_info["pm"]
    log_file: Path = env_info["log_file"]

    j1 = pm.submit_install(job_manager, "demo-pack")
    fin1 = notifier.wait_finished(j1)
    assert fin1["status"] == "succeeded", fin1
    pack_dir = Path(fin1["result"]["pack_dir"])

    # Simulate stale base Python path in pyvenv.cfg (e.g. after app update or move)
    cfg = pack_dir / "pyvenv.cfg"
    cfg.write_text("home = /old/moved/python/bin\nrelocatable = true\n", encoding="utf-8")

    before = len(_read_uv_calls(log_file))
    j2 = pm.submit_install(job_manager, "demo-pack")
    fin2 = notifier.wait_finished(j2)
    assert fin2["status"] == "succeeded", fin2

    new_calls = _read_uv_calls(log_file)[before:]
    assert len(new_calls) == 1
    assert "--allow-existing" in new_calls[0]["argv"]
    assert "--relocatable" in new_calls[0]["argv"]


@pytest.mark.slow
@pytest.mark.timeout(300)
def test_real_cpu_smoke_pack_install_idempotent_and_remove(
    short_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_manager: JobManager,
    notifier: _NotifierRecorder,
) -> None:
    monkeypatch.setenv("SKALD_STORAGE_DIR", str(short_tmp))
    monkeypatch.setenv("SKALD_VENDOR", str(_REPO_ROOT / "vendor"))

    pm = PackManager(
        storage_dir=short_tmp,
        packs_source_dir=_REPO_ROOT / "packs",
        vendor_dir=_REPO_ROOT / "vendor",
    )

    t0 = time.perf_counter()
    j1 = pm.submit_install(job_manager, "torch-cpu-smoke")
    fin1 = notifier.wait_finished(j1, timeout=240.0)
    first_s = time.perf_counter() - t0
    assert fin1["status"] == "succeeded", fin1

    pack_dir = Path(fin1["result"]["pack_dir"])
    assert pm.is_valid_pack(pack_dir)
    meta = pm.read_pack_metadata(pack_dir)
    assert meta is not None and meta.accel == "cpu"

    storage_before_remove = sum(
        p.stat().st_size for p in short_tmp.rglob("*") if p.is_file() and not p.is_symlink()
    )

    # Second install must be idempotent and fast
    t1 = time.perf_counter()
    j2 = pm.submit_install(job_manager, "torch-cpu-smoke")
    fin2 = notifier.wait_finished(j2, timeout=30.0)
    second_s = time.perf_counter() - t1
    assert fin2["status"] == "succeeded", fin2
    assert fin2["result"]["pack_dir"] == str(pack_dir)
    assert second_s < max(5.0, first_s)

    # Removing the sole pack deletes pack, copied base python, and cleans uv-cache
    rem = pm.remove("torch-cpu-smoke")
    storage_after_remove = sum(
        p.stat().st_size for p in short_tmp.rglob("*") if p.is_file() and not p.is_symlink()
    )
    print(
        f"CPU smoke install: first={first_s:.2f}s, second={second_s:.2f}s, "
        f"storage_before_remove={storage_before_remove / 1_000_000:.1f} MB, "
        f"storage_after_remove={storage_after_remove / 1_000:.1f} KB"
    )
    assert rem["cache_cleaned"] == "all"
    assert pm.list_packs() == {}
    assert not pack_dir.exists()
    assert not any((short_tmp / "python").glob("*")) if (short_tmp / "python").exists() else True
