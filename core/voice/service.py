from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.voice.identity import LocalVoiceIdentity, SpeakerVerification
from core.voice.state import VoiceSessionState, VoiceStateMachine
from core.voice.stt import VoiceComponentStatus, WhisperCppTranscriber


@dataclass(frozen=True)
class VoicePipelineResult:
    accepted: bool
    transcript: str
    message: str
    speaker_score: float = 0.0


class LocalVoiceService:
    """Coordinates local STT and the owner-only convenience gate."""

    def __init__(
        self,
        transcriber: WhisperCppTranscriber,
        identity: LocalVoiceIdentity,
        command_handler: Callable[[str], None],
    ) -> None:
        self.transcriber = transcriber
        self.identity = identity
        self.command_handler = command_handler
        self.state = VoiceStateMachine()

    def status(self) -> VoiceComponentStatus:
        stt = self.transcriber.status()
        if not stt.ready:
            return stt
        if not self.identity.is_enrolled():
            return VoiceComponentStatus(False, "Owner voice enrollment is required.")
        return VoiceComponentStatus(True, "Private local voice command service is ready.")

    def process_recording(self, wav_path: str | Path) -> VoicePipelineResult:
        if not self.status().ready:
            return VoicePipelineResult(False, "", self.status().message)
        try:
            self.state.transition(VoiceSessionState.WAKE_DETECTED, "push-to-talk")
            self.state.transition(VoiceSessionState.VERIFYING_SPEAKER)
            verification: SpeakerVerification = self.identity.verify(wav_path)
            if not verification.accepted:
                self.state.transition(VoiceSessionState.IDLE, verification.message)
                return VoicePipelineResult(
                    False, "", verification.message, verification.score
                )
            self.state.transition(VoiceSessionState.LISTENING)
            transcript = self.transcriber.transcribe(wav_path)
            self.state.transition(VoiceSessionState.UNDERSTANDING)
            self.command_handler(transcript)
            self.state.transition(VoiceSessionState.RESPONDING)
            self.state.transition(VoiceSessionState.IDLE)
            return VoicePipelineResult(
                True, transcript, "Voice command accepted.", verification.score
            )
        except Exception as exc:
            if self.state.can_transition(VoiceSessionState.ERROR):
                self.state.transition(VoiceSessionState.ERROR, str(exc))
            if self.state.can_transition(VoiceSessionState.IDLE):
                self.state.transition(VoiceSessionState.IDLE)
            return VoicePipelineResult(False, "", str(exc))

    def verify_and_transcribe(self, wav_path: str | Path) -> VoicePipelineResult:
        """Inspect a wake-listener utterance without dispatching a command."""
        status = self.status()
        if not status.ready:
            return VoicePipelineResult(False, "", status.message)
        verification = self.identity.verify(wav_path)
        if not verification.accepted:
            return VoicePipelineResult(
                False, "", verification.message, verification.score
            )
        try:
            transcript = self.transcriber.transcribe(wav_path)
        except Exception as exc:
            return VoicePipelineResult(
                False,
                "",
                f"Local transcription failed: {exc}",
                verification.score,
            )
        return VoicePipelineResult(
            True,
            transcript,
            "Verified owner utterance transcribed locally.",
            verification.score,
        )
