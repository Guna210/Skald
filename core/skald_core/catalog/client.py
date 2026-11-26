"""Catalog fetch, local caching, bundled fallback, and compatibility annotations."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from skald_core import __version__, net
from skald_core.catalog.schema import Catalog, parse_semver
from skald_core.catalog.validate import _REPO_ROOT, load_adapter_versions
from skald_core.hardware import probe_hardware, rate_model_fit
from skald_core.jobs.manager import JobContext, JobManager
from skald_core.project.store import atomic_write_json
from skald_core.rpc.server import SkaldError
from skald_core.schemas import (
    AnnotatedCatalogCheckpoint,
    AnnotatedCatalogModel,
    AnnotatedCatalogRevision,
    CatalogDataSource,
    CatalogRefreshResult,
    CatalogView,
    HardwareInfo,
    IncompatibilityReason,
)
from skald_core.storage import get_data_dir, models_dir

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/Guna210/Skald/master/catalog/catalog.json"
MAX_CATALOG_BYTES = 5 * 1024 * 1024
SUPPORTED_CATALOG_SCHEMA_VERSION = 1
CATALOG_CACHE_FILENAME = "catalog.cache.json"


def get_resource_root() -> Path:
    """Return the PyInstaller bundle root when frozen, else the repository root."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _REPO_ROOT


def get_bundled_catalog_path() -> Path:
    """Return the path to the bundled fallback catalog.json."""
    return get_resource_root() / "catalog" / "catalog.json"


def get_adapters_path() -> Path:
    """Return the path to the worker adapter registry file."""
    return get_resource_root() / "worker" / "skald_worker" / "adapters" / "__init__.py"


def get_catalog_cache_path(data_dir: Path | None = None) -> Path:
    """Return `<userData>/catalog.cache.json`."""
    root = get_data_dir() if data_dir is None else data_dir
    return root / CATALOG_CACHE_FILENAME


def resolve_catalog_url(url: str | None = None) -> str:
    """Resolve the remote catalog URL from explicit arg, `SKALD_CATALOG_URL`, or default."""
    if url is not None and url.strip():
        return url.strip()
    env_url = os.environ.get("SKALD_CATALOG_URL", "").strip()
    if env_url:
        return env_url
    return DEFAULT_CATALOG_URL


def parse_catalog_json(raw_text: str) -> Catalog:
    """Parse and validate untrusted catalog JSON with the `Catalog` Pydantic schema only."""
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise SkaldError(
            "catalog_invalid",
            f"Catalog JSON could not be parsed: {exc}",
            details={"error": str(exc)},
            hint="The catalog file is malformed.",
        ) from exc

    if not isinstance(data, dict):
        raise SkaldError(
            "catalog_invalid",
            "Catalog root must be a JSON object.",
            details={"type": type(data).__name__},
            hint="The catalog file is malformed.",
        )

    raw_version = data.get("schema_version")
    if (
        not isinstance(raw_version, bool)
        and isinstance(raw_version, int)
        and raw_version > SUPPORTED_CATALOG_SCHEMA_VERSION
    ):
        raise SkaldError(
            "catalog_invalid",
            (
                f"Catalog schema_version {raw_version} is newer than "
                f"supported version {SUPPORTED_CATALOG_SCHEMA_VERSION}."
            ),
            details={
                "reason": "schema_too_new",
                "schema_version": raw_version,
                "supported_version": SUPPORTED_CATALOG_SCHEMA_VERSION,
            },
            hint="Update Skald to use this catalog.",
        )

    try:
        return Catalog.model_validate(data)
    except (ValidationError, RecursionError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            details: object = json.loads(exc.json(include_url=False))
        else:
            details = {"error": str(exc)}
        raise SkaldError(
            "catalog_invalid",
            f"Catalog validation failed: {exc}",
            details=details,
            hint="The catalog file does not match the expected schema.",
        ) from exc


def _is_safe_id_segment(segment: str) -> bool:
    return bool(
        segment
        and segment not in {".", ".."}
        and "/" not in segment
        and "\\" not in segment
        and "\x00" not in segment
    )


def _is_revision_installed(
    models_root: Path,
    model_id: str,
    checkpoint_id: str,
    revision_id: str,
) -> bool:
    # Provisional marker check: T03.6 writes `.complete`; T04.1 may refine bundled revisions.
    if not (
        _is_safe_id_segment(model_id)
        and _is_safe_id_segment(checkpoint_id)
        and _is_safe_id_segment(revision_id)
    ):
        return False
    return (models_root / model_id / checkpoint_id / revision_id / ".complete").is_file()


def _check_revision_compatibility(
    *,
    family_adapter: str,
    min_adapter_version: str,
    adapter_versions: Mapping[str, str],
    app_too_old: bool,
) -> tuple[bool, IncompatibilityReason | None]:
    adapter_ver = adapter_versions.get(family_adapter)
    if adapter_ver is None:
        return False, "adapter_missing"
    if parse_semver(adapter_ver) < parse_semver(min_adapter_version):
        return False, "adapter_too_old"
    if app_too_old:
        return False, "app_too_old"
    return True, None


def annotate_catalog(
    catalog: Catalog,
    *,
    source: CatalogDataSource,
    adapter_versions: Mapping[str, str] | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
    models_root: Path | None = None,
    hardware: HardwareInfo | None = None,
    char_count: int | None = None,
) -> CatalogView:
    """Annotate a validated `Catalog` with compatibility, install, update, and fit state."""
    if adapter_versions is None:
        target_adapters = get_adapters_path() if adapters_path is None else adapters_path
        resolved_adapters: Mapping[str, str] = load_adapter_versions(target_adapters)
    else:
        resolved_adapters = adapter_versions

    resolved_models_root = models_dir() if models_root is None else models_root
    resolved_hardware = (
        hardware if hardware is not None else (probe_hardware() if catalog.models else None)
    )
    app_too_old = parse_semver(app_version) < parse_semver(catalog.min_app_version)

    annotated_models: list[AnnotatedCatalogModel] = []
    for model in catalog.models:
        assert resolved_hardware is not None
        model_fit = rate_model_fit(model.hardware, resolved_hardware, char_count=char_count)
        annotated_checkpoints: list[AnnotatedCatalogCheckpoint] = []
        for cp in model.checkpoints:
            rev_states: list[tuple[bool, IncompatibilityReason | None, bool]] = []
            default_state: tuple[bool, IncompatibilityReason | None, bool] | None = None

            for rev in cp.revisions:
                compat, reason = _check_revision_compatibility(
                    family_adapter=model.family_adapter,
                    min_adapter_version=rev.min_adapter_version,
                    adapter_versions=resolved_adapters,
                    app_too_old=app_too_old,
                )
                rev_installed = _is_revision_installed(
                    resolved_models_root,
                    model.id,
                    cp.id,
                    rev.id,
                )
                state = (compat, reason, rev_installed)
                rev_states.append(state)
                if rev.id == cp.default_revision:
                    default_state = state

            assert default_state is not None
            default_compat, default_reason, default_installed = default_state
            cp_installed = any(installed for _, _, installed in rev_states)
            default_upgradable = default_compat and not default_installed
            cp_update_available = cp_installed and default_upgradable

            annotated_revs: list[AnnotatedCatalogRevision] = []
            for rev, (compat, reason, rev_installed) in zip(cp.revisions, rev_states, strict=True):
                rev_update = rev_installed and rev.id != cp.default_revision and default_upgradable
                annotated_revs.append(
                    AnnotatedCatalogRevision(
                        id=rev.id,
                        bundled=rev.bundled,
                        min_adapter_version=rev.min_adapter_version,
                        source=rev.source,
                        files=rev.files,
                        changelog=rev.changelog,
                        compatible=compat,
                        reason=reason,
                        installed=rev_installed,
                        update_available=rev_update,
                    )
                )

            annotated_checkpoints.append(
                AnnotatedCatalogCheckpoint(
                    id=cp.id,
                    max_chars=cp.max_chars,
                    default_revision=cp.default_revision,
                    revisions=annotated_revs,
                    compatible=default_compat,
                    reason=default_reason,
                    installed=cp_installed,
                    update_available=cp_update_available,
                    fit=model_fit,
                )
            )

        model_compatible = any(cp.compatible for cp in annotated_checkpoints)
        model_reason = None if model_compatible else annotated_checkpoints[0].reason
        model_installed = any(cp.installed for cp in annotated_checkpoints)
        model_update_available = any(cp.update_available for cp in annotated_checkpoints)

        annotated_models.append(
            AnnotatedCatalogModel(
                id=model.id,
                name=model.name,
                status=model.status,
                family_adapter=model.family_adapter,
                pack=model.pack,
                summary=model.summary,
                license=model.license,
                languages=model.languages,
                capabilities=model.capabilities,
                hardware=model.hardware,
                notes=model.notes,
                checkpoints=annotated_checkpoints,
                compatible=model_compatible,
                reason=model_reason,
                installed=model_installed,
                update_available=model_update_available,
                fit=model_fit,
            )
        )

    return CatalogView(
        schema_version=catalog.schema_version,
        min_app_version=catalog.min_app_version,
        updated_at=catalog.updated_at,
        source=source,
        models=annotated_models,
    )


def get_catalog(
    *,
    data_dir: Path | None = None,
    models_root: Path | None = None,
    bundled_path: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
    hardware: HardwareInfo | None = None,
    char_count: int | None = None,
) -> CatalogView:
    """Return the cached catalog if valid, otherwise fall back to the bundled catalog."""
    cache_path = get_catalog_cache_path(data_dir)
    if cache_path.is_file():
        try:
            raw_cache = cache_path.read_text(encoding="utf-8")
            cached_catalog = parse_catalog_json(raw_cache)
            return annotate_catalog(
                cached_catalog,
                source="cache",
                adapters_path=adapters_path,
                app_version=app_version,
                models_root=models_root,
                hardware=hardware,
                char_count=char_count,
            )
        except (OSError, UnicodeDecodeError, SkaldError) as exc:
            logger.warning(
                "Cached catalog at %s is invalid (%s); falling back to bundled catalog",
                cache_path,
                exc,
            )

    fallback_path = get_bundled_catalog_path() if bundled_path is None else bundled_path
    try:
        raw_bundled = fallback_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkaldError(
            "catalog_invalid",
            f"Bundled catalog could not be read at {fallback_path}: {exc}",
            details={"path": str(fallback_path), "error": str(exc)},
            hint="Reinstall Skald to restore bundled application files.",
        ) from exc

    bundled_catalog = parse_catalog_json(raw_bundled)
    return annotate_catalog(
        bundled_catalog,
        source="bundled",
        adapters_path=adapters_path,
        app_version=app_version,
        models_root=models_root,
        hardware=hardware,
        char_count=char_count,
    )


def refresh_catalog(
    ctx: JobContext | None = None,
    *,
    url: str | None = None,
    data_dir: Path | None = None,
    models_root: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
) -> CatalogRefreshResult:
    """Fetch the remote catalog, validate it, atomically replace the cache, and annotate."""
    if ctx is not None:
        ctx.checkpoint()
        ctx.progress(0.0, "Fetching model catalog", "fetch")

    target_url = resolve_catalog_url(url)
    raw_text = net.get_text(target_url, max_bytes=MAX_CATALOG_BYTES)

    if ctx is not None:
        ctx.checkpoint()
        ctx.progress(0.5, "Validating model catalog", "validate")

    try:
        catalog = parse_catalog_json(raw_text)
    except SkaldError as exc:
        logger.warning("Remote catalog from %s failed validation: %s", target_url, exc.message)
        if ctx is not None:
            ctx.log("warning", f"Invalid remote catalog from {target_url}: {exc.message}")
        raise

    if ctx is not None:
        ctx.checkpoint()
        ctx.progress(0.8, "Saving catalog cache", "save")

    cache_path = get_catalog_cache_path(data_dir)
    atomic_write_json(cache_path, catalog.model_dump(mode="json"))

    view = annotate_catalog(
        catalog,
        source="cache",
        adapters_path=adapters_path,
        app_version=app_version,
        models_root=models_root,
    )

    if ctx is not None:
        ctx.progress(1.0, "Catalog refreshed", "done")

    return CatalogRefreshResult(
        updated_at=catalog.updated_at,
        model_count=len(catalog.models),
        source="cache",
        catalog=view,
    )


def submit_catalog_refresh(
    manager: JobManager,
    *,
    url: str | None = None,
    data_dir: Path | None = None,
    models_root: Path | None = None,
    adapters_path: Path | None = None,
    app_version: str = __version__,
) -> str:
    """Submit `catalog.refresh` to `JobManager` and return its `job_id`."""
    return manager.submit(
        "catalog.refresh",
        refresh_catalog,
        url=url,
        data_dir=data_dir,
        models_root=models_root,
        adapters_path=adapters_path,
        app_version=app_version,
    )
