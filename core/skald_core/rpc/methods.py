"""Registration of built-in JSON-RPC methods on an `RpcServer`."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from skald_core.book.rpc import register as register_book_methods
from skald_core.catalog.client import get_catalog, submit_catalog_refresh
from skald_core.hardware import probe_hardware
from skald_core.jobs import JobManager
from skald_core.project.rpc import register as register_project_methods
from skald_core.rpc.server import RpcServer
from skald_core.rpc.system import get_system_info
from skald_core.schemas import CatalogView, HardwareInfo, JobRef, JobStatus, SystemInfo


class JobIdParams(BaseModel):
    """Parameters for job control and status RPC methods."""

    job_id: str


class CatalogGetParams(BaseModel):
    """Optional parameters for `catalog.get`."""

    model_config = ConfigDict(extra="forbid")

    char_count: int | None = Field(default=None, ge=0, strict=True)


def register_all(server: RpcServer, job_manager: JobManager | None = None) -> JobManager:
    """Register all core RPC methods and shutdown hooks on `server`."""
    manager = JobManager(notify_fn=server.notify) if job_manager is None else job_manager

    server.register("system.info", get_system_info, result_model=SystemInfo)
    server.register("system.hardware", probe_hardware, result_model=HardwareInfo)
    server.register(
        "catalog.get",
        lambda p: get_catalog(char_count=p.char_count),
        params_model=CatalogGetParams,
        result_model=CatalogView,
    )
    server.register(
        "catalog.refresh",
        lambda: JobRef(job_id=submit_catalog_refresh(manager)),
        result_model=JobRef,
    )
    store = register_project_methods(server)
    register_book_methods(server, store, manager)
    server.register("job.cancel", lambda p: manager.cancel(p.job_id), JobIdParams, JobStatus)
    server.register("job.pause", lambda p: manager.pause(p.job_id), JobIdParams, JobStatus)
    server.register("job.resume", lambda p: manager.resume(p.job_id), JobIdParams, JobStatus)
    server.register("job.status", lambda p: manager.status(p.job_id), JobIdParams, JobStatus)
    server.add_shutdown_hook(manager.shutdown)

    return manager
