import threading
import unittest
from collections import deque
from unittest.mock import Mock, patch

import numpy as np

from agent.runtime_result import ExecutionResult, ResultStatus
from main import MishaLocal


class VoiceLifecycleTests(unittest.TestCase):
    def _controller(self):
        controller = object.__new__(MishaLocal)
        controller._wake_listener_stop = threading.Event()
        controller._voice_busy = threading.Event()
        controller._audio_capture_lock = threading.Lock()
        controller._follow_up_requested = threading.Event()
        controller._shutdown_lock = threading.Lock()
        controller._stopped = False
        controller._active_barge_monitor = None
        controller._wake_listener_thread = Mock()
        controller._wake_listener_thread.is_alive.return_value = True
        controller.tts = Mock()
        controller.voice_recorder = Mock()
        controller.proactive_service = None
        controller.ui = Mock()
        return controller

    def test_shutdown_cancels_listener_stops_tts_and_joins(self):
        controller = self._controller()
        controller.shutdown(timeout=0.25)
        self.assertTrue(controller._wake_listener_stop.is_set())
        controller.tts.stop.assert_called_once_with()
        controller._wake_listener_thread.join.assert_called_once_with(timeout=0.25)

    def test_shutdown_is_idempotent(self):
        controller = self._controller()
        controller.shutdown()
        controller.shutdown()
        controller.tts.stop.assert_called_once_with()

    def test_shutdown_also_stops_proactive_observation(self):
        controller = self._controller()
        controller.proactive_service = Mock()
        controller.shutdown(timeout=0.25)
        controller.proactive_service.stop.assert_called_once_with(timeout=0.25)

    def test_proactive_observation_requires_controller_opt_in(self):
        controller = self._controller()
        service = Mock()
        service.start.return_value = True
        with (
            patch("core.proactive.ProactiveAI", return_value=service) as proactive_cls,
            patch(
                "memory.config_manager.get_proactive_denylist",
                return_value=("bank.example",),
            ),
            patch(
                "memory.config_manager.get_proactive_settings",
                return_value=Mock(name="settings"),
            ) as get_settings,
            patch("memory.config_manager.set_config") as set_config,
        ):
            controller._set_proactive_enabled(True)
        proactive_cls.assert_called_once_with(
            speak_callback=controller._proactive_notification,
            denylist=("bank.example",),
            settings=get_settings.return_value,
        )
        service.start.assert_called_once_with(consent=True)
        set_config.assert_called_once_with("proactive_enabled", "1")
        controller.ui.set_proactive_enabled.assert_called_once_with(True)

    def test_proactive_observation_can_be_stopped_from_ui(self):
        controller = self._controller()
        controller.proactive_service = Mock()
        with patch("memory.config_manager.set_config") as set_config:
            controller._set_proactive_enabled(False)
        controller.proactive_service.stop.assert_called_once_with()
        set_config.assert_called_once_with("proactive_enabled", "0")
        controller.ui.set_proactive_enabled.assert_called_once_with(False)

    def test_proactive_settings_update_live_service(self):
        controller = self._controller()
        controller.proactive_service = Mock()
        requested = Mock(name="requested_settings")
        validated = Mock(name="validated_settings")
        with (
            patch(
                "memory.config_manager.save_proactive_settings",
                return_value=validated,
            ) as save_settings,
            patch(
                "memory.config_manager.save_proactive_denylist",
                return_value=("bank.example",),
            ) as save_denylist,
        ):
            controller._set_proactive_settings(requested, ["bank.example"])
        save_settings.assert_called_once_with(requested)
        save_denylist.assert_called_once_with(["bank.example"])
        controller.proactive_service.update_settings.assert_called_once_with(
            validated, denylist=("bank.example",)
        )

    def test_local_speaker_check_starts_tts_when_idle(self):
        controller = self._controller()
        controller.tts.status.return_value = Mock(ready=True, message="ready")
        ok, message = controller._test_speaker()
        self.assertTrue(ok)
        self.assertIn("started", message)
        controller.tts.speak.assert_called_once_with(
            "Misha ses testi başarılı. Yerel hoparlör bağlantısı hazır.",
            wait=False,
        )

    def test_speaker_check_never_interrupts_active_work(self):
        controller = self._controller()
        controller._voice_busy.set()
        ok, message = controller._test_speaker()
        self.assertFalse(ok)
        self.assertIn("busy", message)
        controller.tts.speak.assert_not_called()

    def test_audio_device_selection_is_validated_persisted_and_applied(self):
        controller = self._controller()
        manager = Mock()
        microphone = Mock(index=4)
        microphone.name = "Studio Mic"
        speaker = Mock(index=7)
        speaker.name = "Studio Output"
        manager.resolve_input.return_value = microphone
        manager.resolve_output.return_value = speaker
        with (
            patch("core.voice.devices.AudioDeviceManager", return_value=manager),
            patch("memory.config_manager.set_config") as set_config,
        ):
            ok, message = controller._select_audio_devices(4, 7)
        self.assertTrue(ok)
        self.assertIn("Studio Mic", message)
        self.assertEqual(set_config.call_count, 4)
        self.assertEqual(controller.voice_recorder.preferred_input_index, 4)

    def test_microphone_level_test_records_temporary_audio(self):
        from core.voice.recorder import write_pcm16_wav

        controller = self._controller()

        def record(path, seconds):
            signal = np.sin(np.linspace(0, 100, 32_000)) * 0.15
            write_pcm16_wav(path, signal)

        controller.voice_recorder.record.side_effect = record
        ok, message = controller._test_microphone_level()
        self.assertTrue(ok)
        self.assertIn("RMS=", message)
        self.assertFalse(controller._voice_busy.is_set())

    def test_wake_test_verifies_without_dispatching_command(self):
        controller = self._controller()
        controller.voice_service = Mock()
        controller.voice_service.verify_and_transcribe.return_value = Mock(
            accepted=True, transcript="Misha", speaker_score=0.97
        )
        ok, message = controller._test_wake_word()
        self.assertTrue(ok)
        self.assertIn("detected", message)
        controller.voice_service.verify_and_transcribe.assert_called_once()
        self.assertFalse(controller._voice_busy.is_set())

    def test_hands_free_choice_is_persisted(self):
        controller = self._controller()
        with patch("memory.config_manager.set_config") as set_config:
            controller._set_hands_free_enabled(False)
        set_config.assert_called_once_with("hands_free_enabled", "0")
        controller.ui.write_log.assert_called_once()

    def test_full_application_start_without_microphone_fails_soft(self):
        from core.voice.devices import AudioDeviceError

        controller = self._controller()
        controller.voice_recorder = None
        controller.voice_service = None
        provider = Mock()
        provider.healthcheck.return_value = (True, "local model ready")
        transcriber = Mock()
        transcriber.status.return_value = Mock(ready=True, message="ready")
        identity = Mock()
        identity.is_enrolled.return_value = True
        manager = Mock()
        manager.resolve_input.side_effect = AudioDeviceError(
            "No local input audio device is available."
        )
        values = {
            "proactive_enabled": "0",
            "whisper_cli_path": "/usr/bin/true",
            "whisper_model_path": "/tmp/model.bin",
        }
        with (
            patch("core.ai.runtime.get_provider", return_value=provider),
            patch("memory.config_manager.get_config", side_effect=lambda key: values.get(key)),
            patch("memory.config_manager.set_config"),
            patch("core.voice.stt.WhisperCppTranscriber", return_value=transcriber),
            patch("core.voice.identity.LocalVoiceIdentity", return_value=identity),
            patch("core.voice.devices.AudioDeviceManager", return_value=manager),
        ):
            controller.start()
        controller.ui.set_voice_available.assert_called_with(
            False, "No local input audio device is available."
        )
        self.assertIsNone(controller.voice_recorder)
        self.assertIsNone(controller.voice_service)

    def test_vad_sensitivity_is_normalized_and_applied(self):
        controller = self._controller()
        with patch("memory.config_manager.set_config") as set_config:
            controller._set_vad_sensitivity("HIGH")
        set_config.assert_called_once_with("vad_sensitivity", "high")
        self.assertEqual(controller.voice_recorder.vad_config.activation_rms, 0.006)

    def test_verified_barge_in_stops_tts(self):
        controller = self._controller()
        controller.tts.stop.return_value = Mock(latency_ms=42.0)
        controller._interrupt_speech()
        controller.tts.stop.assert_called_once_with()
        controller.ui.write_log.assert_called_once()
        self.assertTrue(controller._follow_up_requested.is_set())

    def test_barge_in_opens_one_bounded_follow_up_turn(self):
        controller = self._controller()
        controller._follow_up_requested.set()
        deadline = controller._consume_follow_up_request(100.0)
        self.assertEqual(deadline, 108.0)
        self.assertFalse(controller._follow_up_requested.is_set())
        self.assertEqual(controller._consume_follow_up_request(101.0), 0.0)
        controller.ui.set_state.assert_called_once_with("LISTENING")

    def test_text_response_starts_and_stops_barge_monitor(self):
        controller = self._controller()
        controller.executor = Mock()
        controller.executor.execute_result.return_value = ExecutionResult(
            ResultStatus.SUCCEEDED, "answer"
        )
        controller.voice_service = Mock()
        controller.history = deque(maxlen=12)
        controller.ui.muted = False
        controller.tts.status.return_value = Mock(ready=True)
        monitor = Mock()
        with patch("core.voice.barge_in.BargeInMonitor", return_value=monitor):
            controller._on_text_command("hello")
        monitor.start.assert_called_once_with()
        monitor.stop.assert_called_once_with()
        controller.tts.speak.assert_called_once_with("answer", wait=False)
        controller.tts.wait.assert_called_once_with()
        self.assertFalse(controller._voice_busy.is_set())
        controller.ui.set_state.assert_any_call("THINKING")
        controller.ui.start_speaking.assert_called_once_with()
        controller.ui.stop_speaking.assert_called_once_with()
        controller.ui.set_state.assert_any_call("READY")

    def test_provider_network_failure_returns_ui_to_ready_without_crashing(self):
        controller = self._controller()
        controller.executor = Mock()
        controller.executor.execute_result.side_effect = ConnectionError(
            "private provider endpoint"
        )
        controller.history = deque(maxlen=12)
        controller.ui.muted = False

        controller._on_text_command("offline request")

        self.assertFalse(controller._voice_busy.is_set())
        controller.ui.set_state.assert_any_call("THINKING")
        controller.ui.set_state.assert_any_call("READY")
        logged = "\n".join(str(call.args[0]) for call in controller.ui.write_log.call_args_list)
        self.assertIn("Local intelligence error", logged)
        self.assertNotIn("private provider endpoint", logged)


if __name__ == "__main__":
    unittest.main()
