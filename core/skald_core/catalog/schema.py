"""Pydantic schema models for the Skald model catalog."""

from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

COMMERCIAL_LICENSE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "NVIDIA Open Model License",
    }
)

MAX_ACTIVE_MODELS: int = 5
MIN_RELEASE_ACTIVE_MODELS: int = 3

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HF_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG_SCHEMA_PATH = (
    _REPO_ROOT / "catalog" / "catalog.schema.json"
    if (_REPO_ROOT / "catalog").is_dir()
    else Path("catalog/catalog.schema.json")
)

FileFormat = Literal["safetensors", "onnx", "gguf", "npz", "json", "text", "pickle"]
SourceHost = Literal["huggingface", "github-release"]
ModelStatus = Literal["active", "retired"]


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse an X.Y.Z semver string into a comparable 3-tuple of ints."""
    match = _SEMVER_RE.match(version)
    if match is None:
        raise ValueError(f"Invalid semver version {version!r}; expected 'X.Y.Z'.")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


class CatalogFile(BaseModel):
    """A single downloadable model or metadata file pinned by size and SHA-256."""

    path: str = Field(min_length=1)
    format: FileFormat
    size: int = Field(gt=0)
    sha256: str
    approved_exception: str | None = None

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value:
            raise ValueError(f"File path {value!r} must be a relative POSIX path.")
        if ".." in value.split("/"):
            raise ValueError(f"File path {value!r} must not contain '..'.")
        return value

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if _SHA256_RE.match(value) is None:
            raise ValueError(f"Invalid sha256 {value!r}; expected 64 lowercase hex characters.")
        return value

    @model_validator(mode="after")
    def _validate_pickle_exception(self) -> CatalogFile:
        if self.format == "pickle" and (
            self.approved_exception is None or not self.approved_exception.strip()
        ):
            raise ValueError(
                f"File {self.path!r} uses 'pickle' format without a non-empty approved_exception."
            )
        return self


class CatalogSource(BaseModel):
    """Upstream hosting location and pinned revision/tag for a catalog revision."""

    host: SourceHost
    repo: str = Field(min_length=1)
    ref: str = Field(min_length=1)

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, value: str) -> str:
        if _REPO_RE.match(value) is None:
            raise ValueError(f"Invalid repo {value!r}; expected 'owner/name'.")
        return value

    @model_validator(mode="after")
    def _validate_ref(self) -> CatalogSource:
        if self.host == "huggingface" and _HF_COMMIT_RE.match(self.ref) is None:
            raise ValueError(
                f"Hugging Face source ref {self.ref!r} must be a 40-char lowercase hex commit SHA."
            )
        return self


def build_file_url(source: CatalogSource, file_path: str) -> str:
    """Build the canonical download URL for a file in a catalog source."""
    clean_path = file_path.lstrip("/")
    if source.host == "huggingface":
        return f"https://huggingface.co/{source.repo}/resolve/{source.ref}/{clean_path}"
    return f"https://github.com/{source.repo}/releases/download/{source.ref}/{clean_path}"


class CatalogLicense(BaseModel):
    """License metadata and commercial-use flag for a catalog model."""

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    commercial: bool
    acknowledgement: str | None = None

    @model_validator(mode="after")
    def _validate_commercial_and_ack(self) -> CatalogLicense:
        expected = self.name in COMMERCIAL_LICENSE_ALLOWLIST
        if self.commercial != expected:
            raise ValueError(
                f"License {self.name!r} requires commercial={expected}, got {self.commercial}."
            )
        if not self.commercial:
            if not self.url.strip():
                raise ValueError("Non-commercial license requires a non-empty url.")
            if self.acknowledgement is None or not self.acknowledgement.strip():
                raise ValueError("Non-commercial license requires non-empty acknowledgement text.")
        return self


class CpuHardware(BaseModel):
    """CPU hardware requirements and reference speed for a model."""

    min_ram_gb: float = Field(gt=0)
    rtf_reference: float | None = Field(default=None, gt=0)


class CudaHardware(BaseModel):
    """NVIDIA CUDA hardware requirements and reference speed for a model."""

    min_vram_gb: float = Field(gt=0)
    min_ram_gb: float | None = Field(default=None, gt=0)
    rtf_reference: float | None = Field(default=None, gt=0)


class CatalogHardware(BaseModel):
    """Supported hardware tiers for a catalog model."""

    cpu: CpuHardware | None = None
    cuda: CudaHardware | None = None


class CatalogNotes(BaseModel):
    """Additional model notes such as watermark disclosure."""

    watermark: str | None = None


class CatalogRevision(BaseModel):
    """A pinned upstream revision of a checkpoint."""

    id: str = Field(min_length=1)
    bundled: bool = False
    min_adapter_version: str
    source: CatalogSource
    files: list[CatalogFile] = Field(min_length=1)
    changelog: str = ""

    @field_validator("min_adapter_version")
    @classmethod
    def _validate_min_adapter_version(cls, value: str) -> str:
        parse_semver(value)
        return value


class CatalogCheckpoint(BaseModel):
    """A selectable model checkpoint with one or more pinned revisions."""

    id: str = Field(min_length=1)
    max_chars: int = Field(gt=0)
    default_revision: str = Field(min_length=1)
    revisions: list[CatalogRevision] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_revisions(self) -> CatalogCheckpoint:
        seen: set[str] = set()
        for rev in self.revisions:
            if rev.id in seen:
                raise ValueError(f"Duplicate revision id {rev.id!r} in checkpoint {self.id!r}.")
            seen.add(rev.id)
        if self.default_revision not in seen:
            raise ValueError(
                f"default_revision {self.default_revision!r} not found in checkpoint {self.id!r}."
            )
        return self


class CatalogModel(BaseModel):
    """A model family entry in the Skald catalog."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: ModelStatus
    family_adapter: str = Field(min_length=1)
    pack: str | None = None
    summary: str = Field(min_length=1)
    license: CatalogLicense
    languages: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    hardware: CatalogHardware
    notes: CatalogNotes = Field(default_factory=CatalogNotes)
    checkpoints: list[CatalogCheckpoint] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_checkpoints(self) -> CatalogModel:
        seen: set[str] = set()
        for cp in self.checkpoints:
            if cp.id in seen:
                raise ValueError(f"Duplicate checkpoint id {cp.id!r} in model {self.id!r}.")
            seen.add(cp.id)
        return self


class Catalog(BaseModel):
    """Top-level Skald model catalog document."""

    schema_version: Literal[1] = 1
    min_app_version: str
    updated_at: str
    models: list[CatalogModel] = Field(default_factory=list)

    @field_validator("min_app_version")
    @classmethod
    def _validate_min_app_version(cls, value: str) -> str:
        parse_semver(value)
        return value

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: str) -> str:
        datetime.date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def _validate_models(self) -> Catalog:
        seen: set[str] = set()
        active_count = 0
        for model in self.models:
            if model.id in seen:
                raise ValueError(f"Duplicate model id {model.id!r} in catalog.")
            seen.add(model.id)
            if model.status == "active":
                active_count += 1
        if active_count > MAX_ACTIVE_MODELS:
            raise ValueError(
                f"Catalog has {active_count} active models; maximum allowed is {MAX_ACTIVE_MODELS}."
            )
        return self


def export_catalog_schema(out_path: Path | None = None) -> Path:
    """Write Catalog JSON Schema to out_path (default: catalog/catalog.schema.json)."""
    target = DEFAULT_CATALOG_SCHEMA_PATH if out_path is None else out_path
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(Catalog.model_json_schema(), indent=2) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `python -m skald_core.catalog.schema [out_path]`."""
    parser = argparse.ArgumentParser(description="Export Skald catalog JSON Schema.")
    parser.add_argument(
        "out_path",
        nargs="?",
        type=Path,
        default=DEFAULT_CATALOG_SCHEMA_PATH,
        help="Output JSON Schema path (default: catalog/catalog.schema.json).",
    )
    args = parser.parse_args(argv)
    export_catalog_schema(args.out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
