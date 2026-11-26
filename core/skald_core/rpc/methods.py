"""Registration of built-in JSON-RPC methods on an `RpcServer`."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from skald_core.book.rpc import register as register_book_methods
from skald_core.catalog.client import _is_safe_id_segment, get_catalog, submit_catalog_refresh
from skald_core.hardware import probe_hardware
from skald_core.jobs import JobManager
from skald_core.models.installer import (
    accept_license,
    list_installed_models,
    submit_model_install,
    submit_model_remove,
    submit_model_update,
)
from skald_core.project.rpc import register as register_project_methods
from skald_core.rpc.server import RpcServer
from skald_core.rpc.system import get_system_info
from skald_core.schemas import (
    CatalogView,
    HardwareInfo,
    InstalledModelsResult,
    JobRef,
    JobStatus,
    LicenseAcceptResult,
    SystemInfo,
)


class JobIdParams(BaseModel):
    """Parameters for job control and status RPC methods."""

    job_id: str


class CatalogGetParams(BaseModel):
    """Optional parameters for `catalog.get`."""

    model_config = ConfigDict(extra="forbid")

    char_count: int | None = Field(default=None, ge=0, strict=True)


class ModelInstallParams(BaseModel):
    """Parameters for `models.install`."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    revision_id: str | None = Field(default=None, min_length=1)

    @field_validator("model_id", "checkpoint_id", "revision_id")
    @classmethod
    def _validate_segment(cls, value: str | None) -> str | None:
        if value is not None and not _is_safe_id_segment(value):
            raise ValueError(f"Unsafe identifier segment: {value!r}")
        return value


class ModelUpdateParams(BaseModel):
    """Parameters for `models.update`."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)

    @field_validator("model_id", "checkpoint_id")
    @classmethod
    def _validate_segment(cls, value: str) -> str:
        if not _is_safe_id_segment(value):
            raise ValueError(f"Unsafe identifier segment: {value!r}")
        return value


class ModelRemoveParams(BaseModel):
    """Parameters for `models.remove`."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    force: bool = Field(default=False, strict=True)

    @field_validator("model_id", "checkpoint_id", "revision_id")
    @classmethod
    def _validate_segment(cls, value: str) -> str:
        if not _is_safe_id_segment(value):
            raise ValueError(f"Unsafe identifier segment: {value!r}")
        return value


class LicenseAcceptParams(BaseModel):
    """Parameters for `license.accept`."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1)
    license_url: str = Field(min_length=1)


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
    project_store = register_project_methods(server)
    register_book_methods(server, project_store, manager)
    server.register(
        "models.install",
        lambda p: JobRef(
            job_id=submit_model_install(
                manager,
                p.model_id,
                p.checkpoint_id,
                p.revision_id,
            )
        ),
        params_model=ModelInstallParams,
        result_model=JobRef,
    )
    server.register(
        "models.update",
        lambda p: JobRef(
            job_id=submit_model_update(
                manager,
                p.model_id,
                p.checkpoint_id,
            )
        ),
        params_model=ModelUpdateParams,
        result_model=JobRef,
    )
    server.register(
        "models.remove",
        lambda p: JobRef(
            job_id=submit_model_remove(
                manager,
                p.model_id,
                p.checkpoint_id,
                p.revision_id,
                force=p.force,
                project_store=project_store,
            )
        ),
        params_model=ModelRemoveParams,
        result_model=JobRef,
    )
    server.register(
        "models.list_installed",
        lambda: list_installed_models(project_store=project_store),
        result_model=InstalledModelsResult,
    )
    server.register(
        "license.accept",
        lambda p: accept_license(p.model_id, p.license_url),
        params_model=LicenseAcceptParams,
        result_model=LicenseAcceptResult,
    )
    server.register("job.cancel", lambda p: manager.cancel(p.job_id), JobIdParams, JobStatus)
    server.register("job.pause", lambda p: manager.pause(p.job_id), JobIdParams, JobStatus)
    server.register("job.resume", lambda p: manager.resume(p.job_id), JobIdParams, JobStatus)
    server.register("job.status", lambda p: manager.status(p.job_id), JobIdParams, JobStatus)
    server.add_shutdown_hook(manager.shutdown)

    return manager
