from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class MicrophoneLevelResult:
    ready: bool
    rms: float
    peak: float
    message: str


def analyze_microphone_wav(path: str | Path) -> MicrophoneLevelResult:
    source = Path(path).expanduser().resolve()
    with wave.open(str(source), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("Microphone test audio must be mono PCM16.")
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    if samples.size == 0:
        return MicrophoneLevelResult(False, 0.0, 0.0, "No microphone samples were captured.")
    signal = samples.astype(np.float32) / 32768.0
    rms = float(math.sqrt(float(np.mean(np.square(signal)))))
    peak = float(np.max(np.abs(signal)))
    if peak >= 0.98:
        return MicrophoneLevelResult(False, rms, peak, "Microphone is clipping; lower input level or move farther away.")
    if rms < 0.006:
        return MicrophoneLevelResult(False, rms, peak, "Microphone level is too low; speak closer or increase input level.")
    return MicrophoneLevelResult(True, rms, peak, "Microphone level is healthy.")
