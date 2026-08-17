import threading
import time
import unittest
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from core.voice.barge_in import BargeInMonitor, match_interrupt_phrase
from core.voice.service import VoicePipelineResult
from core.voice.tts import MacOSTextToSpeech


class _BlockingProcess:
    def __init__(self):
        self.finished = threading.Event()
        self.return_code = 0

    def wait(self, timeout=None):
        if not self.finished.wait(timeout=timeout if timeout is not None else 2):
            raise TimeoutError
        return self.return_code

    def poll(self):
        return None if not self.finished.is_set() else self.return_code

    def terminate(self):
        self.return_code = -15
        self.finished.set()

    def kill(self):
        self.return_code = -9
        self.finished.set()


class _Recorder:
    def __init__(self):
        self.detector = None

    def record_until_silence(self, destination: Path, *, detector, cancel_event):
        self.detector = detector
        destination.write_bytes(b"wav")


class _StubbornProcess:
    def __init__(self):
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        if not self.killed:
            raise subprocess.TimeoutExpired("say", timeout)
        return -9

    def kill(self):
        self.killed = True


class BargeInTests(unittest.TestCase):
    def test_only_exact_wake_prefixed_interrupts_match(self):
        for phrase in ("Misha dur", "Mişa, sus!", "Hey Misha stop"):
            with self.subTest(phrase=phrase):
                self.assertTrue(match_interrupt_phrase(phrase))
        for phrase in ("dur", "Misha devam et", "Bugün Misha dur dedi"):
            with self.subTest(phrase=phrase):
                self.assertFalse(match_interrupt_phrase(phrase))

    def test_monitor_requires_high_confidence_owner(self):
        service = Mock()
        service.verify_and_transcribe.return_value = VoicePipelineResult(
            True, "Misha dur", "ok", 0.90
        )
        interrupted = Mock()
        monitor = BargeInMonitor(_Recorder(), service, interrupted)
        self.assertFalse(monitor.listen_once())
        interrupted.assert_not_called()

    def test_verified_owner_interrupt_stops_playback_callback(self):
        service = Mock()
        service.verify_and_transcribe.return_value = VoicePipelineResult(
            True, "Misha dur", "ok", 0.99
        )
        interrupted = Mock()
        recorder = _Recorder()
        monitor = BargeInMonitor(recorder, service, interrupted)
        self.assertTrue(monitor.listen_once())
        interrupted.assert_called_once_with()
        self.assertEqual(
            recorder.detector.config.maximum_recording_seconds,
            2.0,
        )

    def test_barge_in_uses_shared_audio_capture_lock(self):
        service = Mock()
        service.verify_and_transcribe.return_value = VoicePipelineResult(
            False, "", "no interrupt", 0.0
        )
        lock = threading.Lock()
        recorder = Mock()

        def record(destination, *, detector, cancel_event):
            self.assertTrue(lock.locked())
            destination.write_bytes(b"wav")

        recorder.record_until_silence.side_effect = record
        monitor = BargeInMonitor(
            recorder, service, Mock(), capture_lock=lock
        )
        self.assertFalse(monitor.listen_once())

    def test_tts_stop_can_interrupt_waiting_speech_from_another_thread(self):
        process = _BlockingProcess()
        tts = MacOSTextToSpeech(voice="")
        with (
            patch.object(tts, "status", return_value=Mock(ready=True)),
            patch("core.voice.tts.subprocess.Popen", return_value=process),
        ):
            thread = threading.Thread(
                target=tts.speak,
                args=("hello",),
                kwargs={"wait": True},
            )
            thread.start()
            for _ in range(50):
                if tts.is_speaking():
                    break
                time.sleep(0.01)
            self.assertTrue(tts.is_speaking())
            tts.stop()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(tts.is_speaking())

    def test_tts_stop_reports_measured_latency(self):
        process = _BlockingProcess()
        tts = MacOSTextToSpeech(voice="")
        tts._process = process
        result = tts.stop()
        self.assertTrue(result.stopped)
        self.assertGreaterEqual(result.latency_ms, 0.0)
        self.assertFalse(result.forced)

    def test_tts_stop_force_kills_stuck_playback(self):
        process = _StubbornProcess()
        tts = MacOSTextToSpeech(voice="")
        tts._process = process
        result = tts.stop(timeout=0.01)
        self.assertTrue(result.stopped)
        self.assertTrue(result.forced)
        self.assertTrue(process.killed)


if __name__ == "__main__":
    unittest.main()
