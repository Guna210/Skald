"""Worker JSON-RPC 2.0 stdio server, stdout protection, and adapter base contract."""

from __future__ import annotations

import json
import logging
import os
import platform
import secrets
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Annotated, Any, ClassVar, Literal

import numpy as np
import numpy.typing as npt
import soundfile as sf
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from skald_worker import __version__

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_ERROR = -32000

logger = logging.getLogger(__name__)

# Subset of core ErrorKind values (SPEC B8) valid for worker application errors.
WorkerErrorKind = Literal[
    "internal",
    "out_of_memory",
    "adapter_unavailable",
    "unsupported_format",
]

Capability = Literal["presets", "blend", "clone", "design", "speed", "style"]
DTypeOption = Literal["auto", "float32", "float16", "bfloat16"]

JsonId = str | int | float | None
HandlerFn = Callable[..., Any]


class WorkerError(Exception):
    """Application-level error mapped to JSON-RPC error code -32000 (or specified RPC code)."""

    def __init__(
        self,
        kind: WorkerErrorKind,
        message: str,
        details: Any = None,
        hint: str | None = None,
        *,
        code: int = APP_ERROR,
    ) -> None:
        super().__init__(message)
        self.kind: WorkerErrorKind = kind
        self.message = message
        self.details = details
        self.hint = hint
        self.code = code

    def to_error_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "data": {
                "kind": self.kind,
                "details": self.details,
                "hint": self.hint,
            },
        }


class PresetVoiceSpec(BaseModel):
    """Preset voice specification."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["preset"] = "preset"
    id: str = Field(min_length=1)
    style: dict[str, Any] | None = None


class BlendPart(BaseModel):
    """Single preset component and weight in a blended voice."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    weight: float = Field(ge=0.0)


class BlendVoiceSpec(BaseModel):
    """Blended preset voice specification."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["blend"] = "blend"
    parts: list[BlendPart] = Field(min_length=1)
    style: dict[str, Any] | None = None

    @field_validator("parts")
    @classmethod
    def _validate_positive_total_weight(cls, parts: list[BlendPart]) -> list[BlendPart]:
        if sum(part.weight for part in parts) <= 0.0:
            raise ValueError("Blend parts must have positive total weight.")
        return parts


class CloneVoiceSpec(BaseModel):
    """Cloned voice specification referencing a local WAV clip."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["clone"] = "clone"
    reference_wav: str = Field(min_length=1)
    reference_text: str | None = None
    style: dict[str, Any] | None = None


VoiceSpec = Annotated[
    PresetVoiceSpec | BlendVoiceSpec | CloneVoiceSpec,
    Field(discriminator="kind"),
]


class VoiceInfo(BaseModel):
    """Preset voice entry returned by `worker.voices`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    language: str
    gender: str | None = None


class HelloResult(BaseModel):
    """Response payload for `worker.hello`."""

    model_config = ConfigDict(extra="forbid")

    adapter: str
    adapter_version: str
    worker_version: str
    python: str
    torch: str | None = None
    device_options: list[str]
    capabilities: list[Capability]
    max_chars: int
    languages: list[str]
    deterministic_cpu: bool
    params_schema: dict[str, Any]


class LoadParams(BaseModel):
    """Request parameters for `worker.load`."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1)
    files_dir: str = Field(min_length=1)
    device: str = Field(min_length=1)
    dtype: DTypeOption = "auto"
    threads: int | None = Field(default=None, ge=1)


class LoadResponse(BaseModel):
    """Response payload for `worker.load`."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    checkpoint_id: str
    device: str
    dtype: str
    load_time_s: float
    peak_vram_mb: float | None = None


class VoicesResponse(BaseModel):
    """Response payload for `worker.voices`."""

    model_config = ConfigDict(extra="forbid")

    voices: list[VoiceInfo]


class SynthesizeParams(BaseModel):
    """Request parameters for `worker.synthesize`."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    language: str = Field(min_length=1)
    voice: VoiceSpec
    params: dict[str, Any] = Field(default_factory=dict)
    seed: int = Field(ge=0)
    out_path: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _validate_text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty or whitespace-only.")
        return value


class DesignSampleParams(BaseModel):
    """Request parameters for `worker.design_sample`."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    sample_text: str = Field(min_length=1)
    language: str = Field(min_length=1)
    seed: int = Field(ge=0)
    out_path: str = Field(min_length=1)

    @field_validator("description", "sample_text")
    @classmethod
    def _validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field must not be empty or whitespace-only.")
        return value


class AudioMetricsResponse(BaseModel):
    """Response payload for `worker.synthesize` and `worker.design_sample`."""

    model_config = ConfigDict(extra="forbid")

    sample_rate: int
    duration_s: float
    rtf: float
    peak_vram_mb: float | None = None


class EmptyParamsModel(BaseModel):
    """Default empty parameter schema for adapters without custom parameters."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class LoadResult:
    """In-memory result returned by `Adapter.load`."""

    device: str
    dtype: str
    peak_vram_mb: float | None = None


@dataclass(frozen=True)
class AudioResult:
    """In-memory mono audio samples returned by adapter synthesis methods."""

    samples: npt.NDArray[np.float32]
    sample_rate: int
    peak_vram_mb: float | None = None


class Adapter(ABC):
    """Base class implemented by every Skald TTS worker adapter."""

    name: ClassVar[str]
    version: ClassVar[str]
    capabilities: ClassVar[tuple[Capability, ...]]
    max_chars: ClassVar[int]
    languages: ClassVar[tuple[str, ...]]
    deterministic_cpu: ClassVar[bool]
    params_model: ClassVar[type[BaseModel]] = EmptyParamsModel

    def torch_version(self) -> str | None:
        return None

    def device_options(self) -> list[str]:
        return ["cpu"]

    def check_dependencies(self) -> None:
        """Raise an exception if runtime dependencies for this adapter are missing."""

    @abstractmethod
    def load(
        self,
        checkpoint_id: str,
        files_dir: Path,
        device: str,
        dtype: str,
        threads: int | None,
    ) -> LoadResult:
        """Load the requested checkpoint into memory."""

    @abstractmethod
    def voices(self) -> list[VoiceInfo]:
        """Return preset voices for the loaded checkpoint."""

    @abstractmethod
    def synthesize(
        self,
        *,
        text: str,
        language: str,
        voice: PresetVoiceSpec | BlendVoiceSpec | CloneVoiceSpec,
        params: BaseModel,
        seed: int,
    ) -> AudioResult:
        """Synthesize a single chunk into mono float32 samples at native rate."""

    def design_sample(
        self,
        *,
        description: str,
        sample_text: str,
        language: str,
        seed: int,
    ) -> AudioResult:
        """Design a voice sample from a text description (design-capable adapters only)."""
        raise NotImplementedError(f"Adapter {self.name!r} does not support design_sample.")

    @abstractmethod
    def unload(self) -> None:
        """Release model resources from memory."""


def write_wav_atomic(out_path: Path, samples: npt.NDArray[np.float32], sample_rate: int) -> float:
    """Write mono PCM_16 WAV to a temp file in `out_path.parent` and atomically os.replace."""
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim != 1 or arr.size == 0:
        raise WorkerError("internal", "Adapter produced invalid or empty mono audio array.")
    if not bool(np.all(np.isfinite(arr))):
        raise WorkerError("internal", "Adapter produced non-finite audio samples.")
    if sample_rate <= 0:
        raise WorkerError("internal", f"Invalid sample rate: {sample_rate}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.parent / f".{out_path.stem}.{secrets.token_hex(4)}.tmp.wav"
    try:
        sf.write(str(tmp_path), arr, sample_rate, subtype="PCM_16", format="WAV")
        os.replace(tmp_path, out_path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return float(arr.shape[0]) / float(sample_rate)


def _error_response(
    req_id: JsonId,
    code: int,
    message: str,
    *,
    details: Any = None,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": code,
            "message": message,
            "data": {
                "kind": "internal",
                "details": details,
                "hint": None,
            },
        },
    }


def _is_valid_id(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (str, int, float, type(None)))


def _serialize_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class _MethodEntry:
    handler: HandlerFn
    params_model: type[BaseModel] | None
    result_model: type[BaseModel] | None


class WorkerRpcServer:
    """Thread-safe newline-delimited JSON-RPC 2.0 server for worker processes."""

    def __init__(
        self,
        adapter: Adapter,
        stdin: IO[bytes],
        stdout: IO[bytes],
    ) -> None:
        self._adapter = adapter
        self._stdin = stdin
        self._stdout = stdout
        self._write_lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._loaded = False
        self._methods: dict[str, _MethodEntry] = {}

        self.register("worker.hello", self._handle_hello, result_model=HelloResult)
        self.register("worker.load", self._handle_load, LoadParams, LoadResponse)
        self.register("worker.voices", self._handle_voices, result_model=VoicesResponse)
        self.register(
            "worker.synthesize",
            self._handle_synthesize,
            SynthesizeParams,
            AudioMetricsResponse,
        )
        if "design" in adapter.capabilities:
            self.register(
                "worker.design_sample",
                self._handle_design_sample,
                DesignSampleParams,
                AudioMetricsResponse,
            )
        self.register("worker.unload", self._handle_unload)
        self.register("worker.shutdown", self._handle_shutdown)

    def register(
        self,
        method_name: str,
        handler: HandlerFn,
        params_model: type[BaseModel] | None = None,
        result_model: type[BaseModel] | None = None,
    ) -> None:
        self._methods[method_name] = _MethodEntry(
            handler=handler,
            params_model=params_model,
            result_model=result_model,
        )

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise WorkerError(
                "adapter_unavailable",
                "No checkpoint is loaded; call worker.load first.",
                hint="Load a checkpoint before calling this method.",
            )

    def _handle_hello(self) -> HelloResult:
        return HelloResult(
            adapter=self._adapter.name,
            adapter_version=self._adapter.version,
            worker_version=__version__,
            python=platform.python_version(),
            torch=self._adapter.torch_version(),
            device_options=list(self._adapter.device_options()),
            capabilities=list(self._adapter.capabilities),
            max_chars=self._adapter.max_chars,
            languages=list(self._adapter.languages),
            deterministic_cpu=self._adapter.deterministic_cpu,
            params_schema=self._adapter.params_model.model_json_schema(),
        )

    def _handle_load(self, params: LoadParams) -> LoadResponse:
        available_devices = self._adapter.device_options()
        if params.device not in available_devices:
            raise WorkerError(
                "adapter_unavailable",
                f"Device {params.device!r} is not available; options: {available_devices}",
                details={"device": params.device, "device_options": available_devices},
                hint="Choose one of the devices reported by worker.hello.",
            )

        if self._loaded:
            self._adapter.unload()
            self._loaded = False

        t0 = time.perf_counter()
        result = self._adapter.load(
            checkpoint_id=params.checkpoint_id,
            files_dir=Path(params.files_dir),
            device=params.device,
            dtype=params.dtype,
            threads=params.threads,
        )
        load_time_s = time.perf_counter() - t0
        self._loaded = True
        return LoadResponse(
            ok=True,
            checkpoint_id=params.checkpoint_id,
            device=result.device,
            dtype=result.dtype,
            load_time_s=load_time_s,
            peak_vram_mb=result.peak_vram_mb,
        )

    def _handle_voices(self) -> VoicesResponse:
        self._require_loaded()
        return VoicesResponse(voices=self._adapter.voices())

    def _handle_synthesize(self, params: SynthesizeParams) -> AudioMetricsResponse:
        self._require_loaded()

        if len(params.text) > self._adapter.max_chars:
            raise WorkerError(
                "internal",
                "Invalid params",
                details=[
                    {
                        "loc": ["text"],
                        "msg": (
                            f"Text length ({len(params.text)}) exceeds max_chars "
                            f"({self._adapter.max_chars})."
                        ),
                        "type": "value_error",
                    }
                ],
                code=INVALID_PARAMS,
            )

        required_cap_by_kind: dict[str, Capability] = {
            "preset": "presets",
            "blend": "blend",
            "clone": "clone",
        }
        required_cap = required_cap_by_kind[params.voice.kind]
        if required_cap not in self._adapter.capabilities:
            raise WorkerError(
                "unsupported_format",
                f"Adapter {self._adapter.name!r} does not support {params.voice.kind!r} voices.",
                details={"voice_kind": params.voice.kind},
            )

        merged_params: dict[str, Any] = {}
        if params.voice.style is not None:
            merged_params.update(params.voice.style)
        merged_params.update(params.params)

        try:
            validated_adapter_params = self._adapter.params_model.model_validate(merged_params)
        except ValidationError as exc:
            raise WorkerError(
                "internal",
                "Invalid params",
                details=json.loads(exc.json(include_url=False)),
                code=INVALID_PARAMS,
            ) from exc

        t0 = time.perf_counter()
        audio = self._adapter.synthesize(
            text=params.text,
            language=params.language,
            voice=params.voice,
            params=validated_adapter_params,
            seed=params.seed,
        )
        duration_s = write_wav_atomic(Path(params.out_path), audio.samples, audio.sample_rate)
        elapsed_s = time.perf_counter() - t0
        rtf = elapsed_s / duration_s if duration_s > 0 else 0.0
        return AudioMetricsResponse(
            sample_rate=audio.sample_rate,
            duration_s=duration_s,
            rtf=rtf,
            peak_vram_mb=audio.peak_vram_mb,
        )

    def _handle_design_sample(self, params: DesignSampleParams) -> AudioMetricsResponse:
        self._require_loaded()

        if len(params.sample_text) > self._adapter.max_chars:
            raise WorkerError(
                "internal",
                "Invalid params",
                details=[
                    {
                        "loc": ["sample_text"],
                        "msg": (
                            f"sample_text length ({len(params.sample_text)}) exceeds max_chars "
                            f"({self._adapter.max_chars})."
                        ),
                        "type": "value_error",
                    }
                ],
                code=INVALID_PARAMS,
            )

        t0 = time.perf_counter()
        audio = self._adapter.design_sample(
            description=params.description,
            sample_text=params.sample_text,
            language=params.language,
            seed=params.seed,
        )
        duration_s = write_wav_atomic(Path(params.out_path), audio.samples, audio.sample_rate)
        elapsed_s = time.perf_counter() - t0
        rtf = elapsed_s / duration_s if duration_s > 0 else 0.0
        return AudioMetricsResponse(
            sample_rate=audio.sample_rate,
            duration_s=duration_s,
            rtf=rtf,
            peak_vram_mb=audio.peak_vram_mb,
        )

    def _handle_unload(self) -> dict[str, bool]:
        if self._loaded:
            self._adapter.unload()
            self._loaded = False
        return {"ok": True}

    def _handle_shutdown(self) -> dict[str, bool]:
        self._handle_unload()
        self._shutdown_event.set()
        return {"ok": True}

    def _write_bytes(self, data: bytes) -> None:
        with self._write_lock:
            self._stdout.write(data + b"\n")
            self._stdout.flush()

    def _write_message(self, payload: dict[str, Any]) -> None:
        try:
            encoded = _serialize_json_bytes(payload)
        except (TypeError, ValueError) as exc:
            logger.exception("Failed to serialize JSON-RPC payload")
            if "id" in payload:
                fallback = _error_response(
                    payload["id"],
                    INTERNAL_ERROR,
                    "Internal error",
                    details=str(exc),
                )
                try:
                    encoded = _serialize_json_bytes(fallback)
                except (TypeError, ValueError):
                    safe_fallback = _error_response(
                        None,
                        INTERNAL_ERROR,
                        "Internal error",
                        details="Unserializable response payload",
                    )
                    encoded = _serialize_json_bytes(safe_fallback)
                self._write_bytes(encoded)
                return
            raise
        self._write_bytes(encoded)

    def handle_line(self, raw_line: str) -> dict[str, Any] | None:
        """Parse and dispatch a single JSON-RPC 2.0 line, returning a response or None."""
        if not raw_line.strip():
            return None

        try:
            msg = json.loads(raw_line)
        except (json.JSONDecodeError, RecursionError):
            return _error_response(None, PARSE_ERROR, "Parse error")

        if not isinstance(msg, dict):
            return _error_response(None, INVALID_REQUEST, "Invalid Request")

        has_id = "id" in msg
        raw_id = msg.get("id")
        if has_id and not _is_valid_id(raw_id):
            return _error_response(None, INVALID_REQUEST, "Invalid Request")

        req_id: JsonId = raw_id if has_id else None

        if msg.get("jsonrpc") != "2.0":
            return _error_response(req_id, INVALID_REQUEST, "Invalid Request")

        method = msg.get("method")
        if not isinstance(method, str) or not method:
            return _error_response(req_id, INVALID_REQUEST, "Invalid Request")

        entry = self._methods.get(method)
        if entry is None:
            if not has_id:
                logger.warning("Ignoring notification for unknown method %r", method)
                return None
            return _error_response(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")

        raw_params = msg.get("params")
        validated_params: BaseModel | None = None

        if entry.params_model is not None:
            candidate = {} if raw_params is None else raw_params
            try:
                validated_params = entry.params_model.model_validate(candidate)
            except ValidationError as exc:
                if not has_id:
                    logger.warning("Ignoring notification %r with invalid params", method)
                    return None
                details = json.loads(exc.json(include_url=False))
                return _error_response(req_id, INVALID_PARAMS, "Invalid params", details=details)
        elif raw_params not in (None, {}):
            if not has_id:
                logger.warning("Ignoring notification %r with unexpected params", method)
                return None
            return _error_response(
                req_id,
                INVALID_PARAMS,
                "Invalid params",
                details=[{"msg": "Method takes no parameters"}],
            )

        try:
            if entry.params_model is not None:
                result = entry.handler(validated_params)
            else:
                result = entry.handler()
        except WorkerError as exc:
            logger.warning("Worker error in %s (%s): %s", method, exc.kind, exc.message)
            if not has_id:
                return None
            return {"jsonrpc": "2.0", "id": req_id, "error": exc.to_error_dict()}
        except Exception as exc:
            logger.exception("Unhandled error in worker method %s", method)
            if not has_id:
                return None
            return _error_response(req_id, INTERNAL_ERROR, "Internal error", details=str(exc))

        if not has_id:
            return None

        try:
            if entry.result_model is not None:
                if isinstance(result, entry.result_model):
                    serialized: Any = result.model_dump(mode="json")
                else:
                    serialized = entry.result_model.model_validate(result).model_dump(mode="json")
            elif isinstance(result, BaseModel):
                serialized = result.model_dump(mode="json")
            else:
                serialized = result
        except ValidationError as exc:
            logger.exception("Result validation failed for %s", method)
            return _error_response(req_id, INTERNAL_ERROR, "Internal error", details=str(exc))

        return {"jsonrpc": "2.0", "id": req_id, "result": serialized}

    def _read_line(self) -> str | None:
        raw = self._stdin.readline()
        if raw == b"":
            return None
        return raw.decode("utf-8")

    def serve(self) -> None:
        """Read JSON-RPC requests from stdin until EOF or `worker.shutdown`."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    line = self._read_line()
                except UnicodeDecodeError:
                    self._write_message(_error_response(None, PARSE_ERROR, "Parse error"))
                    continue
                if line is None:
                    break
                response = self.handle_line(line)
                if response is not None:
                    self._write_message(response)
        finally:
            if self._loaded:
                try:
                    self._adapter.unload()
                except Exception:
                    logger.exception("Error unloading adapter during worker exit")
                self._loaded = False


def protect_stdout() -> int:
    """Duplicate fd 1 to a private non-inheritable fd and redirect fd 1 and sys.stdout to stderr."""
    rpc_fd = os.dup(1)
    os.set_inheritable(rpc_fd, False)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return rpc_fd
