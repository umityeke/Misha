from __future__ import annotations

import platform
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeechStatus:
    ready: bool
    message: str


@dataclass(frozen=True)
class SpeechStopResult:
    stopped: bool
    latency_ms: float
    forced: bool = False


class MacOSTextToSpeech:
    """Private text-to-speech through macOS' local `say` executable."""

    def __init__(self, voice: str = "Yelda", rate: int = 190) -> None:
        self.voice = voice.strip()
        self.rate = max(80, min(int(rate), 360))
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()

    def status(self) -> SpeechStatus:
        executable = Path("/usr/bin/say")
        if platform.system() != "Darwin" or not executable.is_file():
            return SpeechStatus(False, "Local macOS speech is unavailable.")
        return SpeechStatus(True, "Local macOS speech is ready.")

    def speak(self, text: str, *, wait: bool = False) -> None:
        message = text.strip()
        if not message:
            return
        status = self.status()
        if not status.ready:
            raise RuntimeError(status.message)
        with self._lock:
            self.stop()
            command = ["/usr/bin/say", "-r", str(self.rate)]
            if self.voice:
                command.extend(["-v", self.voice])
            command.append(message)
            process = subprocess.Popen(command, text=True)
            self._process = process
        if wait:
            self._wait_for_process(process)

    def _wait_for_process(self, process: subprocess.Popen[str]) -> None:
        return_code = process.wait()
        with self._lock:
            interrupted = self._process is not process
            if self._process is process:
                self._process = None
        if return_code != 0 and not interrupted:
            raise RuntimeError("Local speech playback failed.")

    def wait(self) -> None:
        with self._lock:
            process = self._process
        if process is not None:
            self._wait_for_process(process)

    def stop(self, timeout: float = 0.2) -> SpeechStopResult:
        started_at = time.monotonic()
        with self._lock:
            process = self._process
            self._process = None
        if process is None or process.poll() is not None:
            return SpeechStopResult(False, (time.monotonic() - started_at) * 1000.0)

        forced = False
        process.terminate()
        try:
            process.wait(timeout=max(0.01, float(timeout)))
        except subprocess.TimeoutExpired:
            forced = True
            process.kill()
            process.wait(timeout=max(0.01, float(timeout)))
        return SpeechStopResult(
            True,
            (time.monotonic() - started_at) * 1000.0,
            forced,
        )

    def is_speaking(self) -> bool:
        with self._lock:
            return bool(self._process and self._process.poll() is None)
