"""Model file installer, revision management, project pin checks, and license acceptance."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from skald_core import __version__, net
from skald_core.catalog import schema as catalog_schema
from skald_core.catalog.client import _is_safe_id_segment, get_catalog
from skald_core.catalog.schema import CatalogFile
from skald_core.jobs.manager import JobCancelled, JobContext, JobManager
from skald_core.packs.manager import PackManager, _rmtree, parse_lockfile
from skald_core.project.store import MANIFEST_FILENAME, ProjectStore, atomic_write_json
from skald_core.rpc.server import INVALID_PARAMS, SkaldError
from skald_core.schemas import (
    AnnotatedCatalogCheckpoint,
    AnnotatedCatalogModel,
    AnnotatedCatalogRevision,
    ErrorKind,
    HardwareInfo,
    InstalledModelRevision,
    InstalledModelsResult,
    LicenseAcceptResult,
    ModelInstallResult,
    ModelRemoveResult,
    ModelsLockFile,
    PinnedModelRecord,
    ProjectRef,
)
from skald_core.storage import get_data_dir, get_storage_dir, models_dir

logger = logging.getLogger(__name__)

LICENSES_FILENAME = "licenses.json"
RECENT_PROJECTS_FILENAME = "recent.json"
MODELS_LOCK_FILENAME = "models.lock.json"
COMPLETE_MARKER_FILENAME = ".complete"

_REPLACE_RETRY_DELAYS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4, 0.8)

_REVISION_OPS_LOCK = threading.Lock()
_ACTIVE_REVISION_OPS: set[tuple[str, str, str, str]] = set()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _validate_id_segment(segment: str, label: str) -> str:
    if not _is_safe_id_segment(segment):
        raise SkaldError(
            "internal",
            "Invalid params",
            details=[
                {"loc": [label], "msg": f"Invalid {label}: {segment!r}", "type": "value_error"}
            ],
            code=INVALID_PARAMS,
        )
    return segment


def _safe_file_dest(base_dir: Path, rel_path: str) -> Path:
    if not rel_path or rel_path.startswith("/") or "\\" in rel_path or "\x00" in rel_path:
        raise SkaldError(
            "unsupported_format",
            f"Unsafe model file path: {rel_path!r}",
            details={"path": rel_path},
        )
    posix = PurePosixPath(rel_path)
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise SkaldError(
            "unsupported_format",
            f"Unsafe model file path: {rel_path!r}",
            details={"path": rel_path},
        )
    base_resolved = base_dir.resolve()
    target = (base_resolved / Path(*posix.parts)).resolve()
    try:
        target.relative_to(base_resolved)
    except ValueError as exc:
        raise SkaldError(
            "unsupported_format",
            f"Model file path escapes revision directory: {rel_path!r}",
            details={"path": rel_path},
        ) from exc
    return base_dir / Path(*posix.parts)


@contextmanager
def _revision_op_lock(
    models_root: Path,
    model_id: str,
    checkpoint_id: str,
    revision_id: str,
    *,
    error_kind: ErrorKind = "model_download_failed",
) -> Iterator[None]:
    key = (
        os.path.normcase(os.path.abspath(models_root)),
        model_id,
        checkpoint_id,
        revision_id,
    )
    with _REVISION_OPS_LOCK:
        if key in _ACTIVE_REVISION_OPS:
            raise SkaldError(
                error_kind,
                f"Operation for {model_id}/{checkpoint_id}/{revision_id} is already in progress.",
                details={
                    "model_id": model_id,
                    "checkpoint_id": checkpoint_id,
                    "revision_id": revision_id,
                },
                hint="Another operation for this model revision is already in progress.",
            )
        _ACTIVE_REVISION_OPS.add(key)
    try:
        yield
    finally:
        with _REVISION_OPS_LOCK:
            _ACTIVE_REVISION_OPS.discard(key)


def licenses_path(data_dir: Path | None = None) -> Path:
    """Return `<userData>/licenses.json`."""
    root = get_data_dir() if data_dir is None else data_dir
    return root / LICENSES_FILENAME


def _read_licenses(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Could not read licenses file %s (%s); ignoring acceptances", path, exc)
        return {}
    if not isinstance(raw, dict):
        logger.warning("Licenses file %s is not a JSON object; ignoring acceptances", path)
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for model_id, entry in raw.items():
        if not isinstance(model_id, str) or not isinstance(entry, dict):
            continue
        url = entry.get("license_url")
        accepted_at = entry.get("accepted_at")
        if isinstance(url, str) and isinstance(accepted_at, str):
            cleaned[model_id] = {"license_url": url, "accepted_at": accepted_at}
    return cleaned


def is_license_accepted(
    model_id: str,
    license_url: str,
    *,
    data_dir: Path | None = None,
) -> bool:
    """Return True iff `<userData>/licenses.json` records `model_id` with exact `license_url`."""
    entries = _read_licenses(licenses_path(data_dir))
    entry = entries.get(model_id)
    return entry is not None and entry.get("license_url") == license_url


def accept_license(
    model_id: str,
    license_url: str,
    *,
    data_dir: Path | None = None,
    storage_dir: Path | None = None,
    bundled_path: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
    hardware: HardwareInfo | None = None,
) -> LicenseAcceptResult:
    """Validate `model_id` and `license_url` against the current catalog and record acceptance."""
    storage = get_storage_dir() if storage_dir is None else storage_dir
    view = get_catalog(
        data_dir=data_dir,
        models_root=models_dir(storage),
        bundled_path=bundled_path,
        adapters_path=adapters_path,
        app_version=app_version,
        hardware=hardware,
    )
    model = next((m for m in view.models if m.id == model_id), None)
    if model is None:
        raise SkaldError(
            "internal",
            "Invalid params",
            details=[
                {"loc": ["model_id"], "msg": f"Unknown model_id: {model_id}", "type": "value_error"}
            ],
            hint="Select a model from the current catalog.",
            code=INVALID_PARAMS,
        )
    if license_url != model.license.url:
        raise SkaldError(
            "internal",
            "Invalid params",
            details=[
                {
                    "loc": ["license_url"],
                    "msg": "license_url must match the catalog license.url exactly.",
                    "type": "value_error",
                }
            ],
            hint="Refresh the catalog and accept the current license URL.",
            code=INVALID_PARAMS,
        )

    path = licenses_path(data_dir)
    entries = _read_licenses(path)
    accepted_at = _utc_now_iso()
    entries[model_id] = {"license_url": license_url, "accepted_at": accepted_at}
    atomic_write_json(path, entries)
    return LicenseAcceptResult(model_id=model_id, license_url=license_url, accepted_at=accepted_at)


def _read_project_name(project_dir: Path, fallback_name: str | None = None) -> str:
    manifest_path = project_dir / MANIFEST_FILENAME
    if manifest_path.is_file():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                name = raw.get("name")
                if isinstance(name, str) and name.strip():
                    return name
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    if fallback_name is not None and fallback_name.strip():
        return fallback_name
    return project_dir.name or str(project_dir)


def _known_projects(
    *,
    data_dir: Path | None = None,
    project_store: ProjectStore | None = None,
) -> list[ProjectRef]:
    projects_by_key: dict[str, ProjectRef] = {}
    recent_file = (get_data_dir() if data_dir is None else data_dir) / RECENT_PROJECTS_FILENAME
    if not recent_file.is_file():
        logger.warning(
            "Recent projects file not found at %s; treating recent projects as empty",
            recent_file,
        )
    else:
        try:
            raw = json.loads(recent_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "Could not read recent projects file %s (%s); treating as empty",
                recent_file,
                exc,
            )
            raw = None

        if raw is not None and not isinstance(raw, list):
            logger.warning(
                "Recent projects file %s is not a JSON array; treating as empty",
                recent_file,
            )
            raw = None

        if isinstance(raw, list):
            for idx, entry in enumerate(raw):
                if not isinstance(entry, dict):
                    logger.warning("Ignoring non-object entry %d in %s", idx, recent_file)
                    continue
                raw_path = entry.get("path")
                if not isinstance(raw_path, str) or not raw_path.strip():
                    logger.warning("Ignoring entry %d without valid path in %s", idx, recent_file)
                    continue
                proj_path = Path(raw_path)
                if not proj_path.is_absolute():
                    logger.warning(
                        "Ignoring non-absolute project path %r in %s", raw_path, recent_file
                    )
                    continue
                norm = os.path.normcase(os.path.abspath(proj_path))
                raw_name = entry.get("name")
                fallback = raw_name if isinstance(raw_name, str) and raw_name.strip() else None
                if norm not in projects_by_key:
                    projects_by_key[norm] = ProjectRef(
                        name=_read_project_name(proj_path, fallback_name=fallback),
                        path=str(proj_path),
                    )

    if project_store is not None:
        open_root = project_store.root
        if open_root is not None:
            norm = os.path.normcase(os.path.abspath(open_root))
            manifest = project_store.manifest
            name = manifest.name if manifest is not None else _read_project_name(open_root)
            projects_by_key[norm] = ProjectRef(name=name, path=str(open_root))

    return list(projects_by_key.values())


def _read_project_pins(project_dir: Path) -> list[PinnedModelRecord]:
    lock_path = project_dir / MODELS_LOCK_FILENAME
    if not lock_path.is_file():
        return []
    try:
        raw_text = lock_path.read_text(encoding="utf-8")
        lock = ModelsLockFile.model_validate_json(raw_text)
        return lock.models
    except (OSError, UnicodeDecodeError, ValidationError, ValueError) as exc:
        logger.warning(
            "Unreadable or invalid %s (%s); treating project as having no pins",
            lock_path,
            exc,
        )
        return []


def _collect_pins_by_revision(
    *,
    data_dir: Path | None = None,
    project_store: ProjectStore | None = None,
) -> dict[tuple[str, str, str], list[ProjectRef]]:
    pins: dict[tuple[str, str, str], list[ProjectRef]] = {}
    for proj in _known_projects(data_dir=data_dir, project_store=project_store):
        seen_for_proj: set[tuple[str, str, str]] = set()
        for record in _read_project_pins(Path(proj.path)):
            key = (record.model_id, record.checkpoint_id, record.revision_id)
            if key in seen_for_proj:
                continue
            seen_for_proj.add(key)
            pins.setdefault(key, []).append(proj)
    return pins


def _free_disk_bytes(target_dir: Path) -> int:
    probe_path = target_dir.resolve()
    while not probe_path.exists():
        parent = probe_path.parent
        if parent == probe_path:
            break
        probe_path = parent
    return int(shutil.disk_usage(probe_path).free)


def _remaining_download_bytes(part_dir: Path, files: Sequence[CatalogFile]) -> int:
    remaining = 0
    for f_entry in files:
        dest = _safe_file_dest(part_dir, f_entry.path)
        if dest.is_file() and dest.stat().st_size == f_entry.size:
            continue
        part_file = dest.with_name(f"{dest.name}.part")
        if part_file.is_file():
            part_size = part_file.stat().st_size
            if part_size <= f_entry.size:
                remaining += f_entry.size - part_size
                continue
        remaining += f_entry.size
    return remaining


def _lookup_catalog_target(
    view_models: Sequence[AnnotatedCatalogModel],
    model_id: str,
    checkpoint_id: str,
    revision_id: str | None,
) -> tuple[AnnotatedCatalogModel, AnnotatedCatalogCheckpoint, AnnotatedCatalogRevision]:
    model = next((m for m in view_models if m.id == model_id), None)
    if model is None:
        raise SkaldError(
            "model_download_failed",
            f"Model {model_id!r} was not found in the catalog.",
            details={"model_id": model_id},
            hint="Refresh the catalog and try again.",
        )
    cp = next((c for c in model.checkpoints if c.id == checkpoint_id), None)
    if cp is None:
        raise SkaldError(
            "model_download_failed",
            f"Checkpoint {checkpoint_id!r} was not found for model {model_id!r}.",
            details={"model_id": model_id, "checkpoint_id": checkpoint_id},
            hint="Refresh the catalog and try again.",
        )
    target_rev_id = cp.default_revision if revision_id is None else revision_id
    _validate_id_segment(target_rev_id, "revision_id")
    rev = next((r for r in cp.revisions if r.id == target_rev_id), None)
    if rev is None:
        raise SkaldError(
            "model_download_failed",
            f"Revision {target_rev_id!r} was not found for {model_id}/{checkpoint_id}.",
            details={
                "model_id": model_id,
                "checkpoint_id": checkpoint_id,
                "revision_id": target_rev_id,
            },
            hint="Refresh the catalog and try again.",
        )
    return model, cp, rev


def _read_complete_marker(rev_dir: Path) -> dict[str, Any] | None:
    marker_path = rev_dir / COMPLETE_MARKER_FILENAME
    if not marker_path.is_file():
        return None
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _replace_dir_with_retry(
    src: Path,
    dst: Path,
    retry_delays: Sequence[float] = _REPLACE_RETRY_DELAYS,
) -> None:
    if dst.exists():
        _rmtree(dst)
    for attempt in range(len(retry_delays) + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
                continue
            raise SkaldError(
                "model_download_failed",
                f"Could not finalize model directory {dst}: {exc}",
                details={"src": str(src), "dst": str(dst), "error": str(exc)},
                hint="Close any program locking the model folder and try again.",
            ) from exc


def _ensure_pack_if_needed(
    ctx: JobContext,
    model: AnnotatedCatalogModel,
    *,
    storage: Path,
    pack_manager: PackManager | None,
) -> str | None:
    if model.pack is None:
        return None
    accel = "cu12" if (model.fit is not None and model.fit.tier == "cuda") else "cpu"
    pm = PackManager(storage_dir=storage) if pack_manager is None else pack_manager
    resolved_lock = pm.resolve_lockfile(model.pack, accel=accel)
    lock_info = parse_lockfile(resolved_lock)
    candidate_dir = pm.pack_dir_for(model.pack, lock_info, storage_dir=storage)
    existing_meta = pm.read_pack_metadata(candidate_dir)
    if existing_meta is not None and existing_meta.lock_sha256 == lock_info.sha256:
        return str(candidate_dir)
    res = pm.install_job(ctx, model.pack, accel=accel, worker_wheel=None)
    return str(res["pack_dir"])


def _validate_install_preconditions(
    model: AnnotatedCatalogModel,
    cp: AnnotatedCatalogCheckpoint,
    rev: AnnotatedCatalogRevision,
    *,
    data_dir: Path | None,
    part_dir: Path,
) -> None:
    if model.status == "retired":
        raise SkaldError(
            "model_download_failed",
            f"Model {model.id!r} is retired and cannot be downloaded.",
            details={"model_id": model.id, "status": model.status},
            hint="This model is retired and no longer available for new downloads.",
        )
    if not rev.compatible:
        raise SkaldError(
            "adapter_unavailable",
            f"Revision {rev.id!r} of {model.id}/{cp.id} is not compatible ({rev.reason}).",
            details={
                "model_id": model.id,
                "checkpoint_id": cp.id,
                "revision_id": rev.id,
                "reason": rev.reason,
            },
            hint="Update Skald to install this model revision.",
        )
    if rev.bundled:
        raise SkaldError(
            "internal",
            f"Revision {rev.id!r} of {model.id}/{cp.id} is bundled with the app.",
            details={"model_id": model.id, "checkpoint_id": cp.id, "revision_id": rev.id},
            hint="This model revision is bundled with the app and does not need to be downloaded.",
        )
    if not model.license.commercial and not is_license_accepted(
        model.id, model.license.url, data_dir=data_dir
    ):
        raise SkaldError(
            "license_not_accepted",
            f"Non-commercial license for {model.id!r} has not been accepted.",
            details={
                "model_id": model.id,
                "license_name": model.license.name,
                "license_url": model.license.url,
            },
            hint="Read and accept the model's non-commercial license before downloading.",
        )
    for f_entry in rev.files:
        _safe_file_dest(part_dir, f_entry.path)
        if f_entry.format == "pickle" and (
            f_entry.approved_exception is None or not f_entry.approved_exception.strip()
        ):
            raise SkaldError(
                "unsupported_format",
                f"Refusing unapproved pickle file {f_entry.path!r} in {model.id}/{cp.id}/{rev.id}.",
                details={
                    "model_id": model.id,
                    "checkpoint_id": cp.id,
                    "revision_id": rev.id,
                    "file": f_entry.path,
                },
                hint="Pickle model files require an approved exception.",
            )


def install_model(
    ctx: JobContext,
    model_id: str,
    checkpoint_id: str,
    revision_id: str | None = None,
    *,
    data_dir: Path | None = None,
    storage_dir: Path | None = None,
    bundled_path: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
    hardware: HardwareInfo | None = None,
    pack_manager: PackManager | None = None,
) -> ModelInstallResult:
    """Install a model revision: validate, check disk, ensure pack, download, verify, finalize."""
    _validate_id_segment(model_id, "model_id")
    _validate_id_segment(checkpoint_id, "checkpoint_id")
    if revision_id is not None:
        _validate_id_segment(revision_id, "revision_id")

    ctx.checkpoint()
    storage = get_storage_dir() if storage_dir is None else storage_dir
    models_root = models_dir(storage)

    view = get_catalog(
        data_dir=data_dir,
        models_root=models_root,
        bundled_path=bundled_path,
        adapters_path=adapters_path,
        app_version=app_version,
        hardware=hardware,
    )
    model, cp, rev = _lookup_catalog_target(view.models, model_id, checkpoint_id, revision_id)

    rev_dir = models_root / model.id / cp.id / rev.id
    part_dir = models_root / model.id / cp.id / f"{rev.id}.part"

    _validate_install_preconditions(model, cp, rev, data_dir=data_dir, part_dir=part_dir)

    with _revision_op_lock(
        models_root,
        model.id,
        cp.id,
        rev.id,
        error_kind="model_download_failed",
    ):
        ctx.checkpoint()
        existing_marker = _read_complete_marker(rev_dir)
        if existing_marker is not None:
            pack_dir_str = _ensure_pack_if_needed(
                ctx, model, storage=storage, pack_manager=pack_manager
            )
            raw_files = existing_marker.get("files")
            files_map = (
                dict(raw_files)
                if isinstance(raw_files, dict)
                else {f.path: f.sha256 for f in rev.files}
            )
            installed_at = existing_marker.get("installed_at")
            ctx.progress(1.0, f"Model {model.id}/{cp.id}/{rev.id} already installed", "finalize")
            return ModelInstallResult(
                model_id=model.id,
                checkpoint_id=cp.id,
                revision_id=rev.id,
                path=str(rev_dir),
                files=files_map,
                installed_at=installed_at if isinstance(installed_at, str) else _utc_now_iso(),
                pack_dir=pack_dir_str,
                already_installed=True,
            )

        required_bytes = _remaining_download_bytes(part_dir, rev.files)
        free_bytes = _free_disk_bytes(storage)
        if free_bytes < required_bytes:
            raise SkaldError(
                "not_enough_disk",
                (
                    f"Not enough disk space in {storage}: need {required_bytes} bytes, "
                    f"have {free_bytes} bytes"
                ),
                details={
                    "required_bytes": required_bytes,
                    "free_bytes": free_bytes,
                    "path": str(storage),
                },
                hint="Free disk space or choose another model storage folder in Settings.",
            )

        pack_dir_str = _ensure_pack_if_needed(
            ctx, model, storage=storage, pack_manager=pack_manager
        )

        part_dir.mkdir(parents=True, exist_ok=True)
        total_bytes = sum(f.size for f in rev.files)
        num_files = len(rev.files)
        completed_bytes = 0
        file_hashes: dict[str, str] = {}

        for idx, f_entry in enumerate(rev.files, start=1):
            ctx.checkpoint()
            dest = _safe_file_dest(part_dir, f_entry.path)
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.is_file():
                actual_size, actual_sha = net._file_size_and_sha256(dest)
                if actual_size == f_entry.size and actual_sha == f_entry.sha256:
                    completed_bytes += f_entry.size
                    file_hashes[f_entry.path] = f_entry.sha256
                    frac = (
                        min(1.0, completed_bytes / total_bytes)
                        if total_bytes > 0
                        else idx / num_files
                    )
                    ctx.progress(
                        frac,
                        f"Verified {f_entry.path} ({idx}/{num_files})",
                        "download",
                    )
                    continue
                dest.unlink(missing_ok=True)

            url = catalog_schema.build_file_url(rev.source, f_entry.path)

            def _on_progress(
                bytes_written: int,
                _file_size: int,
                *,
                _idx: int = idx,
                _path: str = f_entry.path,
                _fsize: int = f_entry.size,
                _base: int = completed_bytes,
            ) -> None:
                ctx.checkpoint()
                overall = min(total_bytes, _base + min(bytes_written, _fsize))
                frac = min(1.0, overall / total_bytes) if total_bytes > 0 else _idx / num_files
                ctx.progress(
                    frac,
                    f"Downloading {_path} ({_idx}/{num_files}, {overall}/{total_bytes} bytes)",
                    "download",
                )

            try:
                net.download(
                    url,
                    dest,
                    sha256=f_entry.sha256,
                    size=f_entry.size,
                    progress_cb=_on_progress,
                    cancel=lambda: ctx.cancelled,
                )
            except net.DownloadCancelled as exc:
                raise JobCancelled(ctx.job_id) from exc

            completed_bytes += f_entry.size
            file_hashes[f_entry.path] = f_entry.sha256

        ctx.checkpoint()
        installed_at = _utc_now_iso()
        atomic_write_json(
            part_dir / COMPLETE_MARKER_FILENAME,
            {"files": file_hashes, "installed_at": installed_at},
        )
        _replace_dir_with_retry(part_dir, rev_dir)
        ctx.progress(1.0, f"Installed {model.id}/{cp.id}/{rev.id}", "finalize")
        return ModelInstallResult(
            model_id=model.id,
            checkpoint_id=cp.id,
            revision_id=rev.id,
            path=str(rev_dir),
            files=file_hashes,
            installed_at=installed_at,
            pack_dir=pack_dir_str,
            already_installed=False,
        )


def submit_model_install(
    manager: JobManager,
    model_id: str,
    checkpoint_id: str,
    revision_id: str | None = None,
    **kwargs: Any,
) -> str:
    """Submit `install_model` to `JobManager` and return its `job_id`."""
    return manager.submit(
        "models.install",
        install_model,
        model_id=model_id,
        checkpoint_id=checkpoint_id,
        revision_id=revision_id,
        **kwargs,
    )


def update_model(
    ctx: JobContext,
    model_id: str,
    checkpoint_id: str,
    *,
    data_dir: Path | None = None,
    storage_dir: Path | None = None,
    bundled_path: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
    hardware: HardwareInfo | None = None,
    pack_manager: PackManager | None = None,
) -> ModelInstallResult:
    """Install the checkpoint's default revision if not already installed (never edits pins)."""
    _validate_id_segment(model_id, "model_id")
    _validate_id_segment(checkpoint_id, "checkpoint_id")

    ctx.checkpoint()
    storage = get_storage_dir() if storage_dir is None else storage_dir
    models_root = models_dir(storage)

    view = get_catalog(
        data_dir=data_dir,
        models_root=models_root,
        bundled_path=bundled_path,
        adapters_path=adapters_path,
        app_version=app_version,
        hardware=hardware,
    )
    model, cp, rev = _lookup_catalog_target(view.models, model_id, checkpoint_id, None)
    rev_dir = models_root / model.id / cp.id / rev.id
    existing_marker = _read_complete_marker(rev_dir)
    if existing_marker is not None:
        raw_files = existing_marker.get("files")
        files_map = (
            dict(raw_files)
            if isinstance(raw_files, dict)
            else {f.path: f.sha256 for f in rev.files}
        )
        installed_at = existing_marker.get("installed_at")
        ctx.progress(1.0, f"{model.id}/{cp.id} is already on {rev.id}", "finalize")
        return ModelInstallResult(
            model_id=model.id,
            checkpoint_id=cp.id,
            revision_id=rev.id,
            path=str(rev_dir),
            files=files_map,
            installed_at=installed_at if isinstance(installed_at, str) else _utc_now_iso(),
            pack_dir=None,
            already_installed=True,
        )

    return install_model(
        ctx,
        model.id,
        cp.id,
        rev.id,
        data_dir=data_dir,
        storage_dir=storage,
        bundled_path=bundled_path,
        adapters_path=adapters_path,
        app_version=app_version,
        hardware=hardware,
        pack_manager=pack_manager,
    )


def submit_model_update(
    manager: JobManager,
    model_id: str,
    checkpoint_id: str,
    **kwargs: Any,
) -> str:
    """Submit `update_model` to `JobManager` and return its `job_id`."""
    return manager.submit(
        "models.update",
        update_model,
        model_id=model_id,
        checkpoint_id=checkpoint_id,
        **kwargs,
    )


def _scan_installed_revisions(models_root: Path) -> list[tuple[str, str, str, Path]]:
    if not models_root.is_dir():
        return []
    found: list[tuple[str, str, str, Path]] = []
    for model_entry in sorted(models_root.iterdir()):
        if not model_entry.is_dir() or not _is_safe_id_segment(model_entry.name):
            continue
        for cp_entry in sorted(model_entry.iterdir()):
            if not cp_entry.is_dir() or not _is_safe_id_segment(cp_entry.name):
                continue
            for rev_entry in sorted(cp_entry.iterdir()):
                if (
                    not rev_entry.is_dir()
                    or rev_entry.name.endswith(".part")
                    or not _is_safe_id_segment(rev_entry.name)
                ):
                    continue
                if (rev_entry / COMPLETE_MARKER_FILENAME).is_file():
                    found.append((model_entry.name, cp_entry.name, rev_entry.name, rev_entry))
    return found


def _prune_empty_ancestors(checkpoint_dir: Path, model_dir: Path) -> None:
    for d in (checkpoint_dir, model_dir):
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


def remove_model(
    ctx: JobContext,
    model_id: str,
    checkpoint_id: str,
    revision_id: str,
    *,
    force: bool = False,
    data_dir: Path | None = None,
    storage_dir: Path | None = None,
    bundled_path: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
    hardware: HardwareInfo | None = None,
    pack_manager: PackManager | None = None,
    project_store: ProjectStore | None = None,
) -> ModelRemoveResult:
    """Remove an installed model revision unless pinned (without force), then prune unused pack."""
    _validate_id_segment(model_id, "model_id")
    _validate_id_segment(checkpoint_id, "checkpoint_id")
    _validate_id_segment(revision_id, "revision_id")

    ctx.checkpoint()
    storage = get_storage_dir() if storage_dir is None else storage_dir
    models_root = models_dir(storage)
    rev_dir = models_root / model_id / checkpoint_id / revision_id
    part_dir = models_root / model_id / checkpoint_id / f"{revision_id}.part"

    with _revision_op_lock(
        models_root,
        model_id,
        checkpoint_id,
        revision_id,
        error_kind="internal",
    ):
        ctx.checkpoint()
        if not force:
            pins = _collect_pins_by_revision(data_dir=data_dir, project_store=project_store)
            pinning_projects = pins.get((model_id, checkpoint_id, revision_id), [])
            if pinning_projects:
                project_names = ", ".join(p.name for p in pinning_projects)
                raise SkaldError(
                    "model_in_use",
                    (
                        f"Cannot remove {model_id}/{checkpoint_id}/{revision_id} "
                        f"because it is pinned by {len(pinning_projects)} project(s)."
                    ),
                    details={
                        "model_id": model_id,
                        "checkpoint_id": checkpoint_id,
                        "revision_id": revision_id,
                        "projects": [p.model_dump(mode="json") for p in pinning_projects],
                    },
                    hint=f"Still pinned by: {project_names}. Remove with force=true to override.",
                )

        ctx.progress(0.3, f"Removing {model_id}/{checkpoint_id}/{revision_id}", "remove")
        was_present = rev_dir.exists() or part_dir.exists()
        if rev_dir.exists():
            _rmtree(rev_dir)
        if part_dir.exists():
            _rmtree(part_dir)
        _prune_empty_ancestors(models_root / model_id / checkpoint_id, models_root / model_id)

        removed_packs: list[str] = []
        view = get_catalog(
            data_dir=data_dir,
            models_root=models_root,
            bundled_path=bundled_path,
            adapters_path=adapters_path,
            app_version=app_version,
            hardware=hardware,
        )
        packs_by_model = {m.id: m.pack for m in view.models}
        target_pack = packs_by_model.get(model_id)
        if target_pack is not None:
            still_used_packs = {
                packs_by_model.get(m_id)
                for m_id, _, _, _ in _scan_installed_revisions(models_root)
                if packs_by_model.get(m_id) is not None
            }
            if target_pack not in still_used_packs:
                ctx.progress(0.7, f"Removing unused pack {target_pack}", "pack")
                pm = PackManager(storage_dir=storage) if pack_manager is None else pack_manager
                pack_res = pm.remove(target_pack, storage_dir=storage)
                removed_packs = [str(p) for p in pack_res.get("removed_packs", [])]

        ctx.progress(1.0, f"Removed {model_id}/{checkpoint_id}/{revision_id}", "finalize")
        return ModelRemoveResult(
            model_id=model_id,
            checkpoint_id=checkpoint_id,
            revision_id=revision_id,
            removed=was_present,
            removed_packs=removed_packs,
        )


def submit_model_remove(
    manager: JobManager,
    model_id: str,
    checkpoint_id: str,
    revision_id: str,
    *,
    force: bool = False,
    **kwargs: Any,
) -> str:
    """Submit `remove_model` to `JobManager` and return its `job_id`."""
    return manager.submit(
        "models.remove",
        remove_model,
        model_id=model_id,
        checkpoint_id=checkpoint_id,
        revision_id=revision_id,
        force=force,
        **kwargs,
    )


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _, filenames in os.walk(path):
        root_path = Path(root)
        for name in filenames:
            fp = root_path / name
            try:
                if fp.is_file() and not fp.is_symlink():
                    total += fp.stat().st_size
            except OSError:
                pass
    return total


def list_installed_models(
    *,
    data_dir: Path | None = None,
    storage_dir: Path | None = None,
    bundled_path: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
    hardware: HardwareInfo | None = None,
    project_store: ProjectStore | None = None,
) -> InstalledModelsResult:
    """Scan `<storage>/models/` for `.complete` revisions with pin usage and cleanup candidates."""
    storage = get_storage_dir() if storage_dir is None else storage_dir
    models_root = models_dir(storage)

    view = get_catalog(
        data_dir=data_dir,
        models_root=models_root,
        bundled_path=bundled_path,
        adapters_path=adapters_path,
        app_version=app_version,
        hardware=hardware,
    )
    catalog_lookup: dict[tuple[str, str, str], bool] = {}
    for model in view.models:
        for cp in model.checkpoints:
            for rev in cp.revisions:
                catalog_lookup[(model.id, cp.id, rev.id)] = rev.id == cp.default_revision

    pins = _collect_pins_by_revision(data_dir=data_dir, project_store=project_store)

    revisions: list[InstalledModelRevision] = []
    cleanup_candidates: list[InstalledModelRevision] = []
    for model_id, checkpoint_id, revision_id, rev_dir in _scan_installed_revisions(models_root):
        key = (model_id, checkpoint_id, revision_id)
        still_in_catalog = key in catalog_lookup
        is_default = catalog_lookup.get(key, False)
        used_by = pins.get(key, [])
        marker = _read_complete_marker(rev_dir)
        installed_at = (
            marker.get("installed_at")
            if marker is not None and isinstance(marker.get("installed_at"), str)
            else None
        )
        entry = InstalledModelRevision(
            model_id=model_id,
            checkpoint_id=checkpoint_id,
            revision_id=revision_id,
            path=str(rev_dir),
            size_bytes=_dir_size_bytes(rev_dir),
            installed_at=installed_at,
            used_by=used_by,
            still_in_catalog=still_in_catalog,
            is_default=is_default,
        )
        revisions.append(entry)
        if not is_default and not used_by:
            cleanup_candidates.append(entry)

    return InstalledModelsResult(revisions=revisions, cleanup_candidates=cleanup_candidates)
