"""Tests for Pydantic schema models and JSON Schema export."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError

from skald_core.schemas import (
    EXPORTED_MODELS,
    Assignment,
    BlendPart,
    BlendVoiceSpec,
    Book,
    Chapter,
    Chunk,
    ChunkStatus,
    CloneVoiceSpec,
    DesignSource,
    ErrorKind,
    GpuInfo,
    HardwareInfo,
    JobRef,
    LexiconRule,
    Paragraph,
    PinnedModelRecord,
    PresetVoiceSpec,
    ProjectManifest,
    QcResult,
    RenderPlan,
    RenderRecord,
    Sentence,
    SkaldErrorData,
    SystemInfo,
    VoiceProfile,
    VoiceSpec,
)
from skald_core.schemas.export import DEFAULT_EXPORT_DIR, export_schemas

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_EXPECTED_MODEL_NAMES = {
    "ProjectManifest",
    "Book",
    "Chapter",
    "Paragraph",
    "Sentence",
    "Chunk",
    "LexiconRule",
    "VoiceSpec",
    "VoiceProfile",
    "Assignment",
    "RenderPlan",
    "RenderRecord",
    "ChunkStatus",
    "QcResult",
    "SystemInfo",
    "HardwareInfo",
    "JobRef",
    "SkaldErrorData",
}

_EXPECTED_ERROR_KINDS = {
    "offline",
    "epub_drm",
    "epub_invalid",
    "unsupported_format",
    "pack_install_failed",
    "model_download_failed",
    "checksum_mismatch",
    "worker_crashed",
    "out_of_memory",
    "not_enough_disk",
    "license_not_accepted",
    "adapter_unavailable",
    "ffmpeg_failed",
    "folder_not_empty",
    "project_invalid",
    "internal",
    "http_not_found",
    "http_error",
    "timeout",
}


def test_exported_models_cover_spec_and_have_docstrings_and_snake_case_fields() -> None:
    exported_names = {m.__name__ for m in EXPORTED_MODELS}
    assert exported_names == _EXPECTED_MODEL_NAMES

    all_models: tuple[type[BaseModel], ...] = (
        *EXPORTED_MODELS,
        GpuInfo,
        PresetVoiceSpec,
        BlendPart,
        BlendVoiceSpec,
        CloneVoiceSpec,
        DesignSource,
        PinnedModelRecord,
    )
    for model in all_models:
        assert model.__doc__ and model.__doc__.strip(), f"{model.__name__} missing docstring"
        for field_name in model.model_fields:
            assert _SNAKE_CASE_RE.match(field_name), (
                f"{model.__name__}.{field_name} is not snake_case"
            )


def test_default_export_dir_points_to_app_shared_schemas() -> None:
    assert DEFAULT_EXPORT_DIR.parts[-4:] == ("app", "src", "shared", "schemas")


def test_export_round_trip(tmp_path: Path) -> None:
    out_dir = tmp_path / "nested" / "schemas"
    written_dir = export_schemas(out_dir)
    assert written_dir == out_dir

    index_path = out_dir / "index.json"
    assert index_path.is_file()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == 1
    assert set(index["models"].keys()) == _EXPECTED_MODEL_NAMES

    for model in EXPORTED_MODELS:
        filename = index["models"][model.__name__]
        schema_path = out_dir / filename
        assert schema_path.is_file()
        parsed = json.loads(schema_path.read_text(encoding="utf-8"))
        assert parsed == model.model_json_schema()


@pytest.mark.timeout(10)
def test_export_cli_writes_into_target_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "cli_schemas"
    proc = subprocess.run(
        [sys.executable, "-m", "skald_core.schemas.export", str(out_dir)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert (out_dir / "index.json").is_file()
    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    assert set(index["models"].keys()) == _EXPECTED_MODEL_NAMES


def test_error_kind_closed_set_and_error_data_validation() -> None:
    assert set(get_args(ErrorKind)) == _EXPECTED_ERROR_KINDS

    err = SkaldErrorData(kind="http_not_found", details={"status": 404}, hint="Check URL")
    assert err.kind == "http_not_found"

    with pytest.raises(ValidationError):
        SkaldErrorData.model_validate({"kind": "not_a_real_kind", "details": None, "hint": None})


def test_core_models_round_trip_json() -> None:
    preset_spec = VoiceSpec.model_validate({"kind": "preset", "id": "af_heart", "style": {"x": 1}})
    blend_spec = VoiceSpec.model_validate(
        {"kind": "blend", "parts": [{"id": "af_heart", "weight": 0.6}]}
    )
    clone_spec = VoiceSpec.model_validate(
        {"kind": "clone", "reference_wav": "voices/v_1234abcd/reference.wav"}
    )
    assert isinstance(preset_spec.root, PresetVoiceSpec)
    assert isinstance(blend_spec.root, BlendVoiceSpec)
    assert isinstance(clone_spec.root, CloneVoiceSpec)

    profile = VoiceProfile(
        id="v_1234abcd",
        name="Narrator",
        model_id="kokoro",
        checkpoint_id="kokoro-v1.0",
        spec=clone_spec,
        calibrated_cps=15.5,
        created_at="2026-11-13T00:00:00Z",
        consent=True,
        design_source=DesignSource(description="warm alto", seed=42, checkpoint_id="qwen-design"),
    )
    sentence = Sentence(id="s_1", text="Hello world.")
    paragraph = Paragraph(id="p_1", text="Hello world.", sentences=[sentence])
    chapter = Chapter(id="ch_1", title="Chapter 1", paragraphs=[paragraph])
    book = Book(title="Sample", authors=["Author"], language="en-us", chapters=[chapter])
    chunk = Chunk(
        id="ck_1",
        chapter_id="ch_1",
        paragraph_id="p_1",
        index=0,
        text="Hello world.",
        voice_id="v_1234abcd",
        cache_key="abc",
    )
    lexicon_rule = LexiconRule(word="Skald", replacement="skahld")
    assignment = Assignment(narrator_voice_id="v_1234abcd")
    plan = RenderPlan(
        total_chunks=1,
        cached_chunks=0,
        todo_chunks=1,
        total_chars=12,
        estimated_seconds=1.0,
        chunks=[chunk],
    )
    qc = QcResult(duration_s=1.2, expected_duration_s=1.0, duration_ratio=1.2, passed=True)
    chunk_status = ChunkStatus(
        chunk_id="ck_1",
        chapter_id="ch_1",
        paragraph_id="p_1",
        status="done",
        cache_key="abc",
        seed=99,
        attempts=1,
        qc=qc,
    )
    hw = HardwareInfo(
        os="Linux",
        cpu_model="x86_64",
        physical_cores=4,
        logical_cores=8,
        ram_total_bytes=8_000_000_000,
        ram_free_bytes=4_000_000_000,
        disk_free_bytes=50_000_000_000,
        gpus=[
            GpuInfo(
                name="Tesla T4",
                memory_total_mb=15360,
                driver_version="550.54",
                compute_cap="7.5",
                bfloat16_capable=False,
            )
        ],
    )
    record = RenderRecord(
        render_id="rn_1234abcd",
        started_at="2026-11-13T00:00:00Z",
        versions={"core": "0.1.0"},
        os="Linux",
        hardware=hw,
        book_hash="hash_b",
        chapter_hashes={"ch_1": "hash_c"},
        lexicon_hash="hash_l",
        voices={"v_1234abcd": profile},
        models=[
            PinnedModelRecord(
                model_id="kokoro",
                checkpoint_id="kokoro-v1.0",
                revision_id="r1",
                adapter_version="1.0.0",
                file_hashes={"kokoro-v1.0.onnx": "deadbeef"},
            )
        ],
        base_seed=42,
        qc_summary={"passed": 1},
    )
    sys_info = SystemInfo(
        core="0.1.0",
        python="3.12.16",
        lxml="6.1.3",
        pydantic="2.14.3",
        numpy="2.5.4",
        ffmpeg="ffmpeg version n9.0.2",
    )
    job_ref = JobRef(job_id="job_1")
    manifest = ProjectManifest(
        schema_version=1,
        name="The Saga",
        created_at="2026-11-14T00:00:00Z",
        updated_at="2026-11-14T00:00:00Z",
        base_seed=12345,
        render_ids=["rn_1234abcd"],
        voice_ids=["v_1234abcd"],
    )

    for instance in (
        manifest,
        profile,
        book,
        chunk,
        lexicon_rule,
        assignment,
        plan,
        chunk_status,
        record,
        sys_info,
        job_ref,
    ):
        round_tripped = type(instance).model_validate_json(instance.model_dump_json())
        assert round_tripped == instance
