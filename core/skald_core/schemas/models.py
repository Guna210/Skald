"""Pydantic schema models for Skald core RPC, projects, text, voices, and rendering."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel

ErrorKind = Literal[
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
    "internal",
    "http_not_found",
    "http_error",
    "timeout",
]


class SkaldErrorData(BaseModel):
    """Structured error payload attached to JSON-RPC error responses."""

    kind: ErrorKind
    details: Any = None
    hint: str | None = None


class JobRef(BaseModel):
    """Reference returned when a background job is started."""

    job_id: str


JobState = Literal["queued", "running", "paused", "succeeded", "failed", "cancelled"]
JobFinishedStatus = Literal["succeeded", "failed", "cancelled"]


class JobError(BaseModel):
    """Serialized error payload attached to failed jobs, matching the B8 error object."""

    code: int
    message: str
    data: SkaldErrorData


class JobProgress(BaseModel):
    """Payload for `job.progress` notifications."""

    job_id: str
    fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    message: str = ""
    stage: str = ""


class JobLog(BaseModel):
    """Payload for `job.log` notifications."""

    job_id: str
    level: str
    message: str


class JobFinished(BaseModel):
    """Payload for `job.finished` notifications."""

    job_id: str
    status: JobFinishedStatus
    result: Any = None
    error: JobError | None = None


class JobStatus(BaseModel):
    """Current state returned by `job.status`, `job.cancel`, `job.pause`, and `job.resume`."""

    job_id: str
    kind: str
    status: JobState
    fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    message: str = ""
    stage: str = ""
    result: Any = None
    error: JobError | None = None


class SystemInfo(BaseModel):
    """Core, runtime dependency, and ffmpeg version strings."""

    core: str
    python: str
    lxml: str
    pydantic: str
    numpy: str
    ffmpeg: str | None = None


class GpuInfo(BaseModel):
    """NVIDIA GPU details reported by nvidia-smi."""

    name: str
    memory_total_mb: int
    driver_version: str
    compute_cap: str
    bfloat16_capable: bool


class HardwareInfo(BaseModel):
    """Host CPU, memory, disk, and NVIDIA GPU summary."""

    os: str
    cpu_model: str
    physical_cores: int
    logical_cores: int
    ram_total_bytes: int
    ram_free_bytes: int
    disk_free_bytes: int
    gpus: list[GpuInfo] = Field(default_factory=list)


class Sentence(BaseModel):
    """A single sentence inside a paragraph with a stable identifier."""

    id: str
    text: str


class Paragraph(BaseModel):
    """A paragraph of book text and its segmented sentences."""

    id: str
    text: str
    is_heading: bool = False
    unbalanced_quotes: bool = False
    sentences: list[Sentence] = Field(default_factory=list)


class Chapter(BaseModel):
    """A chapter in reading order with inclusion state and extracted paragraphs."""

    id: str
    title: str
    included: bool = True
    linear: bool = True
    skip_reasons: list[str] = Field(default_factory=list)
    paragraphs: list[Paragraph] = Field(default_factory=list)


class Book(BaseModel):
    """Normalized book metadata and chapter hierarchy."""

    title: str
    authors: list[str] = Field(default_factory=list)
    language: str | None = None
    cover_path: str | None = None
    source_path: str | None = None
    chapters: list[Chapter] = Field(default_factory=list)


class Chunk(BaseModel):
    """A synthesis-ready text chunk within a single paragraph."""

    id: str
    chapter_id: str
    paragraph_id: str
    index: int
    text: str
    role: Literal["narration", "dialogue"] = "narration"
    voice_id: str | None = None
    cache_key: str | None = None


class LexiconRule(BaseModel):
    """Per-project pronunciation replacement rule."""

    word: str
    replacement: str
    case_sensitive: bool = False
    whole_word: bool = True
    match_count: int = 0


class PresetVoiceSpec(BaseModel):
    """Preset voice specification passed to a worker."""

    kind: Literal["preset"] = "preset"
    id: str
    style: dict[str, Any] | None = None


class BlendPart(BaseModel):
    """Single preset component and weight in a blended voice."""

    id: str
    weight: float = Field(ge=0.0)


class BlendVoiceSpec(BaseModel):
    """Blended preset voice specification passed to a worker."""

    kind: Literal["blend"] = "blend"
    parts: list[BlendPart] = Field(min_length=1)
    style: dict[str, Any] | None = None


class CloneVoiceSpec(BaseModel):
    """Cloned voice specification referencing a local WAV clip."""

    kind: Literal["clone"] = "clone"
    reference_wav: str
    reference_text: str | None = None
    style: dict[str, Any] | None = None


class VoiceSpec(
    RootModel[
        Annotated[
            PresetVoiceSpec | BlendVoiceSpec | CloneVoiceSpec,
            Field(discriminator="kind"),
        ]
    ]
):
    """Discriminated union describing how a voice is synthesized."""


class DesignSource(BaseModel):
    """Provenance metadata for a voice designed from text and frozen as a clone."""

    description: str
    seed: int
    checkpoint_id: str


class VoiceProfile(BaseModel):
    """Saved voice profile in the user's library or frozen project lockfile."""

    id: str
    name: str
    model_id: str
    checkpoint_id: str
    spec: VoiceSpec
    style_params: dict[str, Any] = Field(default_factory=dict)
    calibrated_cps: float | None = None
    created_at: str
    consent: bool | None = None
    design_source: DesignSource | None = None


class Assignment(BaseModel):
    """Project voice assignments for narrator, dialogue, and overrides."""

    narrator_voice_id: str
    dialogue_voice_id: str | None = None
    chapter_overrides: dict[str, str] = Field(default_factory=dict)
    paragraph_overrides: dict[str, str] = Field(default_factory=dict)


class RenderPlan(BaseModel):
    """Summary of chunks to synthesize, cache hits, and estimated duration."""

    total_chunks: int
    cached_chunks: int
    todo_chunks: int
    total_chars: int
    estimated_seconds: float | None = None
    chunks: list[Chunk] = Field(default_factory=list)


class QcResult(BaseModel):
    """Per-chunk audio quality check metrics and pass/fail outcome."""

    duration_s: float
    expected_duration_s: float | None = None
    duration_ratio: float | None = None
    max_silence_s: float = 0.0
    clipped_fraction: float = 0.0
    empty_or_nan: bool = False
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class ChunkStatus(BaseModel):
    """Execution and quality check status for a single render chunk."""

    chunk_id: str
    chapter_id: str
    paragraph_id: str
    status: Literal["pending", "cached", "rendering", "done", "needs_review", "failed"]
    cache_key: str
    seed: int | None = None
    attempts: int = 0
    qc: QcResult | None = None
    error: str | None = None


class PinnedModelRecord(BaseModel):
    """Pinned model revision and file hashes recorded in render.json."""

    model_id: str
    checkpoint_id: str
    revision_id: str
    adapter_version: str
    file_hashes: dict[str, str] = Field(default_factory=dict)


class RenderRecord(BaseModel):
    """Reproducibility manifest written to renders/<render_id>/render.json."""

    render_id: str
    started_at: str
    finished_at: str | None = None
    versions: dict[str, str | None] = Field(default_factory=dict)
    os: str
    hardware: HardwareInfo | None = None
    book_hash: str
    chapter_hashes: dict[str, str] = Field(default_factory=dict)
    lexicon_hash: str
    voices: dict[str, VoiceProfile] = Field(default_factory=dict)
    models: list[PinnedModelRecord] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    base_seed: int
    qc_summary: dict[str, int] = Field(default_factory=dict)
    ffmpeg_version: str | None = None
    ffmpeg_commands: list[list[str]] = Field(default_factory=list)
