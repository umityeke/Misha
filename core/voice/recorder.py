from __future__ import annotations

import threading
import wave
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

from core.voice.devices import AudioDeviceManager
from core.voice.audio_processing import apply_automatic_gain
from core.voice.vad import EnergyVoiceActivityDetector, VADConfig, VADState


class RecordingCancelled(RuntimeError):
    pass


class MicrophoneAccessError(RuntimeError):
    """A user-facing local microphone access or device failure."""


def microphone_error_message(error: Exception) -> str:
    detail = str(error).strip()
    normalized = detail.casefold()
    if any(term in normalized for term in ("permission", "not permitted", "not authorized")):
        return "Microphone permission is denied. Enable Misha in System Settings > Privacy & Security > Microphone."
    if any(term in normalized for term in ("busy", "in use", "unavailable")):
        return "The microphone is busy or unavailable. Close other audio apps and try again."
    if any(term in normalized for term in ("invalid device", "device unavailable", "no default input")):
        return "The selected microphone is no longer available. Reconnect it or select another input device."
    if "overflow" in normalized:
        return "The microphone could not be read fast enough. Close heavy apps and try again."
    return f"The microphone could not be opened: {detail or type(error).__name__}"


def write_pcm16_wav(
    path: str | Path,
    samples: np.ndarray,
    *,
    sample_rate: int = 16000,
) -> Path:
    destination = Path(path).expanduser().resolve()
    if sample_rate < 8000:
        raise ValueError("Sample rate must be at least 8000 Hz.")
    values = np.asarray(samples)
    if values.ndim == 2 and values.shape[1] == 1:
        values = values[:, 0]
    if values.ndim != 1:
        raise ValueError("Audio samples must be mono.")
    if np.issubdtype(values.dtype, np.floating):
        values = np.clip(values, -1.0, 1.0)
        values = (values * 32767.0).astype("<i2")
    else:
        values = np.clip(values, -32768, 32767).astype("<i2")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(values.tobytes())
    return destination


class SoundDeviceRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        *,
        device_manager: AudioDeviceManager | None = None,
        preferred_input_index: int | None = None,
        preferred_input_name: str | None = None,
        vad_config: VADConfig | None = None,
        quality_warning: Callable[[str], None] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.device_manager = device_manager
        self.preferred_input_index = preferred_input_index
        self.preferred_input_name = preferred_input_name
        self.vad_config = vad_config
        self.quality_warning = quality_warning

    def record(self, destination: str | Path, seconds: float = 5.0) -> Path:
        duration = max(1.0, min(float(seconds), 30.0))
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("The local microphone dependency is not installed.") from exc
        manager = self.device_manager or AudioDeviceManager(sd, self.sample_rate)
        selected = manager.resolve_input(
            self.preferred_input_index,
            self.preferred_input_name,
        )
        frames = int(self.sample_rate * duration)
        try:
            recording = sd.rec(
                frames,
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=selected.index,
            )
            sd.wait()
        except Exception as exc:
            raise MicrophoneAccessError(microphone_error_message(exc)) from exc
        normalized = apply_automatic_gain(np.asarray(recording).reshape(-1))
        return write_pcm16_wav(destination, normalized, sample_rate=self.sample_rate)

    def record_until_silence(
        self,
        destination: str | Path,
        *,
        detector: EnergyVoiceActivityDetector | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("The local microphone dependency is not installed.") from exc
        manager = self.device_manager or AudioDeviceManager(sd, self.sample_rate)
        selected = manager.resolve_input(
            self.preferred_input_index,
            self.preferred_input_name,
        )
        vad = detector or EnergyVoiceActivityDetector(self.vad_config)
        if vad.config.sample_rate != self.sample_rate:
            raise ValueError("Recorder and VAD sample rates must match.")

        pre_roll: deque[np.ndarray] = deque(maxlen=vad.pre_roll_frames)
        captured: list[np.ndarray] = []
        speech_started = False
        clipping_reported = False
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=vad.frame_samples,
                device=selected.index,
            ) as stream:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise RecordingCancelled("Voice recording was cancelled.")
                    frame, _overflowed = stream.read(vad.frame_samples)
                    mono = np.asarray(frame, dtype=np.float32).reshape(-1)
                    if not speech_started:
                        pre_roll.append(mono.copy())
                    decision = vad.process(mono)
                    if decision.clipped and not clipping_reported:
                        clipping_reported = True
                        if self.quality_warning:
                            try:
                                self.quality_warning(
                                    "SYS: Microphone audio is clipping. Move farther from the microphone or lower its input level."
                                )
                            except Exception:
                                pass
                    if decision.speech_started:
                        speech_started = True
                        captured.extend(pre_roll)
                    elif speech_started:
                        captured.append(mono.copy())
                    if decision.state == VADState.COMPLETE:
                        break
                    if decision.state == VADState.TIMEOUT:
                        if not speech_started:
                            if decision.low_input:
                                raise RuntimeError(
                                    "Microphone input level is too low. Move closer or increase the input level in System Settings > Sound."
                                )
                            raise RuntimeError("No speech was detected before the timeout.")
                        break
        except RecordingCancelled:
            raise
        except RuntimeError as exc:
            if str(exc).startswith("No speech was detected"):
                raise
            raise MicrophoneAccessError(microphone_error_message(exc)) from exc
        except Exception as exc:
            raise MicrophoneAccessError(microphone_error_message(exc)) from exc

        if not captured:
            raise RuntimeError("No speech audio was captured.")
        normalized = apply_automatic_gain(np.concatenate(captured))
        return write_pcm16_wav(
            destination,
            normalized,
            sample_rate=self.sample_rate,
        )
