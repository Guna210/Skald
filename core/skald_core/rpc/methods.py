"""Registration of built-in JSON-RPC methods on an `RpcServer`."""

from __future__ import annotations

from pydantic import BaseModel

from skald_core.jobs import JobManager
from skald_core.rpc.server import RpcServer
from skald_core.rpc.system import get_system_info
from skald_core.schemas import JobStatus, SystemInfo


class JobIdParams(BaseModel):
    """Parameters for job control and status RPC methods."""

    job_id: str


def register_all(server: RpcServer, job_manager: JobManager | None = None) -> JobManager:
    """Register all core RPC methods and shutdown hooks on `server`."""
    manager = JobManager(notify_fn=server.notify) if job_manager is None else job_manager

    server.register("system.info", get_system_info, result_model=SystemInfo)
    server.register("job.cancel", lambda p: manager.cancel(p.job_id), JobIdParams, JobStatus)
    server.register("job.pause", lambda p: manager.pause(p.job_id), JobIdParams, JobStatus)
    server.register("job.resume", lambda p: manager.resume(p.job_id), JobIdParams, JobStatus)
    server.register("job.status", lambda p: manager.status(p.job_id), JobIdParams, JobStatus)
    server.add_shutdown_hook(manager.shutdown)

    return manager
