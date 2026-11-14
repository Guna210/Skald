"""Project folder storage, atomic writes, ID generation, path helpers, and migrations."""

from __future__ import annotations

import json
import ntpath
import os
import secrets
import string
import tempfile
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from skald_core.rpc.server import INVALID_PARAMS, SkaldError
from skald_core.schemas import ProjectManifest

MANIFEST_FILENAME = "skald-project.json"
CURRENT_SCHEMA_VERSION = 1
MAX_BASE_SEED = 2**31
ID_PREFIXES = frozenset({"v_", "rn_", "ch_", "p_"})
IGNORED_OS_FILES = frozenset({"desktop.ini", "thumbs.db", ".ds_store"})

_ID_ALPHABET = string.ascii_lowercase + string.digits
_ID_RANDOM_LENGTH = 8

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]
MIGRATIONS: dict[int, MigrationFn] = {}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """Return a random B9 identifier (`<prefix><8 lowercase alphanumerics>`)."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"Unsupported ID prefix {prefix!r}; expected one of {sorted(ID_PREFIXES)}")
    suffix = "".join(secrets.choice(_ID_ALPHABET) for _ in range(_ID_RANDOM_LENGTH))
    return f"{prefix}{suffix}"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write bytes via a same-directory temp file and `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_path = Path(fh.name)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically write UTF-8 JSON (`ensure_ascii=False`, indent 2, LF newlines)."""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    atomic_write_bytes(path, text.replace("\r\n", "\n").encode("utf-8"))


def _validate_single_segment(segment: str, label: str) -> str:
    if (
        not segment
        or segment in {".", ".."}
        or "/" in segment
        or "\\" in segment
        or "\x00" in segment
    ):
        raise ValueError(f"Invalid {label}: {segment!r}")
    return segment


class ProjectPaths:
    """Path helpers for every B9 file inside a project folder (created on demand)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def manifest(self) -> Path:
        return self.root / MANIFEST_FILENAME

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    def source_file(self, filename: str = "original.epub") -> Path:
        return self.source_dir / _validate_single_segment(filename, "source filename")

    @property
    def book(self) -> Path:
        return self.root / "book.json"

    @property
    def lexicon(self) -> Path:
        return self.root / "lexicon.json"

    @property
    def assignments(self) -> Path:
        return self.root / "assignments.json"

    @property
    def voices_lock(self) -> Path:
        return self.root / "voices.lock.json"

    @property
    def models_lock(self) -> Path:
        return self.root / "models.lock.json"

    @property
    def chunks_cache_dir(self) -> Path:
        return self.root / "cache" / "chunks"

    def chunk_cache(self, sha256: str) -> Path:
        return self.chunks_cache_dir / f"{_validate_single_segment(sha256, 'chunk hash')}.flac"

    @property
    def renders_dir(self) -> Path:
        return self.root / "renders"

    def render_dir(self, render_id: str) -> Path:
        return self.renders_dir / _validate_single_segment(render_id, "render id")

    def render_record(self, render_id: str) -> Path:
        return self.render_dir(render_id) / "render.json"

    def render_chapters_dir(self, render_id: str) -> Path:
        return self.render_dir(render_id) / "chapters"

    def render_chapter(self, render_id: str, index: int) -> Path:
        if index < 0:
            raise ValueError(f"Chapter index must be non-negative, got {index}")
        return self.render_chapters_dir(render_id) / f"{index:02d}.flac"

    def render_qc(self, render_id: str) -> Path:
        return self.render_dir(render_id) / "qc.json"

    def render_exports_dir(self, render_id: str) -> Path:
        return self.render_dir(render_id) / "exports"

    def to_relative(self, target: Path | str) -> str:
        """Convert a path inside the project root to a POSIX relative path (`/`)."""
        resolved_root = self.root.resolve()
        candidate = Path(target)
        resolved_target = (
            candidate.resolve()
            if candidate.is_absolute()
            else (resolved_root / candidate).resolve()
        )
        try:
            rel = resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"Path {target!r} is outside project root {self.root}") from exc
        return rel.as_posix()

    def from_relative(self, rel_path: str) -> Path:
        """Resolve a stored POSIX relative path under the project root safely."""
        if not rel_path or "\\" in rel_path or "\x00" in rel_path:
            raise ValueError(f"Invalid stored relative path: {rel_path!r}")
        drive, _ = ntpath.splitdrive(rel_path)
        if drive or rel_path.startswith("/"):
            raise ValueError(f"Stored path must be relative: {rel_path!r}")
        posix = PurePosixPath(rel_path)
        if any(part == ".." for part in posix.parts):
            raise ValueError(f"Path traversal not allowed in stored path: {rel_path!r}")
        return self.root / Path(*posix.parts)


def migrate(
    manifest: Mapping[str, Any],
    migrations: Mapping[int, MigrationFn] | None = None,
) -> dict[str, Any]:
    """Upgrade a raw manifest dict to `CURRENT_SCHEMA_VERSION` via `{from_version: fn}`."""
    data = dict(manifest)
    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise SkaldError(
            "project_invalid",
            "Project manifest is missing a valid schema_version.",
            details={"schema_version": version},
            hint="The skald-project.json file is malformed.",
        )

    if version > CURRENT_SCHEMA_VERSION:
        raise SkaldError(
            "project_invalid",
            (
                f"Project manifest uses schema version {version}, "
                f"but this version supports up to {CURRENT_SCHEMA_VERSION}."
            ),
            details={"schema_version": version, "supported_version": CURRENT_SCHEMA_VERSION},
            hint="This project was made by a newer Skald. Update Skald to open it.",
        )

    reg = MIGRATIONS if migrations is None else migrations
    while version < CURRENT_SCHEMA_VERSION:
        fn = reg.get(version)
        if fn is None:
            raise SkaldError(
                "project_invalid",
                f"Unsupported project schema version {version}.",
                details={"schema_version": version},
                hint="No migration path is available for this project version.",
            )
        next_data = fn(dict(data))
        next_version = next_data.get("schema_version")
        if (
            isinstance(next_version, bool)
            or not isinstance(next_version, int)
            or next_version <= version
            or next_version > CURRENT_SCHEMA_VERSION
        ):
            raise SkaldError(
                "project_invalid",
                (
                    f"Project migration from version {version} "
                    f"produced invalid version {next_version}."
                ),
                details={"from_version": version, "to_version": next_version},
            )
        data = next_data
        version = next_version

    return data


def _check_create_target(root: Path) -> None:
    if not root.exists():
        return
    if not root.is_dir():
        raise SkaldError(
            "folder_not_empty",
            f"Target path exists and is not a folder: {root}",
            details={"path": str(root)},
            hint="Choose an empty folder or a new folder path.",
        )
    if (root / MANIFEST_FILENAME).exists():
        raise SkaldError(
            "folder_not_empty",
            f"Folder already contains a Skald project: {root}",
            details={"path": str(root)},
            hint="This folder already contains a Skald project; open it instead.",
        )
    non_ignored = [
        entry.name for entry in root.iterdir() if entry.name.lower() not in IGNORED_OS_FILES
    ]
    if non_ignored:
        raise SkaldError(
            "folder_not_empty",
            f"Target folder is not empty: {root}",
            details={"path": str(root), "entries": sorted(non_ignored)},
            hint="Choose an empty folder or a new folder path.",
        )


class ProjectStore:
    """Manages the currently open Skald project folder and manifest."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._root: Path | None = None
        self._manifest: ProjectManifest | None = None

    @property
    def root(self) -> Path | None:
        with self._lock:
            return self._root

    @property
    def manifest(self) -> ProjectManifest | None:
        with self._lock:
            return self._manifest

    @property
    def paths(self) -> ProjectPaths:
        with self._lock:
            if self._root is None:
                raise SkaldError(
                    "internal",
                    "No project is currently open.",
                    hint="Create or open a project first.",
                    code=INVALID_PARAMS,
                )
            return ProjectPaths(self._root)

    def create(
        self,
        path: Path | str,
        name: str,
        base_seed: int | None = None,
    ) -> ProjectManifest:
        """Create a new Skald project in a missing or empty folder and keep it open."""
        if not name or not name.strip():
            raise ValueError("Project name must not be empty")
        if base_seed is None:
            seed = secrets.randbelow(MAX_BASE_SEED)
        else:
            if isinstance(base_seed, bool) or not (0 <= base_seed < MAX_BASE_SEED):
                raise ValueError(f"base_seed must be in [0, {MAX_BASE_SEED}), got {base_seed!r}")
            seed = base_seed

        root = Path(path).resolve()
        with self._lock:
            _check_create_target(root)
            now = _utc_now_iso()
            manifest = ProjectManifest(
                schema_version=CURRENT_SCHEMA_VERSION,
                name=name,
                created_at=now,
                updated_at=now,
                base_seed=seed,
                render_ids=[],
                voice_ids=[],
            )
            root.mkdir(parents=True, exist_ok=True)
            atomic_write_json(root / MANIFEST_FILENAME, manifest.model_dump(mode="json"))
            self._root = root
            self._manifest = manifest
            return manifest.model_copy(deep=True)

    def open(self, path: Path | str) -> ProjectManifest:
        """Open an existing Skald project folder, migrating and validating its manifest."""
        root = Path(path).resolve()
        manifest_path = root / MANIFEST_FILENAME
        if not root.is_dir() or not manifest_path.is_file():
            raise SkaldError(
                "project_invalid",
                f"Project manifest not found in {root}",
                details={"path": str(root)},
                hint=f"Select a folder that contains {MANIFEST_FILENAME}.",
            )

        try:
            raw_text = manifest_path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkaldError(
                "project_invalid",
                f"Project manifest is malformed: {manifest_path}",
                details={"path": str(manifest_path), "error": str(exc)},
                hint=f"The {MANIFEST_FILENAME} file could not be parsed as UTF-8 JSON.",
            ) from exc

        if not isinstance(raw_data, dict):
            raise SkaldError(
                "project_invalid",
                f"Project manifest must be a JSON object: {manifest_path}",
                details={"path": str(manifest_path)},
                hint=f"The {MANIFEST_FILENAME} file is malformed.",
            )

        migrated = migrate(raw_data)
        try:
            manifest = ProjectManifest.model_validate(migrated)
        except ValidationError as exc:
            raise SkaldError(
                "project_invalid",
                f"Project manifest is invalid: {manifest_path}",
                details=json.loads(exc.json(include_url=False)),
                hint=f"The {MANIFEST_FILENAME} file is incomplete or malformed.",
            ) from exc

        with self._lock:
            self._root = root
            self._manifest = manifest
            return manifest.model_copy(deep=True)

    def save(self) -> ProjectManifest:
        """Atomically save the currently open project manifest."""
        with self._lock:
            if self._root is None or self._manifest is None:
                raise SkaldError(
                    "internal",
                    "No project is currently open.",
                    hint="Create or open a project before saving.",
                    code=INVALID_PARAMS,
                )
            updated = self._manifest.model_copy(update={"updated_at": _utc_now_iso()})
            atomic_write_json(self._root / MANIFEST_FILENAME, updated.model_dump(mode="json"))
            self._manifest = updated
            return updated.model_copy(deep=True)
