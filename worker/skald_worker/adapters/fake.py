"""Deterministic fake TTS adapter for worker protocol and contract testing."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar, Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

from skald_worker.protocol import (
    Adapter,
    AudioResult,
    BlendVoiceSpec,
    Capability,
    CloneVoiceSpec,
    LoadResult,
    PresetVoiceSpec,
    VoiceInfo,
    WorkerError,
)

FakeMode = Literal["ok", "fail", "hang", "silence", "clip", "stdout_noise", "crash"]

_SAMPLE_RATE = 24000
_PRESET_VOICES: tuple[VoiceInfo, ...] = (
    VoiceInfo(id="fake_narrator", name="Fake Narrator", language="en", gender="neutral"),
    VoiceInfo(id="fake_alice", name="Fake Alice", language="en", gender="female"),
    VoiceInfo(id="fake_bob", name="Fake Bob", language="en", gender="male"),
)
_PRESET_IDS: frozenset[str] = frozenset(v.id for v in _PRESET_VOICES)


class FakeParams(BaseModel):
    """Parameter schema declared by the fake adapter."""

    model_config = ConfigDict(extra="forbid")

    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speech playback speed multiplier.",
    )
    pitch_shift: float = Field(
        default=0.0,
        ge=-12.0,
        le=12.0,
        description="Style pitch shift in semitones.",
    )
    fake_mode: FakeMode = Field(
        default="ok",
        description="Test mode controlling fake synthesis behaviour.",
    )


def _sine_wave(
    *,
    num_chars: int,
    seed: int,
    voice_key: str,
    speed: float,
    pitch_shift: float,
) -> npt.NDArray[np.float32]:
    duration_s = max(0.2, float(num_chars) / (15.0 * speed))
    n_samples = max(1, int(round(duration_s * _SAMPLE_RATE)))
    digest = hashlib.sha256(f"{seed}\0{voice_key}".encode()).digest()
    base_freq = 220.0 + float(int.from_bytes(digest[:4], "big") % 440)
    freq = base_freq * (2.0 ** (pitch_shift / 12.0))

    t = np.arange(n_samples, dtype=np.float64) / float(_SAMPLE_RATE)
    wave = 0.5 * np.sin(2.0 * np.pi * freq * t)
    fade = min(240, n_samples // 10)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float64)
        wave[:fade] *= ramp
        wave[-fade:] *= ramp[::-1]
    return np.asarray(wave, dtype=np.float32)


class FakeAdapter(Adapter):
    """Test adapter supporting all capabilities with deterministic 24 kHz sine output."""

    name: ClassVar[str] = "fake"
    version: ClassVar[str] = "0.1.0"
    capabilities: ClassVar[tuple[Capability, ...]] = (
        "presets",
        "blend",
        "clone",
        "design",
        "speed",
        "style",
    )
    max_chars: ClassVar[int] = 500
    languages: ClassVar[tuple[str, ...]] = (
        "en",
        "en-us",
        "en-gb",
        "es",
        "fr",
        "de",
        "it",
        "pt-br",
        "ja",
        "zh",
        "hi",
    )
    deterministic_cpu: ClassVar[bool] = True
    params_model: ClassVar[type[BaseModel]] = FakeParams

    def __init__(self) -> None:
        self._checkpoint_id: str | None = None

    def load(
        self,
        checkpoint_id: str,
        files_dir: Path,
        device: str,
        dtype: str,
        threads: int | None,
    ) -> LoadResult:
        del files_dir, threads
        resolved_dtype = "float32" if dtype == "auto" else dtype
        self._checkpoint_id = checkpoint_id
        return LoadResult(device=device, dtype=resolved_dtype, peak_vram_mb=None)

    def voices(self) -> list[VoiceInfo]:
        return list(_PRESET_VOICES)

    def _validate_language(self, language: str) -> None:
        if language.strip().lower() not in self.languages:
            raise WorkerError(
                "unsupported_format",
                f"Unsupported language {language!r} for fake adapter.",
                details={"language": language, "supported": list(self.languages)},
            )

    def _voice_key(
        self,
        voice: PresetVoiceSpec | BlendVoiceSpec | CloneVoiceSpec,
    ) -> str:
        if isinstance(voice, PresetVoiceSpec):
            if voice.id not in _PRESET_IDS:
                raise WorkerError(
                    "unsupported_format",
                    f"Unknown preset voice: {voice.id!r}",
                    details={"voice_id": voice.id},
                )
            return f"preset:{voice.id}"

        if isinstance(voice, BlendVoiceSpec):
            for part in voice.parts:
                if part.id not in _PRESET_IDS:
                    raise WorkerError(
                        "unsupported_format",
                        f"Unknown preset voice in blend: {part.id!r}",
                        details={"voice_id": part.id},
                    )
            parts_str = ",".join(f"{p.id}:{p.weight:.4f}" for p in voice.parts)
            return f"blend:{parts_str}"

        ref_path = Path(voice.reference_wav)
        if not ref_path.is_file():
            raise WorkerError(
                "unsupported_format",
                f"Reference WAV file not found: {voice.reference_wav}",
                details={"reference_wav": voice.reference_wav},
                hint="Provide an existing local WAV file for cloning.",
            )
        return f"clone:{ref_path.name}:{voice.reference_text or ''}"

    def synthesize(
        self,
        *,
        text: str,
        language: str,
        voice: PresetVoiceSpec | BlendVoiceSpec | CloneVoiceSpec,
        params: BaseModel,
        seed: int,
    ) -> AudioResult:
        assert isinstance(params, FakeParams)
        mode = params.fake_mode

        if mode == "fail":
            raise WorkerError(
                "internal",
                "Simulated synthesis failure (fake_mode='fail').",
                details={"fake_mode": "fail"},
                hint="Retry with fake_mode='ok'.",
            )
        if mode == "hang":
            while True:
                time.sleep(1.0)
        if mode == "crash":
            os._exit(3)

        self._validate_language(language)
        voice_key = self._voice_key(voice)

        if mode == "stdout_noise":
            print("fake stdout noise via print", flush=True)
            os.write(1, b"fake stdout noise via os.write(1)\n")
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "print('fake child stdout noise', flush=True)",
                ],
                check=True,
            )

        if mode == "silence":
            duration_s = max(0.2, float(len(text)) / (15.0 * params.speed))
            n_samples = max(1, int(round(duration_s * _SAMPLE_RATE)))
            return AudioResult(
                samples=np.zeros(n_samples, dtype=np.float32),
                sample_rate=_SAMPLE_RATE,
            )

        if mode == "clip":
            duration_s = max(0.2, float(len(text)) / (15.0 * params.speed))
            n_samples = max(1, int(round(duration_s * _SAMPLE_RATE)))
            samples = np.where(
                (np.arange(n_samples) % 2) == 0,
                np.float32(1.0),
                np.float32(-1.0),
            ).astype(np.float32)
            return AudioResult(samples=samples, sample_rate=_SAMPLE_RATE)

        samples = _sine_wave(
            num_chars=len(text),
            seed=seed,
            voice_key=voice_key,
            speed=params.speed,
            pitch_shift=params.pitch_shift,
        )
        return AudioResult(samples=samples, sample_rate=_SAMPLE_RATE)

    def design_sample(
        self,
        *,
        description: str,
        sample_text: str,
        language: str,
        seed: int,
    ) -> AudioResult:
        self._validate_language(language)
        samples = _sine_wave(
            num_chars=len(sample_text),
            seed=seed,
            voice_key=f"design:{description}",
            speed=1.0,
            pitch_shift=0.0,
        )
        return AudioResult(samples=samples, sample_rate=_SAMPLE_RATE)

    def unload(self) -> None:
        self._checkpoint_id = None
