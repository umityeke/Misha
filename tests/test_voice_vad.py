import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core.voice.recorder import (
    MicrophoneAccessError,
    RecordingCancelled,
    SoundDeviceRecorder,
    microphone_error_message,
)
from core.voice.vad import (
    EnergyVoiceActivityDetector,
    VADConfig,
    VADState,
    vad_config_for_sensitivity,
)


def _config(**overrides):
    values = {
        "sample_rate": 8000,
        "frame_ms": 20,
        "activation_rms": 0.02,
        "speech_start_ms": 40,
        "speech_end_silence_ms": 60,
        "minimum_speech_ms": 80,
        "maximum_recording_seconds": 2.0,
        "pre_roll_ms": 40,
        "noise_calibration_ms": 0,
    }
    values.update(overrides)
    return VADConfig(**values)


class _Manager:
    def resolve_input(self, *_args):
        return SimpleNamespace(index=5, name="Test microphone")


class _Stream:
    def __init__(self, frames):
        self.frames = list(frames)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _count):
        return self.frames.pop(0).reshape(-1, 1), False


class VoiceActivityDetectorTests(unittest.TestCase):
    def test_detects_speech_start_and_trailing_silence(self):
        detector = EnergyVoiceActivityDetector(_config())
        loud = np.full(detector.frame_samples, 0.2, dtype=np.float32)
        quiet = np.zeros(detector.frame_samples, dtype=np.float32)
        self.assertFalse(detector.process(loud).speech_started)
        self.assertTrue(detector.process(loud).speech_started)
        detector.process(loud)
        detector.process(loud)
        detector.process(quiet)
        detector.process(quiet)
        decision = detector.process(quiet)
        self.assertTrue(decision.speech_ended)
        self.assertEqual(decision.state, VADState.COMPLETE)

    def test_short_noise_does_not_trigger_speech(self):
        detector = EnergyVoiceActivityDetector(_config())
        loud = np.full(detector.frame_samples, 0.2, dtype=np.float32)
        quiet = np.zeros(detector.frame_samples, dtype=np.float32)
        detector.process(loud)
        decision = detector.process(quiet)
        self.assertEqual(decision.state, VADState.WAITING)

    def test_silence_reaches_bounded_timeout(self):
        detector = EnergyVoiceActivityDetector(
            _config(maximum_recording_seconds=0.1)
        )
        quiet = np.zeros(detector.frame_samples, dtype=np.float32)
        for _ in range(5):
            decision = detector.process(quiet)
        self.assertEqual(decision.state, VADState.TIMEOUT)

    def test_recorder_writes_vad_bounded_audio(self):
        detector = EnergyVoiceActivityDetector(_config())
        loud = np.full(detector.frame_samples, 0.2, dtype=np.float32)
        quiet = np.zeros(detector.frame_samples, dtype=np.float32)
        stream = _Stream([quiet, loud, loud, loud, loud, quiet, quiet, quiet])
        recorder = SoundDeviceRecorder(
            sample_rate=8000,
            device_manager=_Manager(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vad.wav"
            with patch("sounddevice.InputStream", return_value=stream) as input_stream:
                recorder.record_until_silence(path, detector=detector)
            self.assertEqual(input_stream.call_args.kwargs["device"], 5)
            with wave.open(str(path), "rb") as audio:
                self.assertGreater(audio.getnframes(), 0)
                self.assertEqual(audio.getframerate(), 8000)

    def test_recorder_cancellation_fails_closed(self):
        detector = EnergyVoiceActivityDetector(_config())
        quiet = np.zeros(detector.frame_samples, dtype=np.float32)
        recorder = SoundDeviceRecorder(
            sample_rate=8000,
            device_manager=_Manager(),
        )
        cancelled = threading.Event()
        cancelled.set()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("sounddevice.InputStream", return_value=_Stream([quiet])):
                with self.assertRaises(RecordingCancelled):
                    recorder.record_until_silence(
                        Path(temp_dir) / "cancelled.wav",
                        detector=detector,
                        cancel_event=cancelled,
                    )

    def test_busy_microphone_has_actionable_error(self):
        recorder = SoundDeviceRecorder(
            sample_rate=8000,
            device_manager=_Manager(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("sounddevice.InputStream", side_effect=RuntimeError("device busy")):
                with self.assertRaisesRegex(MicrophoneAccessError, "busy or unavailable"):
                    recorder.record_until_silence(
                        Path(temp_dir) / "busy.wav",
                        detector=EnergyVoiceActivityDetector(_config()),
                    )

    def test_permission_error_points_to_system_settings(self):
        message = microphone_error_message(RuntimeError("not permitted"))
        self.assertIn("Privacy & Security", message)

    def test_noise_calibration_raises_activation_threshold(self):
        detector = EnergyVoiceActivityDetector(
            _config(noise_calibration_ms=40, noise_multiplier=3.0)
        )
        noise = np.full(detector.frame_samples, 0.03, dtype=np.float32)
        detector.process(noise)
        decision = detector.process(noise)
        self.assertAlmostEqual(detector.noise_floor, 0.03, places=3)
        self.assertAlmostEqual(decision.threshold, 0.09, places=3)
        self.assertEqual(decision.state, VADState.WAITING)

    def test_sensitivity_profiles_are_ordered(self):
        high = vad_config_for_sensitivity("high")
        normal = vad_config_for_sensitivity("normal")
        low = vad_config_for_sensitivity("low")
        self.assertLess(high.activation_rms, normal.activation_rms)
        self.assertLess(normal.activation_rms, low.activation_rms)

    def test_low_microphone_level_has_actionable_error(self):
        detector = EnergyVoiceActivityDetector(
            _config(maximum_recording_seconds=0.04)
        )
        quiet = np.zeros(detector.frame_samples, dtype=np.float32)
        recorder = SoundDeviceRecorder(sample_rate=8000, device_manager=_Manager())
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("sounddevice.InputStream", return_value=_Stream([quiet, quiet])):
                with self.assertRaisesRegex(RuntimeError, "input level is too low"):
                    recorder.record_until_silence(
                        Path(temp_dir) / "quiet.wav",
                        detector=detector,
                    )

    def test_clipping_warning_is_emitted_once(self):
        detector = EnergyVoiceActivityDetector(_config())
        clipped = np.ones(detector.frame_samples, dtype=np.float32)
        quiet = np.zeros(detector.frame_samples, dtype=np.float32)
        warnings = []
        recorder = SoundDeviceRecorder(
            sample_rate=8000,
            device_manager=_Manager(),
            quality_warning=warnings.append,
        )
        frames = [clipped, clipped, clipped, clipped, quiet, quiet, quiet]
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("sounddevice.InputStream", return_value=_Stream(frames)):
                recorder.record_until_silence(
                    Path(temp_dir) / "clipped.wav",
                    detector=detector,
                )
        self.assertEqual(len(warnings), 1)
        self.assertIn("clipping", warnings[0])


if __name__ == "__main__":
    unittest.main()
