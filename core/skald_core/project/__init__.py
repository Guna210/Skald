"""Project folder storage and RPC bindings."""

from skald_core.project.rpc import ProjectCreateParams, ProjectOpenParams, register
from skald_core.project.store import (
    CURRENT_SCHEMA_VERSION,
    ID_PREFIXES,
    IGNORED_OS_FILES,
    MANIFEST_FILENAME,
    MAX_BASE_SEED,
    MIGRATIONS,
    ProjectPaths,
    ProjectStore,
    atomic_write_bytes,
    atomic_write_json,
    migrate,
    new_id,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ID_PREFIXES",
    "IGNORED_OS_FILES",
    "MANIFEST_FILENAME",
    "MAX_BASE_SEED",
    "MIGRATIONS",
    "ProjectCreateParams",
    "ProjectOpenParams",
    "ProjectPaths",
    "ProjectStore",
    "atomic_write_bytes",
    "atomic_write_json",
    "migrate",
    "new_id",
    "register",
]
