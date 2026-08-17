"""Local voice runtime primitives for Misha."""

from core.voice.barge_in import BargeInMonitor, match_interrupt_phrase
from core.voice.events import VoiceEvent
from core.voice.identity import LocalVoiceIdentity, SpeakerVerification
from core.voice.realtime import (
    AudioChunk,
    AudioQueueStats,
    DropOldestAsyncQueue,
    RealtimeInterruptionCoordinator,
    RealtimeInterruptionResult,
    RealtimeVoiceSession,
)
from core.voice.service import LocalVoiceService, VoicePipelineResult
from core.voice.state import VoiceSessionState, VoiceStateMachine
from core.voice.stt import VoiceComponentStatus, WhisperCppTranscriber
from core.voice.tts import MacOSTextToSpeech, SpeechStatus, SpeechStopResult

__all__ = [
    "BargeInMonitor",
    "AudioChunk",
    "AudioQueueStats",
    "DropOldestAsyncQueue",
    "LocalVoiceIdentity",
    "LocalVoiceService",
    "MacOSTextToSpeech",
    "RealtimeVoiceSession",
    "RealtimeInterruptionCoordinator",
    "RealtimeInterruptionResult",
    "SpeakerVerification",
    "SpeechStatus",
    "SpeechStopResult",
    "VoiceComponentStatus",
    "VoicePipelineResult",
    "VoiceEvent",
    "VoiceSessionState",
    "VoiceStateMachine",
    "WhisperCppTranscriber",
    "match_interrupt_phrase",
]
