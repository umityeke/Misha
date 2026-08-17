from __future__ import annotations

import json
import math
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SpeakerVerification:
    accepted: bool
    score: float
    message: str


def _voice_features(wav_path: str | Path) -> np.ndarray:
    path = Path(wav_path).expanduser().resolve()
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("Voice identity samples must be mono 16-bit WAV.")
        sample_rate = audio.getframerate()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")

    if sample_rate < 8000 or samples.size < sample_rate:
        raise ValueError("Voice identity samples must contain at least one second of audio.")
    signal = samples.astype(np.float32) / 32768.0
    signal = signal - float(np.mean(signal))
    peak = float(np.max(np.abs(signal)))
    if peak < 0.01:
        raise ValueError("Voice identity sample is too quiet.")
    signal /= peak

    frame_size = max(256, int(sample_rate * 0.032))
    hop = max(128, frame_size // 2)
    frames = []
    window = np.hanning(frame_size).astype(np.float32)
    for start in range(0, signal.size - frame_size + 1, hop):
        frame = signal[start:start + frame_size] * window
        spectrum = np.abs(np.fft.rfft(frame)) + 1e-8
        frames.append(np.log(spectrum))
    if not frames:
        raise ValueError("Voice identity sample is too short.")

    mean_spectrum = np.mean(np.stack(frames), axis=0)
    bands = np.array_split(mean_spectrum, 32)
    feature = np.array([float(np.mean(band)) for band in bands], dtype=np.float32)
    feature -= float(np.mean(feature))
    norm = float(np.linalg.norm(feature))
    if norm <= 1e-8:
        raise ValueError("Could not extract a voice identity feature.")
    return feature / norm


class LocalVoiceIdentity:
    """Best-effort local voice gate; not a replacement for approval or PIN."""

    def __init__(self, profile_path: str | Path, threshold: float = 0.88) -> None:
        self.profile_path = Path(profile_path).expanduser()
        self.threshold = max(0.5, min(float(threshold), 0.99))

    def is_enrolled(self) -> bool:
        return self.profile_path.is_file()

    def enroll(self, wav_paths: list[str | Path]) -> None:
        if len(wav_paths) < 3:
            raise ValueError("At least three voice samples are required for enrollment.")
        features = np.stack([_voice_features(path) for path in wav_paths])
        centroid = np.mean(features, axis=0)
        norm = float(np.linalg.norm(centroid))
        if norm <= 1e-8 or not math.isfinite(norm):
            raise ValueError("Could not create a stable voice profile.")
        centroid = centroid / norm

        self.profile_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {"version": 1, "feature": centroid.tolist()}
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.profile_path.parent,
            prefix=".voice-profile-",
            delete=False,
        ) as handle:
            json.dump(payload, handle)
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.profile_path)
        os.chmod(self.profile_path, 0o600)

    def verify(self, wav_path: str | Path) -> SpeakerVerification:
        if not self.is_enrolled():
            return SpeakerVerification(False, 0.0, "No owner voice profile is enrolled.")
        try:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
            enrolled = np.asarray(payload["feature"], dtype=np.float32)
            candidate = _voice_features(wav_path)
            if enrolled.shape != candidate.shape:
                raise ValueError("Voice profile format is incompatible.")
            score = float(np.dot(enrolled, candidate))
        except Exception as exc:
            return SpeakerVerification(False, 0.0, f"Voice verification failed: {exc}")
        accepted = score >= self.threshold
        message = "Owner voice accepted." if accepted else "Speaker does not match the owner profile."
        return SpeakerVerification(accepted, score, message)
