from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class VADState(str, Enum):
    WAITING = "waiting"
    SPEAKING = "speaking"
    COMPLETE = "complete"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class VADConfig:
    sample_rate: int = 16000
    frame_ms: int = 30
    activation_rms: float = 0.012
    speech_start_ms: int = 90
    speech_end_silence_ms: int = 750
    minimum_speech_ms: int = 300
    maximum_recording_seconds: float = 15.0
    pre_roll_ms: int = 300
    noise_calibration_ms: int = 300
    noise_multiplier: float = 3.0
    low_input_rms: float = 0.002
    clipping_peak: float = 0.98
    clipping_ratio: float = 0.01

    def __post_init__(self) -> None:
        if self.sample_rate < 8000:
            raise ValueError("VAD sample rate must be at least 8000 Hz.")
        if self.frame_ms < 10 or self.frame_ms > 100:
            raise ValueError("VAD frame size must be between 10 and 100 ms.")
        if self.activation_rms <= 0 or self.activation_rms >= 1:
            raise ValueError("VAD activation RMS must be between zero and one.")
        if self.maximum_recording_seconds <= 0:
            raise ValueError("VAD maximum recording time must be positive.")
        if self.noise_calibration_ms < 0 or self.noise_calibration_ms > 2000:
            raise ValueError("VAD noise calibration must be between 0 and 2000 ms.")
        if self.noise_multiplier < 1 or self.noise_multiplier > 10:
            raise ValueError("VAD noise multiplier must be between 1 and 10.")
        if not 0 < self.low_input_rms < self.activation_rms:
            raise ValueError("VAD low-input RMS must be below activation RMS.")
        if not 0.5 <= self.clipping_peak <= 1:
            raise ValueError("VAD clipping peak must be between 0.5 and 1.")
        if not 0 < self.clipping_ratio <= 1:
            raise ValueError("VAD clipping ratio must be between zero and one.")


@dataclass(frozen=True)
class VADDecision:
    state: VADState
    rms: float
    speech_started: bool = False
    speech_ended: bool = False
    threshold: float = 0.0
    clipped: bool = False
    low_input: bool = False


_SENSITIVITY_PROFILES = {
    "low": {"activation_rms": 0.020, "noise_multiplier": 4.5},
    "normal": {"activation_rms": 0.012, "noise_multiplier": 3.0},
    "high": {"activation_rms": 0.006, "noise_multiplier": 2.0},
}


def normalize_vad_sensitivity(value: str | None) -> str:
    normalized = (value or "normal").strip().lower()
    return normalized if normalized in _SENSITIVITY_PROFILES else "normal"


def vad_config_for_sensitivity(
    value: str | None,
    *,
    sample_rate: int = 16000,
) -> VADConfig:
    sensitivity = normalize_vad_sensitivity(value)
    return VADConfig(sample_rate=sample_rate, **_SENSITIVITY_PROFILES[sensitivity])


class EnergyVoiceActivityDetector:
    """Small offline VAD with bounded recording and deterministic behavior."""

    def __init__(self, config: VADConfig | None = None) -> None:
        self.config = config or VADConfig()
        self.state = VADState.WAITING
        self.total_samples = 0
        self.speech_samples = 0
        self._active_samples = 0
        self._silent_samples = 0
        self._calibration_levels: list[float] = []
        self.noise_floor = 0.0
        self.activation_threshold = self.config.activation_rms
        self.max_observed_rms = 0.0

    @property
    def frame_samples(self) -> int:
        return max(1, int(self.config.sample_rate * self.config.frame_ms / 1000))

    @property
    def pre_roll_frames(self) -> int:
        return max(1, int(self.config.pre_roll_ms / self.config.frame_ms))

    @staticmethod
    def rms(samples: np.ndarray) -> float:
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        if values.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(values), dtype=np.float64)))

    def process(self, samples: np.ndarray) -> VADDecision:
        if self.state in {VADState.COMPLETE, VADState.TIMEOUT}:
            return VADDecision(
                self.state,
                self.rms(samples),
                threshold=self.activation_threshold,
            )
        values = np.asarray(samples, dtype=np.float32).reshape(-1)
        level = self.rms(values)
        count = int(values.size)
        self.total_samples += count
        self.max_observed_rms = max(self.max_observed_rms, level)
        clipped = bool(
            values.size
            and np.mean(np.abs(values) >= self.config.clipping_peak)
            >= self.config.clipping_ratio
        )

        calibration_samples = int(
            self.config.sample_rate * self.config.noise_calibration_ms / 1000
        )
        if calibration_samples and self.total_samples <= calibration_samples:
            self._calibration_levels.append(level)
            if self.total_samples >= calibration_samples:
                self.noise_floor = float(np.percentile(self._calibration_levels, 80))
                self.activation_threshold = min(
                    0.25,
                    max(
                        self.config.activation_rms,
                        self.noise_floor * self.config.noise_multiplier,
                    ),
                )
            return VADDecision(
                self.state,
                level,
                threshold=self.activation_threshold,
                clipped=clipped,
            )

        active = level >= self.activation_threshold
        started = False
        ended = False

        if self.state == VADState.WAITING:
            self._active_samples = self._active_samples + count if active else 0
            required = int(
                self.config.sample_rate * self.config.speech_start_ms / 1000
            )
            if self._active_samples >= required:
                self.state = VADState.SPEAKING
                self.speech_samples = self._active_samples
                started = True
        else:
            self.speech_samples += count
            self._silent_samples = 0 if active else self._silent_samples + count
            minimum = int(
                self.config.sample_rate * self.config.minimum_speech_ms / 1000
            )
            ending_silence = int(
                self.config.sample_rate
                * self.config.speech_end_silence_ms
                / 1000
            )
            if self.speech_samples >= minimum and self._silent_samples >= ending_silence:
                self.state = VADState.COMPLETE
                ended = True

        maximum = int(
            self.config.sample_rate * self.config.maximum_recording_seconds
        )
        if self.total_samples >= maximum and self.state != VADState.COMPLETE:
            self.state = VADState.TIMEOUT
        low_input = (
            self.state == VADState.TIMEOUT
            and self.speech_samples == 0
            and self.max_observed_rms < self.config.low_input_rms
        )
        return VADDecision(
            self.state,
            level,
            started,
            ended,
            self.activation_threshold,
            clipped,
            low_input,
        )
