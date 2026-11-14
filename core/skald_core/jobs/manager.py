"""Background job manager with pause, resume, process-tree cancel, and progress throttling."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import secrets
import string
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psutil  # type: ignore[import-untyped]
from pydantic import BaseModel

from skald_core.rpc.server import (
    APP_ERROR,
    INTERNAL_ERROR,
    InvalidParamsError,
    SkaldError,
    notify,
)
from skald_core.schemas import (
    JobError,
    JobFinished,
    JobFinishedStatus,
    JobLog,
    JobProgress,
    JobState,
    JobStatus,
    SkaldErrorData,
)

logger = logging.getLogger(__name__)

_JOB_ID_ALPHABET = string.ascii_lowercase + string.digits
_JOB_ID_RANDOM_LEN = 8
_TERMINAL_STATES: frozenset[JobState] = frozenset({"succeeded", "failed", "cancelled"})
_DEFAULT_PROGRESS_INTERVAL_S = 0.1
_TERMINATE_WAIT_S = 1.0
_KILL_WAIT_S = 0.5

NotifyFn = Callable[[str, BaseModel | dict[str, Any]], None]


class JobCancelled(Exception):
    """Raised at a job checkpoint when cancellation has been requested."""


class UnknownJobError(InvalidParamsError):
    """Raised when a job control or status call references an unknown job_id."""

    def __init__(self, job_id: str) -> None:
        super().__init__(
            "Invalid params",
            details=[
                {"loc": ["job_id"], "msg": f"Unknown job_id: {job_id}", "type": "value_error"}
            ],
        )
        self.job_id = job_id


def _generate_job_id() -> str:
    suffix = "".join(secrets.choice(_JOB_ID_ALPHABET) for _ in range(_JOB_ID_RANDOM_LEN))
    return f"j_{suffix}"


def _kill_process_tree(popen: subprocess.Popen[Any]) -> None:
    """Terminate children recursively first, then parent; wait up to 1 s, then kill."""
    if popen.poll() is not None:
        return

    try:
        parent = psutil.Process(popen.pid)
    except psutil.NoSuchProcess:
        return

    try:
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        children = []

    targets = [*children, parent]
    for proc in targets:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _, alive = psutil.wait_procs(targets, timeout=_TERMINATE_WAIT_S)
    if alive:
        alive_pids = {p.pid for p in alive}
        for proc in targets:
            if proc.pid in alive_pids:
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        psutil.wait_procs(alive, timeout=_KILL_WAIT_S)

    try:
        popen.wait(timeout=_KILL_WAIT_S)
    except (subprocess.TimeoutExpired, OSError):
        pass


@dataclass
class _JobRecord:
    job_id: str
    kind: str
    fn: Callable[..., Any]
    kwargs: dict[str, Any]
    status: JobState = "queued"
    started: bool = False
    in_flight: bool = True
    cancel_requested: bool = False
    fraction: float | None = None
    message: str = ""
    stage: str = ""
    result: Any = None
    error: JobError | None = None
    future: concurrent.futures.Future[None] | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    resume_event: threading.Event = field(default_factory=threading.Event)
    subprocesses: list[subprocess.Popen[Any]] = field(default_factory=list)
    emit_lock: threading.Lock = field(default_factory=threading.Lock)
    last_progress_sent: float = float("-inf")
    pending_progress: JobProgress | None = None
    progress_timer: threading.Timer | None = None
    finished_emitted: bool = False

    def __post_init__(self) -> None:
        self.resume_event.set()


class JobContext:
    """Execution context passed to background job functions as `fn(ctx, **kwargs)`."""

    def __init__(self, manager: JobManager, record: _JobRecord) -> None:
        self._manager = manager
        self._record = record

    @property
    def job_id(self) -> str:
        """Unique identifier of this job."""
        return self._record.job_id

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested for this job."""
        return self._record.cancel_event.is_set()

    def progress(self, fraction: float | None, message: str = "", stage: str = "") -> None:
        """Report progress (throttled per job, keeping the latest value)."""
        self._manager._report_progress(self._record, fraction, message, stage)

    def log(self, level: str, message: str) -> None:
        """Emit an unthrottled `job.log` notification."""
        self._manager._emit_log(self._record, level, message)

    def checkpoint(self) -> None:
        """Block while paused and raise `JobCancelled` if cancelled."""
        while True:
            if self._record.cancel_event.is_set():
                raise JobCancelled(self._record.job_id)
            if self._record.resume_event.is_set():
                return
            self._record.resume_event.wait()

    def register_subprocess(self, popen: subprocess.Popen[Any]) -> subprocess.Popen[Any]:
        """Register a child process so cancel or shutdown kills its process tree."""
        self._manager._register_subprocess(self._record, popen)
        return popen


class JobManager:
    """Thread-pool background job runner with pause, resume, cancel, and throttling."""

    def __init__(
        self,
        max_workers: int = 2,
        notify_fn: NotifyFn | None = None,
        progress_interval_s: float = _DEFAULT_PROGRESS_INTERVAL_S,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._max_workers = max_workers
        self._notify_fn: NotifyFn = notify if notify_fn is None else notify_fn
        self._progress_interval_s = progress_interval_s
        self._time_fn: Callable[[], float] = time.monotonic if time_fn is None else time_fn
        self._lock = threading.Lock()
        self._jobs: dict[str, _JobRecord] = {}
        self._shutdown = False
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="skald-job",
        )

    def submit(self, kind: str, fn: Callable[..., Any], **kwargs: Any) -> str:
        """Queue `fn(ctx, **kwargs)` on the thread pool and return its `job_id`."""
        with self._lock:
            if self._shutdown:
                raise RuntimeError("JobManager is shut down")
            job_id = _generate_job_id()
            while job_id in self._jobs:
                job_id = _generate_job_id()
            record = _JobRecord(job_id=job_id, kind=kind, fn=fn, kwargs=dict(kwargs))
            self._jobs[job_id] = record
            record.future = self._executor.submit(self._run_job, record)
            return job_id

    def status(self, job_id: str) -> JobStatus:
        """Return the current status snapshot for `job_id`."""
        with self._lock:
            record = self._get_record_locked(job_id)
            return self._snapshot_locked(record)

    def pause(self, job_id: str) -> JobStatus:
        """Pause a queued or running job immediately (no-op on already finished jobs)."""
        with self._lock:
            record = self._get_record_locked(job_id)
            if record.status in _TERMINAL_STATES or record.cancel_requested:
                return self._snapshot_locked(record)
            if record.status != "paused":
                record.status = "paused"
                record.resume_event.clear()
            return self._snapshot_locked(record)

    def resume(self, job_id: str) -> JobStatus:
        """Resume a paused job to running or queued (no-op on already finished jobs)."""
        with self._lock:
            record = self._get_record_locked(job_id)
            if record.status in _TERMINAL_STATES or record.cancel_requested:
                return self._snapshot_locked(record)
            if record.status == "paused":
                record.resume_event.set()
                if record.started:
                    record.status = "running"
                else:
                    record.status = "queued"
                    if not record.in_flight and not self._shutdown:
                        record.in_flight = True
                        record.future = self._executor.submit(self._run_job, record)
            return self._snapshot_locked(record)

    def cancel(self, job_id: str) -> JobStatus:
        """Cancel a job, killing any registered subprocess trees."""
        finished_payload: JobFinished | None = None
        procs_to_kill: list[subprocess.Popen[Any]] = []
        future_to_cancel: concurrent.futures.Future[None] | None = None

        with self._lock:
            record = self._get_record_locked(job_id)
            if record.status in _TERMINAL_STATES:
                return self._snapshot_locked(record)

            record.cancel_requested = True
            record.cancel_event.set()
            record.resume_event.set()

            if not record.started:
                record.status = "cancelled"
                future_to_cancel = record.future
                finished_payload = JobFinished(job_id=record.job_id, status="cancelled")
            else:
                procs_to_kill = [p for p in record.subprocesses if p.poll() is None]

            snap = self._snapshot_locked(record)

        if future_to_cancel is not None:
            future_to_cancel.cancel()
        for proc in procs_to_kill:
            _kill_process_tree(proc)
        if finished_payload is not None:
            self._emit_finished(record, finished_payload)
        return snap

    def shutdown(self, timeout: float = 2.0) -> None:
        """Cancel all queued/running jobs, kill process trees, and wait briefly for exit."""
        cancelled_queued: list[tuple[_JobRecord, JobFinished]] = []
        procs_to_kill: list[subprocess.Popen[Any]] = []
        futures_to_cancel: list[concurrent.futures.Future[None]] = []
        active_futures: list[concurrent.futures.Future[None]] = []

        with self._lock:
            self._shutdown = True
            for record in self._jobs.values():
                if record.future is not None:
                    active_futures.append(record.future)
                if record.status in _TERMINAL_STATES:
                    continue
                record.cancel_requested = True
                record.cancel_event.set()
                record.resume_event.set()
                if not record.started:
                    record.status = "cancelled"
                    if record.future is not None:
                        futures_to_cancel.append(record.future)
                    cancelled_queued.append(
                        (record, JobFinished(job_id=record.job_id, status="cancelled"))
                    )
                else:
                    procs_to_kill.extend(p for p in record.subprocesses if p.poll() is None)

        for future in futures_to_cancel:
            future.cancel()
        for proc in procs_to_kill:
            _kill_process_tree(proc)
        for record, payload in cancelled_queued:
            self._emit_finished(record, payload)

        if active_futures:
            _, not_done = concurrent.futures.wait(active_futures, timeout=timeout)
            if not_done:
                logger.warning(
                    "%d background job(s) did not stop within %.1fs during shutdown",
                    len(not_done),
                    timeout,
                )
                self._executor.shutdown(wait=False, cancel_futures=True)
                return

        self._executor.shutdown(wait=True)

    def _get_record_locked(self, job_id: str) -> _JobRecord:
        record = self._jobs.get(job_id)
        if record is None:
            raise UnknownJobError(job_id)
        return record

    def _snapshot_locked(self, record: _JobRecord) -> JobStatus:
        return JobStatus(
            job_id=record.job_id,
            kind=record.kind,
            status=record.status,
            fraction=record.fraction,
            message=record.message,
            stage=record.stage,
            result=record.result,
            error=record.error,
        )

    def _register_subprocess(self, record: _JobRecord, popen: subprocess.Popen[Any]) -> None:
        with self._lock:
            record.subprocesses = [p for p in record.subprocesses if p.poll() is None]
            record.subprocesses.append(popen)
            cancelled = record.cancel_requested
        if cancelled:
            _kill_process_tree(popen)
            raise JobCancelled(record.job_id)

    def _emit_log(self, record: _JobRecord, level: str, message: str) -> None:
        payload = JobLog(job_id=record.job_id, level=level, message=message)
        self._notify_fn("job.log", payload)

    def _report_progress(
        self,
        record: _JobRecord,
        fraction: float | None,
        message: str,
        stage: str,
    ) -> None:
        payload = JobProgress(
            job_id=record.job_id,
            fraction=fraction,
            message=message,
            stage=stage,
        )
        with self._lock:
            if record.status in _TERMINAL_STATES:
                return
            record.fraction = payload.fraction
            record.message = payload.message
            record.stage = payload.stage

        stale_timer: threading.Timer | None = None
        with record.emit_lock:
            if record.finished_emitted:
                return
            now = self._time_fn()
            elapsed = now - record.last_progress_sent
            if elapsed >= self._progress_interval_s:
                if record.progress_timer is not None:
                    stale_timer = record.progress_timer
                    record.progress_timer = None
                    stale_timer.cancel()
                record.pending_progress = None
                record.last_progress_sent = now
                self._notify_fn("job.progress", payload)
            else:
                record.pending_progress = payload
                if record.progress_timer is None:
                    delay = max(0.0, self._progress_interval_s - elapsed)
                    timer = threading.Timer(delay, self._flush_progress_timer, args=(record,))
                    timer.daemon = True
                    record.progress_timer = timer
                    timer.start()

        if stale_timer is not None and stale_timer is not threading.current_thread():
            stale_timer.join(timeout=1.0)

    def _flush_progress_timer(self, record: _JobRecord) -> None:
        with record.emit_lock:
            record.progress_timer = None
            if record.finished_emitted or record.pending_progress is None:
                return
            payload = record.pending_progress
            record.pending_progress = None
            record.last_progress_sent = self._time_fn()
            self._notify_fn("job.progress", payload)

    def _emit_finished(self, record: _JobRecord, payload: JobFinished) -> None:
        timer: threading.Timer | None = None
        with record.emit_lock:
            if record.finished_emitted:
                return
            timer = record.progress_timer
            record.progress_timer = None
            if timer is not None:
                timer.cancel()
            if record.pending_progress is not None:
                pending = record.pending_progress
                record.pending_progress = None
                self._notify_fn("job.progress", pending)
            record.finished_emitted = True
            self._notify_fn("job.finished", payload)

        if timer is not None and timer is not threading.current_thread():
            timer.join(timeout=1.0)

    def _run_job(self, record: _JobRecord) -> None:
        with self._lock:
            record.in_flight = False
            if record.status in _TERMINAL_STATES:
                return
            if record.cancel_requested:
                record.status = "cancelled"
                early_cancel = JobFinished(job_id=record.job_id, status="cancelled")
                should_emit_early = True
            elif record.status == "paused":
                # Paused while still queued: do not invoke fn or block a worker thread.
                return
            else:
                record.started = True
                record.status = "running"
                should_emit_early = False

        if should_emit_early:
            self._emit_finished(record, early_cancel)
            return

        ctx = JobContext(self, record)
        final_status: JobFinishedStatus
        final_result: Any = None
        final_error: JobError | None = None

        try:
            raw_result = record.fn(ctx, **record.kwargs)
            serialized = (
                raw_result.model_dump(mode="json")
                if isinstance(raw_result, BaseModel)
                else raw_result
            )
            json.dumps(serialized, ensure_ascii=False, allow_nan=False)
            final_status = "succeeded"
            final_result = serialized
        except JobCancelled:
            final_status = "cancelled"
        except Exception as exc:
            with self._lock:
                cancelled = record.cancel_requested
            if cancelled:
                final_status = "cancelled"
            elif isinstance(exc, SkaldError):
                logger.warning(
                    "Job %s (%s) failed (%s): %s",
                    record.job_id,
                    record.kind,
                    exc.kind,
                    exc.message,
                )
                final_status = "failed"
                final_error = JobError(
                    code=APP_ERROR,
                    message=exc.message,
                    data=SkaldErrorData(kind=exc.kind, details=exc.details, hint=exc.hint),
                )
            else:
                logger.exception(
                    "Job %s (%s) failed with unexpected error",
                    record.job_id,
                    record.kind,
                )
                final_status = "failed"
                final_error = JobError(
                    code=INTERNAL_ERROR,
                    message="Internal error",
                    data=SkaldErrorData(kind="internal", details=str(exc), hint=None),
                )
        finally:
            with self._lock:
                remaining_procs = list(record.subprocesses)
                record.subprocesses.clear()
                kill_remaining = record.cancel_requested
            if kill_remaining:
                for proc in remaining_procs:
                    _kill_process_tree(proc)

        with self._lock:
            record.status = final_status
            record.result = final_result
            record.error = final_error

        finished_payload = JobFinished(
            job_id=record.job_id,
            status=final_status,
            result=final_result,
            error=final_error,
        )
        self._emit_finished(record, finished_payload)
