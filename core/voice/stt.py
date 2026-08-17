from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VoiceComponentStatus:
    ready: bool
    message: str


class WhisperCppTranscriber:
    """Offline speech-to-text adapter for the whisper.cpp CLI."""

    def __init__(
        self,
        executable: str | Path,
        model_path: str | Path,
        *,
        language: str = "tr",
        timeout_seconds: int = 120,
    ) -> None:
        self.executable = Path(executable).expanduser()
        self.model_path = Path(model_path).expanduser()
        self.language = language.strip() or "tr"
        self.timeout_seconds = max(5, int(timeout_seconds))

    def status(self) -> VoiceComponentStatus:
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            return VoiceComponentStatus(False, "whisper-cli is not installed.")
        if not self.model_path.is_file():
            return VoiceComponentStatus(False, "The local Whisper model is missing.")
        return VoiceComponentStatus(True, "Offline Whisper speech recognition is ready.")

    def transcribe(self, wav_path: str | Path) -> str:
        status = self.status()
        if not status.ready:
            raise RuntimeError(status.message)

        audio_path = Path(wav_path).expanduser().resolve()
        if not audio_path.is_file() or audio_path.suffix.lower() != ".wav":
            raise ValueError("Speech input must be an existing WAV file.")

        with tempfile.TemporaryDirectory(prefix="misha-stt-") as temp_dir:
            output_base = Path(temp_dir) / "transcript"
            command = [
                str(self.executable),
                "--model", str(self.model_path),
                "--file", str(audio_path),
                "--language", self.language,
                "--no-timestamps",
                "--output-txt",
                "--output-file", str(output_base),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()[-500:]
                raise RuntimeError(f"Offline transcription failed: {detail}")

            transcript_path = output_base.with_suffix(".txt")
            if not transcript_path.is_file():
                raise RuntimeError("whisper-cli did not create a transcript.")
            transcript = transcript_path.read_text(encoding="utf-8").strip()
            if not transcript:
                raise RuntimeError("No speech was detected in the recording.")
            return transcript
