from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SetupCheck:
    key: str
    label: str
    ready: bool
    message: str
    required: bool = True


def collect_setup_checks(
    *,
    getter=None,
    provider=None,
    device_manager=None,
    tts=None,
) -> tuple[SetupCheck, ...]:
    if getter is None:
        from memory.config_manager import get_config

        getter = get_config
    raw_getter = getter

    def safe_get(key: str):
        try:
            return raw_getter(key)
        except Exception:
            return None

    getter = safe_get
    provider_error = None
    if provider is None:
        try:
            from core.ai.runtime import get_provider

            provider = get_provider()
        except Exception as exc:
            provider_error = type(exc).__name__
    if device_manager is None:
        try:
            from core.voice.devices import AudioDeviceManager

            device_manager = AudioDeviceManager(sample_rate=16000)
        except Exception:
            device_manager = None
    if tts is None:
        try:
            from core.voice.tts import MacOSTextToSpeech

            tts = MacOSTextToSpeech(voice="")
        except Exception:
            tts = None

    checks = []
    try:
        if provider is None:
            raise RuntimeError(provider_error or "provider_unavailable")
        ready, message = provider.healthcheck()
        checks.append(SetupCheck("local_ai", "Local intelligence", bool(ready), str(message)[:240]))
    except Exception as exc:
        checks.append(SetupCheck("local_ai", "Local intelligence", False, f"Check failed: {type(exc).__name__}"))

    from core.voice.stt import WhisperCppTranscriber

    whisper_cli = getter("whisper_cli_path") or "/opt/homebrew/bin/whisper-cli"
    whisper_model = getter("whisper_model_path") or str(
        Path.home() / ".misha/models/ggml-large-v3-turbo-q5_0.bin"
    )
    stt = WhisperCppTranscriber(whisper_cli, whisper_model).status()
    checks.append(SetupCheck("speech_recognition", "Offline speech recognition", stt.ready, stt.message))

    voice_profile = Path.home() / ".misha" / "voice" / "owner.json"
    enrolled = voice_profile.is_file()
    private = enrolled and (not hasattr(os, "stat") or voice_profile.stat().st_mode & 0o077 == 0)
    checks.append(SetupCheck(
        "owner_voice", "Owner voice profile", bool(enrolled and private),
        "Owner voice is enrolled and private."
        if enrolled and private else "Owner voice enrollment is missing or not private.",
    ))

    microphone_ready = False
    try:
        if device_manager is None:
            raise RuntimeError("device_manager_unavailable")
        microphone = device_manager.resolve_input(
            _safe_int(getter("audio_input_device_id")),
            getter("audio_input_device_name"),
        )
        microphone_ready = True
        microphone_message = f"Ready: {microphone.name}"
    except Exception as exc:
        microphone_message = f"Microphone unavailable: {type(exc).__name__}"
    checks.append(SetupCheck("microphone", "Microphone", microphone_ready, microphone_message))

    speaker_ready = False
    try:
        if device_manager is None or tts is None:
            raise RuntimeError("speaker_dependencies_unavailable")
        speaker = device_manager.resolve_output(
            _safe_int(getter("audio_output_device_id")),
            getter("audio_output_device_name"),
        )
        speech_status = tts.status()
        speaker_ready = bool(speech_status.ready)
        speaker_message = (
            f"Ready: {speaker.name}" if speaker_ready else speech_status.message
        )
    except Exception as exc:
        speaker_message = f"Speaker unavailable: {type(exc).__name__}"
    checks.append(SetupCheck("speaker", "Speaker and local TTS", speaker_ready, speaker_message))

    wake_ready = bool(stt.ready and enrolled and private and microphone_ready)
    checks.append(SetupCheck(
        "wake_word", "Wake-word pipeline", wake_ready,
        'Ready for “Misha” owner-verified wake commands.'
        if wake_ready else "Requires microphone, Whisper and owner voice profile.",
    ))
    return tuple(checks)


def _safe_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def setup_is_ready(checks: tuple[SetupCheck, ...]) -> bool:
    return bool(checks) and all(check.ready for check in checks if check.required)
