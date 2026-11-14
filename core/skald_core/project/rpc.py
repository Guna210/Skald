"""JSON-RPC method handlers and registration for `project.*`."""

from __future__ import annotations

from pydantic import BaseModel, Field

from skald_core.project.store import ProjectStore
from skald_core.rpc.server import RpcServer
from skald_core.schemas import ProjectManifest


class ProjectCreateParams(BaseModel):
    """Parameters for `project.create`."""

    path: str = Field(min_length=1)
    name: str = Field(min_length=1)
    base_seed: int | None = Field(default=None, ge=0, lt=2**31)


class ProjectOpenParams(BaseModel):
    """Parameters for `project.open`."""

    path: str = Field(min_length=1)


def register(server: RpcServer, store: ProjectStore | None = None) -> ProjectStore:
    """Register `project.create`, `project.open`, and `project.save` on `server`."""
    active_store = ProjectStore() if store is None else store

    def handle_create(params: ProjectCreateParams) -> ProjectManifest:
        return active_store.create(params.path, params.name, base_seed=params.base_seed)

    def handle_open(params: ProjectOpenParams) -> ProjectManifest:
        return active_store.open(params.path)

    def handle_save() -> ProjectManifest:
        return active_store.save()

    server.register("project.create", handle_create, ProjectCreateParams, ProjectManifest)
    server.register("project.open", handle_open, ProjectOpenParams, ProjectManifest)
    server.register("project.save", handle_save, None, ProjectManifest)
    return active_store
