from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def resample_mono(
    samples: np.ndarray,
    source_rate: int,
    target_rate: int,
) -> np.ndarray:
    """Deterministic mono float32 linear resampling without an optional DSP dependency."""
    source_rate = int(source_rate)
    target_rate = int(target_rate)
    if source_rate < 8000 or target_rate < 8000:
        raise ValueError("Audio sample rates must be at least 8000 Hz.")
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if values.size == 0 or source_rate == target_rate:
        return values.copy()
    target_size = max(1, round(values.size * target_rate / source_rate))
    source_positions = np.arange(values.size, dtype=np.float64)
    target_positions = np.linspace(0, values.size - 1, target_size, dtype=np.float64)
    return np.interp(target_positions, source_positions, values).astype(np.float32)


def apply_automatic_gain(
    samples: np.ndarray,
    *,
    target_rms: float = 0.10,
    maximum_gain: float = 4.0,
) -> np.ndarray:
    """Apply bounded recording-level AGC while preserving silence and preventing clipping."""
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not 0.02 <= float(target_rms) <= 0.25:
        raise ValueError("AGC target RMS must be between 0.02 and 0.25.")
    if not 1.0 <= float(maximum_gain) <= 8.0:
        raise ValueError("AGC maximum gain must be between 1 and 8.")
    if values.size == 0:
        return values.copy()
    rms = float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))
    peak = float(np.max(np.abs(values)))
    if rms < 1e-4 or peak >= 0.98:
        return values.copy()
    gain = min(float(maximum_gain), float(target_rms) / rms, 0.98 / max(peak, 1e-6))
    return np.clip(values * max(0.25, gain), -0.98, 0.98).astype(np.float32)


@dataclass(frozen=True)
class JitterBufferStats:
    received: int
    late_dropped: int
    missing_filled: int
    buffered: int
    underruns: int


class PCMJitterBuffer:
    """Small sequence-aware PCM buffer with bounded latency and silence concealment."""

    def __init__(self, frame_bytes: int, *, prefill_frames: int = 2, maximum_frames: int = 8):
        if frame_bytes < 2 or frame_bytes % 2:
            raise ValueError("PCM frame size must be a positive multiple of two bytes.")
        if not 1 <= prefill_frames <= maximum_frames <= 64:
            raise ValueError("Jitter buffer bounds are invalid.")
        self.frame_bytes = int(frame_bytes)
        self.prefill_frames = int(prefill_frames)
        self.maximum_frames = int(maximum_frames)
        self._packets: dict[int, bytes] = {}
        self._expected: int | None = None
        self._started = False
        self._received = 0
        self._late_dropped = 0
        self._missing_filled = 0
        self._underruns = 0

    def push(self, sequence: int, pcm: bytes) -> bool:
        sequence = int(sequence)
        if sequence < 0 or len(pcm) != self.frame_bytes:
            raise ValueError("Jitter packet sequence or PCM frame is invalid.")
        self._received += 1
        if self._expected is not None and sequence < self._expected:
            self._late_dropped += 1
            return False
        self._packets.setdefault(sequence, bytes(pcm))
        if len(self._packets) > self.maximum_frames:
            newest = max(self._packets)
            del self._packets[newest]
            if newest == sequence:
                self._late_dropped += 1
                return False
        return True

    def pop(self) -> bytes | None:
        if not self._started:
            if len(self._packets) < self.prefill_frames:
                return None
            self._started = True
            self._expected = min(self._packets)
        assert self._expected is not None
        frame = self._packets.pop(self._expected, None)
        self._expected += 1
        if frame is not None:
            return frame
        self._underruns += 1
        if self._packets:
            self._missing_filled += 1
        return bytes(self.frame_bytes)

    @property
    def stats(self) -> JitterBufferStats:
        return JitterBufferStats(
            received=self._received,
            late_dropped=self._late_dropped,
            missing_filled=self._missing_filled,
            buffered=len(self._packets),
            underruns=self._underruns,
        )
