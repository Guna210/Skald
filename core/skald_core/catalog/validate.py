"""Catalog validator CLI and library functions."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from skald_core import net
from skald_core.catalog.schema import (
    MIN_RELEASE_ACTIVE_MODELS,
    Catalog,
    CatalogRevision,
    build_file_url,
    parse_semver,
)
from skald_core.rpc import SkaldError

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ADAPTERS_PATH = _REPO_ROOT / "worker" / "skald_worker" / "adapters" / "__init__.py"
DEFAULT_MODELS_DOC_DIR = _REPO_ROOT / "docs" / "models"


def load_adapter_versions(adapters_path: Path | None = None) -> dict[str, str]:
    """Read ADAPTER_VERSIONS dict literal from worker adapters __init__.py via AST."""
    target = DEFAULT_ADAPTERS_PATH if adapters_path is None else adapters_path
    if not target.is_file():
        return {}

    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(target))
    for node in tree.body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign):
            for target_node in node.targets:
                if isinstance(target_node, ast.Name) and target_node.id == "ADAPTER_VERSIONS":
                    value_node = node.value
                    break
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "ADAPTER_VERSIONS"
            and node.value is not None
        ):
            value_node = node.value

        if value_node is not None:
            raw = ast.literal_eval(value_node)
            if not isinstance(raw, dict):
                raise ValueError(f"ADAPTER_VERSIONS in {target} must be a dict literal.")
            versions: dict[str, str] = {}
            for k, v in raw.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise ValueError(
                        f"ADAPTER_VERSIONS in {target} must map str to str, got {k!r}: {v!r}."
                    )
                parse_semver(v)
                versions[k] = v
            return versions

    return {}


def _load_base_catalog_from_git(
    catalog_path: Path,
    base_ref: str = "origin/master",
) -> Catalog | None:
    """Load the base catalog from git if available; return None if it does not exist."""
    try:
        rel_path = catalog_path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        rel_path = catalog_path.as_posix()

    proc = subprocess.run(
        ["git", "show", f"{base_ref}:{rel_path}"],
        cwd=str(_REPO_ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        return Catalog.model_validate_json(proc.stdout)
    except ValidationError:
        return None


def _changed_revision_keys(
    current: Catalog,
    base: Catalog | None,
) -> set[tuple[str, str, str]]:
    """Return (model_id, checkpoint_id, revision_id) tuples that are new or modified vs base."""
    base_revs: dict[tuple[str, str, str], CatalogRevision] = {}
    if base is not None:
        for model in base.models:
            for cp in model.checkpoints:
                for rev in cp.revisions:
                    base_revs[(model.id, cp.id, rev.id)] = rev

    changed: set[tuple[str, str, str]] = set()
    for model in current.models:
        for cp in model.checkpoints:
            for rev in cp.revisions:
                key = (model.id, cp.id, rev.id)
                prev = base_revs.get(key)
                if prev is None or prev.model_dump() != rev.model_dump():
                    changed.add(key)
    return changed


def validate_catalog(
    catalog_path: Path,
    *,
    release: bool = False,
    network: bool = False,
    adapters_path: Path | None = None,
    models_doc_dir: Path | None = None,
    base_catalog: Catalog | None = None,
    use_git_diff: bool = True,
) -> list[str]:
    """Validate a catalog JSON file and return a list of error strings (empty if valid)."""
    errors: list[str] = []

    if not catalog_path.is_file():
        return [f"Catalog file not found: {catalog_path}"]

    try:
        raw_text = catalog_path.read_text(encoding="utf-8")
        catalog = Catalog.model_validate_json(raw_text)
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        return [f"Schema validation failed: {exc}"]

    active_models = [m for m in catalog.models if m.status == "active"]
    if release and len(active_models) < MIN_RELEASE_ACTIVE_MODELS:
        errors.append(
            f"Release catalog requires at least {MIN_RELEASE_ACTIVE_MODELS} active models, "
            f"found {len(active_models)}."
        )

    try:
        adapter_versions = load_adapter_versions(adapters_path)
    except (OSError, SyntaxError, ValueError) as exc:
        errors.append(f"Failed to read adapter registry: {exc}")
        adapter_versions = {}

    for model in catalog.models:
        adapter_ver = adapter_versions.get(model.family_adapter)
        if adapter_ver is None:
            errors.append(
                f"Model {model.id!r} references unknown family_adapter {model.family_adapter!r}."
            )
            continue
        installed_tuple = parse_semver(adapter_ver)
        for cp in model.checkpoints:
            for rev in cp.revisions:
                required_tuple = parse_semver(rev.min_adapter_version)
                if installed_tuple < required_tuple:
                    errors.append(
                        f"Model {model.id!r} checkpoint {cp.id!r} revision {rev.id!r} requires "
                        f"adapter {model.family_adapter!r} >= {rev.min_adapter_version}, "
                        f"but registry has {adapter_ver}."
                    )

    doc_dir = DEFAULT_MODELS_DOC_DIR if models_doc_dir is None else models_doc_dir
    for model in active_models:
        card_path = doc_dir / f"{model.id}.md"
        if not card_path.is_file():
            errors.append(f"Active model {model.id!r} is missing model card {card_path}.")

    if network:
        effective_base = base_catalog
        if effective_base is None and use_git_diff:
            effective_base = _load_base_catalog_from_git(catalog_path)
        if effective_base is None:
            print(
                "WARNING: origin/master catalog not available; treating all entries as changed.",
                file=sys.stderr,
            )
        changed_keys = _changed_revision_keys(catalog, effective_base)

        with tempfile.TemporaryDirectory(prefix="skald-catalog-check-") as tmp_dir:
            tmp_root = Path(tmp_dir)
            for model in catalog.models:
                for cp in model.checkpoints:
                    for rev in cp.revisions:
                        is_changed = (model.id, cp.id, rev.id) in changed_keys
                        for idx, f_entry in enumerate(rev.files):
                            url = build_file_url(rev.source, f_entry.path)
                            try:
                                net.head(url)
                            except SkaldError as exc:
                                errors.append(
                                    f"URL unreachable for {model.id}/{cp.id}/{rev.id} "
                                    f"file {f_entry.path!r} ({url}): {exc.message}"
                                )
                                continue

                            if is_changed:
                                dest = tmp_root / f"{model.id}_{cp.id}_{rev.id}_{idx}"
                                try:
                                    net.download(url, dest, f_entry.sha256, f_entry.size)
                                except SkaldError as exc:
                                    errors.append(
                                        f"Download verification failed for {model.id}/{cp.id}/"
                                        f"{rev.id} file {f_entry.path!r} ({url}): {exc.message}"
                                    )
                                finally:
                                    dest.unlink(missing_ok=True)

    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `python -m skald_core.catalog.validate`."""
    parser = argparse.ArgumentParser(description="Validate a Skald model catalog JSON file.")
    parser.add_argument(
        "catalog_path",
        type=Path,
        help="Path to catalog.json.",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help=(
            "Verify URLs are reachable and download/hash-check entries changed vs "
            "origin/master (if origin/master catalog is unavailable, warns and checks all)."
        ),
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help=f"Enforce release minimum of {MIN_RELEASE_ACTIVE_MODELS} active models.",
    )
    parser.add_argument(
        "--adapters-file",
        type=Path,
        default=None,
        help="Optional path to worker adapters __init__.py.",
    )
    args = parser.parse_args(argv)

    errors = validate_catalog(
        args.catalog_path,
        release=args.release,
        network=args.network,
        adapters_path=args.adapters_file,
    )
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"Catalog {args.catalog_path} is valid.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
