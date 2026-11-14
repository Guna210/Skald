"""Unit and integration tests for the background job manager and job.* RPC methods."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psutil
import pytest
from pydantic import BaseModel

from skald_core.jobs import JobCancelled, JobContext, JobManager, UnknownJobError
from skald_core.rpc import (
    APP_ERROR,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    RpcServer,
    SkaldError,
)
from skald_core.rpc.methods import register_all
from skald_core.schemas import JobFinished, JobLog, JobProgress, JobRef

_JOB_ID_RE = re.compile(r"^j_[a-z0-9]{8}$")


class _RecordingNotifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.finished_events: dict[str, threading.Event] = {}

    def __call__(self, method: str, params: BaseModel | dict[str, Any]) -> None:
        payload = params.model_dump(mode="json") if isinstance(params, BaseModel) else dict(params)
        with self._lock:
            self.events.append((method, payload))
            if method == "job.finished":
                ev = self.finished_events.setdefault(payload["job_id"], threading.Event())
                ev.set()

    def wait_finished(self, job_id: str, timeout: float = 5.0) -> dict[str, Any]:
        with self._lock:
            ev = self.finished_events.setdefault(job_id, threading.Event())
        assert ev.wait(timeout=timeout), f"Timed out waiting for job.finished on {job_id}"
        matches = [p for m, p in self.by_method("job.finished") if p["job_id"] == job_id]
        assert len(matches) == 1, f"Expected 1 job.finished for {job_id}, got {matches}"
        return matches[0]

    def by_method(self, method: str) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            return [(m, p) for m, p in self.events if m == method]

    def snapshot(self) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            return list(self.events)


@pytest.fixture
def notifier() -> _RecordingNotifier:
    return _RecordingNotifier()


@pytest.fixture
def manager(notifier: _RecordingNotifier) -> Iterator[JobManager]:
    jm = JobManager(max_workers=2, notify_fn=notifier)
    try:
        yield jm
    finally:
        jm.shutdown(timeout=2.0)


def test_job_id_format_and_job_ref(manager: JobManager) -> None:
    done = threading.Event()
    job_id = manager.submit("test.noop", lambda ctx: done.set() or {"ok": True})
    assert _JOB_ID_RE.match(job_id)
    assert JobRef(job_id=job_id).job_id == job_id
    assert done.wait(timeout=2.0)


def test_job_success_with_dict_and_pydantic_result_and_unthrottled_logs(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    def run_dict(ctx: JobContext, value: int) -> dict[str, int]:
        ctx.log("info", "step 1")
        ctx.log("debug", "step 2")
        ctx.progress(1.0, "done", "finish")
        return {"doubled": value * 2}

    def run_model(ctx: JobContext) -> JobRef:
        return JobRef(job_id=ctx.job_id)

    j1 = manager.submit("test.dict", run_dict, value=21)
    j2 = manager.submit("test.model", run_model)

    fin1 = notifier.wait_finished(j1)
    fin2 = notifier.wait_finished(j2)

    JobFinished.model_validate(fin1)
    JobFinished.model_validate(fin2)
    assert fin1 == {"job_id": j1, "status": "succeeded", "result": {"doubled": 42}, "error": None}
    assert fin2 == {"job_id": j2, "status": "succeeded", "result": {"job_id": j2}, "error": None}

    logs = [JobLog.model_validate(p) for _, p in notifier.by_method("job.log") if p["job_id"] == j1]
    assert [(entry.level, entry.message) for entry in logs] == [
        ("info", "step 1"),
        ("debug", "step 2"),
    ]
    status1 = manager.status(j1)
    assert status1.status == "succeeded"
    assert status1.result == {"doubled": 42}
    assert status1.fraction == 1.0


def test_job_failure_skald_error_and_unexpected_exception(
    manager: JobManager,
    notifier: _RecordingNotifier,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_skald(ctx: JobContext) -> None:
        raise SkaldError(
            "epub_drm",
            "Book has DRM",
            details={"file": "locked.epub"},
            hint="Use a DRM-free EPUB.",
        )

    def fail_unexpected(ctx: JobContext) -> None:
        raise ValueError("unexpected kaboom")

    j1 = manager.submit("test.skald_err", fail_skald)
    with caplog.at_level(logging.ERROR, logger="skald_core.jobs.manager"):
        j2 = manager.submit("test.boom", fail_unexpected)
        fin1 = notifier.wait_finished(j1)
        fin2 = notifier.wait_finished(j2)

    assert fin1["status"] == "failed"
    assert fin1["result"] is None
    assert fin1["error"] == {
        "code": APP_ERROR,
        "message": "Book has DRM",
        "data": {
            "kind": "epub_drm",
            "details": {"file": "locked.epub"},
            "hint": "Use a DRM-free EPUB.",
        },
    }

    assert fin2["status"] == "failed"
    assert fin2["error"]["code"] == INTERNAL_ERROR
    assert fin2["error"]["data"] == {
        "kind": "internal",
        "details": "unexpected kaboom",
        "hint": None,
    }
    assert any(
        rec.exc_info is not None and "unexpected kaboom" in rec.getMessage() + repr(rec.exc_info)
        for rec in caplog.records
    )


@pytest.mark.timeout(10)
def test_cancel_running_subprocess_kills_process_tree_within_2s(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    registered = threading.Event()
    pid_holder: list[int] = []

    def run_sleep(ctx: JobContext) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid_holder.append(proc.pid)
        ctx.register_subprocess(proc)
        registered.set()
        proc.wait()
        ctx.checkpoint()

    job_id = manager.submit("test.sleep", run_sleep)
    assert registered.wait(timeout=3.0)
    child_pid = pid_holder[0]
    assert psutil.pid_exists(child_pid)

    t0 = time.monotonic()
    manager.cancel(job_id)
    fin = notifier.wait_finished(job_id, timeout=2.0)
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0
    assert fin["status"] == "cancelled"
    assert manager.status(job_id).status == "cancelled"
    assert not psutil.pid_exists(child_pid)


def test_cancel_requested_while_fn_raises_other_exception_becomes_cancelled(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    started = threading.Event()
    proceed = threading.Event()

    def run_job(ctx: JobContext) -> None:
        started.set()
        assert proceed.wait(timeout=3.0)
        raise OSError("broken pipe after kill")

    job_id = manager.submit("test.race", run_job)
    assert started.wait(timeout=2.0)
    manager.cancel(job_id)
    proceed.set()

    fin = notifier.wait_finished(job_id)
    assert fin["status"] == "cancelled"
    assert fin["error"] is None


def test_pause_and_resume_at_checkpoint(manager: JobManager, notifier: _RecordingNotifier) -> None:
    at_step1 = threading.Event()
    allow_checkpoint1 = threading.Event()
    passed_checkpoint1 = threading.Event()

    def run_job(ctx: JobContext) -> dict[str, bool]:
        at_step1.set()
        assert allow_checkpoint1.wait(timeout=3.0)
        ctx.checkpoint()
        passed_checkpoint1.set()
        return {"done": True}

    job_id = manager.submit("test.pause", run_job)
    assert at_step1.wait(timeout=2.0)

    paused_status = manager.pause(job_id)
    assert paused_status.status == "paused"

    allow_checkpoint1.set()
    assert not passed_checkpoint1.wait(timeout=0.05)
    assert manager.status(job_id).status == "paused"

    resumed_status = manager.resume(job_id)
    assert resumed_status.status == "running"
    assert passed_checkpoint1.wait(timeout=2.0)

    fin = notifier.wait_finished(job_id)
    assert fin["status"] == "succeeded"
    assert fin["result"] == {"done": True}


def test_pause_and_resume_while_queued(notifier: _RecordingNotifier) -> None:
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        gate1 = threading.Event()
        started1 = threading.Event()
        started2 = threading.Event()
        ran3 = threading.Event()

        def job1(ctx: JobContext) -> str:
            started1.set()
            assert gate1.wait(timeout=3.0)
            return "one"

        def job2(ctx: JobContext) -> str:
            started2.set()
            return "two"

        def job3(ctx: JobContext) -> str:
            ran3.set()
            return "three"

        j1 = jm.submit("test.j1", job1)
        assert started1.wait(timeout=2.0)

        j2 = jm.submit("test.j2", job2)
        assert jm.status(j2).status == "queued"

        paused = jm.pause(j2)
        assert paused.status == "paused"

        j3 = jm.submit("test.j3", job3)
        gate1.set()

        assert notifier.wait_finished(j1)["status"] == "succeeded"
        assert notifier.wait_finished(j3)["status"] == "succeeded"
        assert ran3.is_set()
        assert not started2.wait(timeout=0.05)
        assert jm.status(j2).status == "paused"

        resumed = jm.resume(j2)
        assert resumed.status in ("queued", "running", "succeeded")
        assert started2.wait(timeout=2.0)
        assert notifier.wait_finished(j2)["result"] == "two"
    finally:
        jm.shutdown(timeout=2.0)


def test_cancel_while_paused_unblocks_checkpoint(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    ready_to_pause = threading.Event()
    enter_checkpoint = threading.Event()
    saw_job_cancelled = threading.Event()

    def run_job(ctx: JobContext) -> None:
        ready_to_pause.set()
        assert enter_checkpoint.wait(timeout=3.0)
        try:
            ctx.checkpoint()
        except JobCancelled:
            saw_job_cancelled.set()
            raise

    job_id = manager.submit("test.cancel_paused", run_job)
    assert ready_to_pause.wait(timeout=2.0)
    assert manager.pause(job_id).status == "paused"
    enter_checkpoint.set()
    # Yield briefly so the worker enters resume_event.wait() inside checkpoint().
    time.sleep(0.02)

    manager.cancel(job_id)
    assert saw_job_cancelled.wait(timeout=2.0)
    fin = notifier.wait_finished(job_id)
    assert fin["status"] == "cancelled"


def test_cancel_while_queued_never_runs(notifier: _RecordingNotifier) -> None:
    jm = JobManager(max_workers=1, notify_fn=notifier)
    try:
        started1 = threading.Event()
        gate1 = threading.Event()
        ran2 = threading.Event()

        def job1(ctx: JobContext) -> str:
            started1.set()
            assert gate1.wait(timeout=3.0)
            return "done"

        def job2(ctx: JobContext) -> str:
            ran2.set()
            return "should_not_run"

        j1 = jm.submit("test.j1", job1)
        assert started1.wait(timeout=2.0)

        j2 = jm.submit("test.j2", job2)
        cancelled = jm.cancel(j2)
        assert cancelled.status == "cancelled"

        fin2 = notifier.wait_finished(j2)
        assert fin2["status"] == "cancelled"

        gate1.set()
        assert notifier.wait_finished(j1)["status"] == "succeeded"
        jm.shutdown(timeout=2.0)
        assert not ran2.is_set()
    finally:
        jm.shutdown(timeout=2.0)


def test_idempotent_control_on_finished_job_and_unknown_job_id() -> None:
    stdin = io.BytesIO()
    stdout = io.BytesIO()
    server = RpcServer(stdin=stdin, stdout=stdout)
    jm = register_all(server)
    try:
        j1 = jm.submit("test.fast", lambda ctx: {"val": 7})
        # Wait until j1 finishes via polling or event.
        deadline = time.monotonic() + 2.0
        while jm.status(j1).status != "succeeded":
            assert time.monotonic() < deadline
            time.sleep(0.005)

        expected = jm.status(j1).model_dump(mode="json")
        for method in ("job.cancel", "job.pause", "job.resume", "job.status"):
            req = {
                "jsonrpc": "2.0",
                "id": method,
                "method": method,
                "params": {"job_id": j1},
            }
            resp = server.handle_line(json.dumps(req))
            assert resp == {"jsonrpc": "2.0", "id": method, "result": expected}

        for method in ("job.cancel", "job.pause", "job.resume", "job.status"):
            resp = server.handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": f"missing-{method}",
                        "method": method,
                        "params": {"job_id": "j_missing1"},
                    }
                )
            )
            assert resp is not None
            assert resp["error"]["code"] == INVALID_PARAMS
            assert resp["error"]["data"]["kind"] == "internal"

        with pytest.raises(UnknownJobError):
            jm.status("j_missing1")
    finally:
        jm.shutdown(timeout=2.0)


def test_progress_throttling_deterministic_coalesce_and_flush_before_finished(
    notifier: _RecordingNotifier,
) -> None:
    clock = [0.0]
    jm = JobManager(
        max_workers=1,
        notify_fn=notifier,
        progress_interval_s=0.1,
        time_fn=lambda: clock[0],
    )
    try:

        def run_job(ctx: JobContext) -> str:
            ctx.progress(0.0, "start", "s0")
            clock[0] = 0.02
            ctx.progress(0.2, "skip1", "s1")
            clock[0] = 0.05
            ctx.progress(0.5, "keep-until-0.11", "s2")
            clock[0] = 0.11
            ctx.progress(0.7, "second-emit", "s3")
            clock[0] = 0.13
            ctx.progress(0.9, "superseded", "s4")
            clock[0] = 0.15
            ctx.progress(1.0, "final-pending", "s5")
            return "ok"

        job_id = jm.submit("test.throttle_clock", run_job)
        notifier.wait_finished(job_id)

        events = [
            (m, p)
            for m, p in notifier.snapshot()
            if p.get("job_id") == job_id and m in ("job.progress", "job.finished")
        ]
        assert [m for m, _ in events] == [
            "job.progress",
            "job.progress",
            "job.progress",
            "job.finished",
        ]
        progress_items = [JobProgress.model_validate(p) for m, p in events if m == "job.progress"]
        assert [(p.fraction, p.message) for p in progress_items] == [
            (0.0, "start"),
            (0.7, "second-emit"),
            (1.0, "final-pending"),
        ]
    finally:
        jm.shutdown(timeout=2.0)


def test_progress_throttling_real_clock_rate_limit(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    def burst(ctx: JobContext) -> str:
        for idx in range(1, 51):
            ctx.progress(idx / 50.0, f"step {idx}", "burst")
            time.sleep(0.004)
        return "done"

    t0 = time.monotonic()
    job_id = manager.submit("test.throttle_real", burst)
    notifier.wait_finished(job_id)
    elapsed = time.monotonic() - t0

    events = [
        (m, p)
        for m, p in notifier.snapshot()
        if p.get("job_id") == job_id and m in ("job.progress", "job.finished")
    ]
    assert events[-1][0] == "job.finished"
    progress_list = [p for m, p in events if m == "job.progress"]
    # At most 10/s during the run plus 1 trailing flush before job.finished.
    max_allowed = int(elapsed * 10) + 2
    assert len(progress_list) <= max_allowed
    assert progress_list[-1]["fraction"] == 1.0
    assert progress_list[-1]["message"] == "step 50"


@pytest.mark.timeout(10)
def test_cancel_kills_process_tree_including_grandchild(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    child_code = (
        "import subprocess, sys, time; "
        "c = subprocess.Popen("
        "[sys.executable, '-c', 'import time; time.sleep(60)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "print(c.pid, flush=True); "
        "c.wait()"
    )
    registered = threading.Event()
    pids: list[int] = []

    def run_tree(ctx: JobContext) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdout is not None
        grandchild_pid = int(proc.stdout.readline().strip())
        pids.extend([proc.pid, grandchild_pid])
        ctx.register_subprocess(proc)
        registered.set()
        proc.wait()
        ctx.checkpoint()

    job_id = manager.submit("test.tree", run_tree)
    assert registered.wait(timeout=3.0)
    parent_pid, grandchild_pid = pids
    assert psutil.pid_exists(parent_pid)
    assert psutil.pid_exists(grandchild_pid)

    t0 = time.monotonic()
    manager.cancel(job_id)
    fin = notifier.wait_finished(job_id, timeout=2.0)
    assert time.monotonic() - t0 < 2.0
    assert fin["status"] == "cancelled"
    assert not psutil.pid_exists(parent_pid)
    assert not psutil.pid_exists(grandchild_pid)


@pytest.mark.timeout(10)
def test_system_shutdown_cancels_running_and_queued_jobs_and_kills_subprocess(
    tmp_path: Path,
) -> None:
    script = """
import subprocess, sys
from skald_core.jobs import JobManager
from skald_core.rpc.server import run_stdio_server

def setup(server):
    jm1 = JobManager(max_workers=1, notify_fn=server.notify)
    server.add_shutdown_hook(jm1.shutdown)

    def run_sleep(ctx):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ctx.register_subprocess(proc)
        ctx.log("info", f"pid:{proc.pid}")
        proc.wait()
        ctx.checkpoint()

    def run_queued(ctx):
        return {"ran": True}

    def start_single():
        j1 = jm1.submit("test.sleep", run_sleep)
        j2 = jm1.submit("test.queued", run_queued)
        return {"j1": j1, "j2": j2}

    server.register("test.start", start_single)

raise SystemExit(run_stdio_server(setup=setup))
"""
    env = {**os.environ, "SKALD_LOG_DIR": str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None

        proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"test.start"}\n')
        proc.stdin.flush()

        child_pid: int | None = None
        job_ids: dict[str, str] = {}
        while child_pid is None or not job_ids:
            raw_line = proc.stdout.readline()
            assert raw_line, f"Server exited early; stderr={proc.stderr.read().decode('utf-8')}"
            msg = json.loads(raw_line.decode("utf-8"))
            if msg.get("id") == 1:
                job_ids = msg["result"]
            elif msg.get("method") == "job.log":
                text = msg["params"]["message"]
                if text.startswith("pid:"):
                    child_pid = int(text.split(":", 1)[1])

        assert psutil.pid_exists(child_pid)

        t0 = time.monotonic()
        proc.stdin.write(b'{"jsonrpc":"2.0","id":2,"method":"system.shutdown"}\n')
        proc.stdin.flush()

        remaining = [json.loads(line.decode("utf-8")) for line in proc.stdout.readlines() if line]
        rc = proc.wait(timeout=5)
        elapsed = time.monotonic() - t0

        assert rc == 0
        assert elapsed < 2.0
        assert not psutil.pid_exists(child_pid)

        shutdown_resps = [m for m in remaining if m.get("id") == 2]
        assert shutdown_resps == [{"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}]

        finished_by_id = {
            m["params"]["job_id"]: m["params"]["status"]
            for m in remaining
            if m.get("method") == "job.finished"
        }
        assert finished_by_id[job_ids["j1"]] == "cancelled"
        assert finished_by_id[job_ids["j2"]] == "cancelled"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_no_leftover_threads_after_shutdown() -> None:
    before_names = {t.name for t in threading.enumerate()}
    notifier = _RecordingNotifier()
    jm = JobManager(max_workers=2, notify_fn=notifier)

    def job_fn(ctx: JobContext) -> str:
        ctx.progress(0.1, "a", "s")
        ctx.progress(0.5, "b", "s")
        ctx.checkpoint()
        return "ok"

    j1 = jm.submit("test.t1", job_fn)
    j2 = jm.submit("test.t2", job_fn)
    notifier.wait_finished(j1)
    notifier.wait_finished(j2)
    jm.shutdown(timeout=2.0)

    after_skald_threads = [
        t
        for t in threading.enumerate()
        if t.name.startswith("skald-job") and t.name not in before_names
    ]
    assert after_skald_threads == []


@pytest.mark.timeout(10)
def test_register_subprocess_after_cancel_kills_immediately_and_raises(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    started = threading.Event()
    cancelled = threading.Event()
    pid_holder: list[int] = []

    def run_job(ctx: JobContext) -> None:
        started.set()
        assert cancelled.wait(timeout=3.0)
        assert ctx.cancelled is True
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid_holder.append(proc.pid)
        ctx.register_subprocess(proc)

    job_id = manager.submit("test.reg_after_cancel", run_job)
    assert started.wait(timeout=2.0)
    manager.cancel(job_id)
    cancelled.set()

    fin = notifier.wait_finished(job_id, timeout=2.0)
    assert fin["status"] == "cancelled"
    assert pid_holder and not psutil.pid_exists(pid_holder[0])


@pytest.mark.timeout(10)
def test_cancel_kills_stubborn_sigterm_ignoring_subprocess_within_2s(
    manager: JobManager, notifier: _RecordingNotifier
) -> None:
    registered = threading.Event()
    pid_holder: list[int] = []
    stubborn_code = (
        "import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); "
        "time.sleep(60)"
    )

    def run_stubborn(ctx: JobContext) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", stubborn_code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        pid_holder.append(proc.pid)
        ctx.register_subprocess(proc)
        registered.set()
        proc.wait()
        ctx.checkpoint()

    job_id = manager.submit("test.stubborn", run_stubborn)
    assert registered.wait(timeout=3.0)
    t0 = time.monotonic()
    manager.cancel(job_id)
    fin = notifier.wait_finished(job_id, timeout=2.0)
    assert time.monotonic() - t0 < 2.0
    assert fin["status"] == "cancelled"
    assert not psutil.pid_exists(pid_holder[0])
