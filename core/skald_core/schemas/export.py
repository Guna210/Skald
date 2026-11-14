"""CLI and helper for exporting Pydantic models to JSON Schema files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skald_core.schemas import EXPORTED_MODELS

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPORT_DIR = (
    _REPO_ROOT / "app" / "src" / "shared" / "schemas"
    if (_REPO_ROOT / "app").is_dir()
    else Path("app/src/shared/schemas")
)


def export_schemas(out_dir: Path | None = None) -> Path:
    """Write one JSON Schema per exported model plus index.json into out_dir."""
    target = DEFAULT_EXPORT_DIR if out_dir is None else out_dir
    target.mkdir(parents=True, exist_ok=True)

    index_models: dict[str, str] = {}
    for model in sorted(EXPORTED_MODELS, key=lambda m: m.__name__):
        filename = f"{model.__name__}.schema.json"
        schema_path = target / filename
        schema_text = json.dumps(model.model_json_schema(), indent=2) + "\n"
        schema_path.write_text(schema_text, encoding="utf-8")
        index_models[model.__name__] = filename

    index_payload = {"schema_version": 1, "models": index_models}
    (target / "index.json").write_text(
        json.dumps(index_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `python -m skald_core.schemas.export [dir]`."""
    parser = argparse.ArgumentParser(description="Export Skald Pydantic schemas to JSON Schema.")
    parser.add_argument(
        "out_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_EXPORT_DIR,
        help="Output directory (default: app/src/shared/schemas/).",
    )
    args = parser.parse_args(argv)
    export_schemas(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
