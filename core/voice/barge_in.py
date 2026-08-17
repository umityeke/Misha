from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Callable

from core.voice.recorder import RecordingCancelled, SoundDeviceRecorder
from core.voice.service import LocalVoiceService
from core.voice.vad import EnergyVoiceActivityDetector, VADConfig
from core.voice.wake import match_wake_word


_INTERRUPT_COMMANDS = {
    "dur",
    "sus",
    "stop",
    "konusmayi kes",
    "konuşmayı kes",
    "yeter",
}


def match_interrupt_phrase(transcript: str) -> bool:
    wake = match_wake_word(transcript)
    if not wake.detected:
        return False
    command = " ".join(wake.command.casefold().strip(" .,!?:;—-").split())
    return command in _INTERRUPT_COMMANDS


class BargeInMonitor:
    """Listens only during TTS and accepts exact, owner-verified stop phrases."""

    def __init__(
        self,
        recorder: SoundDeviceRecorder,
        voice_service: LocalVoiceService,
        on_interrupt: Callable[[], None],
        *,
        minimum_owner_score: float = 0.94,
        capture_lock: threading.Lock | threading.RLock | None = None,
    ) -> None:
        self.recorder = recorder
        self.voice_service = voice_service
        self.on_interrupt = on_interrupt
        self.minimum_owner_score = max(0.0, min(float(minimum_owner_score), 1.0))
        self.capture_lock = capture_lock
        self.vad_config = VADConfig(
            speech_start_ms=60,
            speech_end_silence_ms=250,
            minimum_speech_ms=150,
            maximum_recording_seconds=2.0,
            pre_roll_ms=150,
            noise_calibration_ms=150,
        )
        self.stop_event = threading.Event()
        self.interrupted = threading.Event()
        self._thread: threading.Thread | None = None

    def listen_once(self) -> bool:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="misha-barge-", suffix=".wav", delete=False
            ) as handle:
                temp_path = Path(handle.name)
            if self.capture_lock is None:
                self.recorder.record_until_silence(
                    temp_path,
                    detector=EnergyVoiceActivityDetector(self.vad_config),
                    cancel_event=self.stop_event,
                )
                result = self.voice_service.verify_and_transcribe(temp_path)
            else:
                with self.capture_lock:
                    self.recorder.record_until_silence(
                        temp_path,
                        detector=EnergyVoiceActivityDetector(self.vad_config),
                        cancel_event=self.stop_event,
                    )
                    result = self.voice_service.verify_and_transcribe(temp_path)
            accepted = (
                result.accepted
                and result.speaker_score >= self.minimum_owner_score
                and match_interrupt_phrase(result.transcript)
            )
            if accepted:
                self.interrupted.set()
                self.on_interrupt()
            return accepted
        except RecordingCancelled:
            return False
        except Exception:
            return False
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _run(self) -> None:
        while not self.stop_event.is_set() and not self.interrupted.is_set():
            self.listen_once()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()
        self.interrupted.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="misha-barge-in-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self.stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
