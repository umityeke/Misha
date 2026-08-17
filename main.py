from __future__ import annotations

import threading
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from core.ide_context import start_context_server, stop_context_server

if TYPE_CHECKING:
    from ui import MishaUI


def get_base_dir():
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()


def ide_context_opted_in() -> bool:
    try:
        from memory.config_manager import get_config

        value = str(get_config("ide_context_enabled") or "0").strip().casefold()
        return value in {"1", "true", "yes", "on"}
    except Exception:
        return False


class MishaLocal:
    """Text-first, fully local Misha controller backed by Ollama."""

    def __init__(self, ui: MishaUI):
        from collections import deque
        from agent.executor import AgentExecutor
        from core.voice.tts import MacOSTextToSpeech

        self.ui = ui
        self.task_journal = None
        recoverable_tasks = ()
        try:
            from core.task_journal import TaskJournal

            self.task_journal = TaskJournal()
            recoverable_tasks = self.task_journal.recover_interrupted()
            self.task_journal.purge_old_terminal()
        except Exception as exc:
            self.ui.write_log(
                f"SYS: Encrypted task recovery is unavailable: {type(exc).__name__}"
            )
        self.executor = AgentExecutor(journal=self.task_journal)
        self.tts = MacOSTextToSpeech(voice="")
        self.voice_service = None
        self.voice_recorder = None
        self.proactive_service = None
        self._wake_listener_stop = threading.Event()
        self._voice_busy = threading.Event()
        self._audio_capture_lock = threading.Lock()
        self._follow_up_requested = threading.Event()
        self._wake_listener_thread = None
        self._shutdown_lock = threading.Lock()
        self._stopped = False
        self._active_barge_monitor = None
        self.history = deque(maxlen=12)
        self.ui.on_text_command = self._on_text_command
        self.ui.on_voice_command = self._on_voice_command
        self.ui.on_voice_toggle = self._set_hands_free_enabled
        self.ui.on_vad_sensitivity_change = self._set_vad_sensitivity
        self.ui.on_proactive_toggle = self._set_proactive_enabled
        self.ui.on_proactive_settings_change = self._set_proactive_settings
        self.ui.on_setup_diagnostics = self._collect_setup_diagnostics
        self.ui.on_speaker_test = self._test_speaker
        self.ui.on_audio_devices = self._list_audio_devices
        self.ui.on_audio_device_select = self._select_audio_devices
        self.ui.on_microphone_test = self._test_microphone_level
        self.ui.on_wake_test = self._test_wake_word
        if recoverable_tasks and hasattr(self.ui, "show_recoverable_tasks"):
            self.ui.show_recoverable_tasks(
                recoverable_tasks,
                self.task_journal.dismiss if self.task_journal is not None else None,
            )
        if hasattr(self.ui, "add_shutdown_handler"):
            self.ui.add_shutdown_handler(self.shutdown)

    def _set_hands_free_enabled(self, enabled: bool) -> None:
        from memory.config_manager import set_config

        set_config("hands_free_enabled", "1" if enabled else "0")
        self.ui.write_log(
            "SYS: Hands-free listening enabled."
            if enabled
            else "SYS: Hands-free listening paused."
        )

    def _set_vad_sensitivity(self, sensitivity: str) -> None:
        from core.voice.vad import normalize_vad_sensitivity, vad_config_for_sensitivity
        from memory.config_manager import set_config

        normalized = normalize_vad_sensitivity(sensitivity)
        set_config("vad_sensitivity", normalized)
        if self.voice_recorder is not None:
            self.voice_recorder.vad_config = vad_config_for_sensitivity(normalized)
        self.ui.write_log(f"SYS: Voice sensitivity set to {normalized}.")

    def _proactive_notification(self, notice) -> None:
        """Surface a local proactive notice without interrupting active work."""
        from core.notifications import deliver_notification

        safe_message = " ".join(str(notice.message).split())[:300]
        priority = str(notice.priority).upper()
        if not safe_message:
            return
        self.ui.write_log(f"Misha (proactive/{priority}): {safe_message}")
        receipt = deliver_notification(
            "Misha — proactive notice", safe_message, priority=priority
        )
        if not receipt.delivered:
            self.ui.write_log("SYS: OS notification channel is unavailable; notice remains in Misha.")
        if self._voice_busy.is_set() or self.ui.muted or not self.tts.status().ready:
            return
        try:
            self.tts.speak(safe_message, wait=False)
        except Exception as exc:
            self.ui.write_log(
                f"SYS: Proactive speech unavailable: {type(exc).__name__}"
            )

    def _set_proactive_enabled(self, enabled: bool) -> None:
        """Apply an explicit local observation opt-in or stop it immediately."""
        from core.proactive import ProactiveAI
        from memory.config_manager import (
            get_proactive_denylist,
            get_proactive_settings,
            set_config,
        )

        requested = bool(enabled)
        if requested and self.proactive_service is None:
            self.proactive_service = ProactiveAI(
                speak_callback=self._proactive_notification,
                denylist=get_proactive_denylist(),
                settings=get_proactive_settings(),
            )
        running = False
        if requested and self.proactive_service is not None:
            running = self.proactive_service.start(consent=True)
        elif self.proactive_service is not None:
            self.proactive_service.stop()
        set_config("proactive_enabled", "1" if running else "0")
        self.ui.set_proactive_enabled(running)
        self.ui.write_log(
            "SYS: Proactive local observation enabled; protected screens remain excluded."
            if running
            else "SYS: Proactive local observation stopped."
        )

    def _set_proactive_settings(self, settings, denylist) -> None:
        from memory.config_manager import (
            save_proactive_denylist,
            save_proactive_settings,
        )

        validated_settings = save_proactive_settings(settings)
        normalized_denylist = save_proactive_denylist(denylist)
        if self.proactive_service is not None:
            self.proactive_service.update_settings(
                validated_settings, denylist=normalized_denylist
            )
        self.ui.write_log(
            "SYS: Proactive privacy and notification settings updated locally."
        )

    def _collect_setup_diagnostics(self):
        from core.setup_diagnostics import collect_setup_checks

        return collect_setup_checks(tts=self.tts)

    def _test_speaker(self) -> tuple[bool, str]:
        if self._voice_busy.is_set():
            return False, "Misha is busy; retry the speaker test in a moment."
        status = self.tts.status()
        if not status.ready:
            return False, status.message
        try:
            self.tts.speak(
                "Misha ses testi başarılı. Yerel hoparlör bağlantısı hazır.",
                wait=False,
            )
            return True, "Local speaker test started successfully."
        except Exception as exc:
            return False, f"Speaker test failed safely: {type(exc).__name__}"

    def _list_audio_devices(self) -> dict[str, list[dict]]:
        from core.voice.devices import AudioDeviceManager

        manager = AudioDeviceManager(sample_rate=16000)
        return {
            "inputs": [
                {"index": item.index, "name": item.name, "default": item.is_default_input}
                for item in manager.list_devices("input")
            ],
            "outputs": [
                {"index": item.index, "name": item.name, "default": item.is_default_output}
                for item in manager.list_devices("output")
            ],
        }

    def _select_audio_devices(
        self, input_index: int | None, output_index: int | None
    ) -> tuple[bool, str]:
        from core.voice.devices import AudioDeviceManager
        from memory.config_manager import set_config

        manager = AudioDeviceManager(sample_rate=16000)
        microphone = manager.resolve_input(input_index)
        speaker = manager.resolve_output(output_index)
        set_config("audio_input_device_id", str(microphone.index))
        set_config("audio_input_device_name", microphone.name)
        set_config("audio_output_device_id", str(speaker.index))
        set_config("audio_output_device_name", speaker.name)
        if self.voice_recorder is not None:
            self.voice_recorder.device_manager = manager
            self.voice_recorder.preferred_input_index = microphone.index
            self.voice_recorder.preferred_input_name = microphone.name
        return True, (
            f"Microphone preference saved: {microphone.name}. "
            f"Speaker validated: {speaker.name}; macOS controls the active system output."
        )

    def _test_microphone_level(self) -> tuple[bool, str]:
        import tempfile
        from core.voice.diagnostics import analyze_microphone_wav

        if self.voice_recorder is None:
            return False, "Microphone service is not ready."
        if self._voice_busy.is_set():
            return False, "Misha is busy; retry the microphone test in a moment."
        temp_path = None
        self._voice_busy.set()
        try:
            with tempfile.NamedTemporaryFile(
                prefix="misha-mic-test-", suffix=".wav", delete=False
            ) as handle:
                temp_path = Path(handle.name)
            with self._audio_capture_lock:
                self.voice_recorder.record(temp_path, seconds=2.0)
            result = analyze_microphone_wav(temp_path)
            return result.ready, (
                f"{result.message} RMS={result.rms:.3f}, peak={result.peak:.3f}"
            )
        except Exception as exc:
            return False, f"Microphone test failed safely: {type(exc).__name__}"
        finally:
            self._voice_busy.clear()
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _test_wake_word(self) -> tuple[bool, str]:
        import tempfile
        from core.voice.wake import match_wake_word

        if self.voice_recorder is None or self.voice_service is None:
            return False, "Wake-word service is not ready."
        if self._voice_busy.is_set():
            return False, "Misha is busy; retry the wake-word test in a moment."
        temp_path = None
        self._voice_busy.set()
        try:
            with tempfile.NamedTemporaryFile(
                prefix="misha-wake-test-", suffix=".wav", delete=False
            ) as handle:
                temp_path = Path(handle.name)
            with self._audio_capture_lock:
                self.voice_recorder.record_until_silence(
                    temp_path, cancel_event=self._wake_listener_stop
                )
                result = self.voice_service.verify_and_transcribe(temp_path)
            if not result.accepted:
                return False, "Owner voice or offline transcription was not accepted."
            wake = match_wake_word(result.transcript)
            if not wake.detected:
                return False, 'Wake word was not detected; say “Misha” clearly.'
            return True, 'Owner-verified “Misha” wake word detected locally.'
        except Exception as exc:
            return False, f"Wake-word test failed safely: {type(exc).__name__}"
        finally:
            self._voice_busy.clear()
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop local audio and worker activity without terminating the process abruptly."""
        with self._shutdown_lock:
            if self._stopped:
                return
            self._stopped = True
            self._wake_listener_stop.set()
        monitor = self._active_barge_monitor
        if monitor is not None:
            monitor.stop(timeout=min(max(0.0, float(timeout)), 1.0))
        self.tts.stop()
        if self.proactive_service is not None:
            self.proactive_service.stop(timeout=min(max(0.0, float(timeout)), 1.0))
        self._follow_up_requested.clear()
        thread = self._wake_listener_thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=max(0.0, float(timeout)))

    def _conversation_context(self) -> str:
        if not self.history:
            return ""
        lines = ["[RECENT SESSION CONVERSATION — use only for continuity]"]
        lines.extend(f"{role}: {text}" for role, text in self.history)
        return "\n".join(lines)[-6000:]

    def _on_text_command(self, text: str):
        import uuid

        self._voice_busy.set()
        self.ui.set_state("THINKING")
        try:
            execution = self.executor.execute_result(
                text,
                approve=self.ui.ask_approval,
                context=self._conversation_context(),
                cancel_flag=self._wake_listener_stop,
                request_id=uuid.uuid4().hex,
                state_callback=self.ui.set_state,
                plan_callback=self.ui.show_plan,
            )
            result = execution.message
            if execution.succeeded and result:
                self.history.append(("User", text[:2000]))
                self.history.append(("Misha", str(result)[:3000]))
                self.ui.write_log(f"Misha: {result}")
                if not self.ui.muted and self.tts.status().ready:
                    from core.voice.barge_in import BargeInMonitor

                    self.ui.start_speaking()
                    monitor = None
                    try:
                        self.tts.speak(str(result)[:1200], wait=False)
                        if self.voice_recorder is not None and self.voice_service is not None:
                            monitor = BargeInMonitor(
                                self.voice_recorder,
                                self.voice_service,
                                self._interrupt_speech,
                                capture_lock=self._audio_capture_lock,
                            )
                            self._active_barge_monitor = monitor
                            monitor.start()
                        self.tts.wait()
                    except Exception as speech_error:
                        self.ui.write_log(f"SYS: Local speech error: {speech_error}")
                    finally:
                        if monitor is not None:
                            monitor.stop()
                        self._active_barge_monitor = None
                        self.ui.stop_speaking()
            elif result:
                self.ui.write_log(
                    f"SYS: Task {execution.status.value}: {result}"
                )
        except Exception as exc:
            traceback.print_exc()
            self.ui.write_log(
                f"SYS: Local intelligence error: {type(exc).__name__}. "
                "The private error detail was written only to the local diagnostic stream."
            )
        finally:
            self._voice_busy.clear()
            if not self.ui.muted:
                self.ui.set_state(
                    "LISTENING" if self._follow_up_requested.is_set() else "READY"
                )

    def _interrupt_speech(self) -> None:
        stop_result = self.tts.stop()
        self._follow_up_requested.set()
        latency_ms = getattr(stop_result, "latency_ms", None)
        suffix = f" ({latency_ms:.0f} ms)." if latency_ms is not None else "."
        self.ui.write_log(
            "SYS: Speech interrupted by verified owner command; "
            f"follow-up listening is armed{suffix}"
        )
        if not self.ui.muted:
            self.ui.set_state("LISTENING")

    def _consume_follow_up_request(self, now: float) -> float:
        if not self._follow_up_requested.is_set():
            return 0.0
        self._follow_up_requested.clear()
        self.ui.set_state("LISTENING")
        self.ui.write_log("Misha: Dinliyorum; yeni komutunu söyle…")
        return now + 8.0

    def _on_voice_command(self):
        import tempfile

        if self.voice_service is None or self.voice_recorder is None:
            self.ui.write_log("SYS: Local voice setup is incomplete.")
            return
        temp_path = None
        try:
            try:
                from core.ai.runtime import release_provider_memory
                release_provider_memory()
                self.ui.write_log("SYS: Released language-model memory for local speech.")
            except Exception as release_error:
                self.ui.write_log(f"SYS: Model memory release warning: {release_error}")
            with tempfile.NamedTemporaryFile(
                prefix="misha-voice-", suffix=".wav", delete=False
            ) as handle:
                temp_path = Path(handle.name)
            self.ui.set_state("LISTENING")
            self.ui.write_log(
                "SYS: Listening locally; recording stops after you finish speaking…"
            )
            with self._audio_capture_lock:
                self.voice_recorder.record_until_silence(
                    temp_path,
                    cancel_event=self._wake_listener_stop,
                )
                self.ui.set_state("THINKING")
                result = self.voice_service.process_recording(temp_path)
            if result.accepted:
                self.ui.write_log(
                    f"You (voice, score {result.speaker_score:.2f}): {result.transcript}"
                )
            else:
                self.ui.write_log(f"SYS: Voice command rejected: {result.message}")
        except Exception as exc:
            self.ui.write_log(f"SYS: Local microphone error: {exc}")
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            if not self.ui.muted:
                self.ui.set_state("READY")

    def _continuous_voice_loop(self):
        import tempfile
        import time

        from core.ai.runtime import release_provider_memory
        from core.voice.wake import WakeGuard, WakeMetrics, match_wake_word

        armed_until = 0.0
        wake_guard = WakeGuard()
        wake_metrics = WakeMetrics()
        try:
            release_provider_memory()
        except Exception as exc:
            self.ui.write_log(f"SYS: Wake listener memory warning: {exc}")
        self.ui.write_log(
            'SYS: Hands-free mode active. Say "Misha" followed by your command.'
        )
        while not self._wake_listener_stop.is_set():
            if self.ui.muted or self._voice_busy.is_set():
                time.sleep(0.2)
                continue
            follow_up_deadline = self._consume_follow_up_request(time.monotonic())
            if follow_up_deadline:
                armed_until = follow_up_deadline
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix="misha-wake-", suffix=".wav", delete=False
                ) as handle:
                    temp_path = Path(handle.name)
                with self._audio_capture_lock:
                    self.voice_recorder.record_until_silence(
                        temp_path,
                        cancel_event=self._wake_listener_stop,
                    )
                    result = self.voice_service.verify_and_transcribe(temp_path)
                if self._voice_busy.is_set():
                    # A user-started diagnostic owns the next capture. Discard this
                    # completed listener turn rather than dispatching it concurrently.
                    continue
                if not result.accepted:
                    continue
                wake = match_wake_word(result.transcript)
                armed = time.monotonic() <= armed_until
                if not wake.detected and not armed:
                    wake_metrics.record("verified_no_wake")
                    continue
                if wake.detected:
                    guard = wake_guard.evaluate(
                        bypass_cooldown=armed and bool(wake.command)
                    )
                    if not guard.allowed:
                        wake_metrics.record("wake_suppressed")
                        if guard.reason == "rate_limit":
                            self.ui.write_log(
                                "SYS: Repeated wake triggers were temporarily limited."
                            )
                        continue
                    wake_metrics.record("wake_detected")
                command = wake.command if wake.detected else result.transcript.strip()
                if wake.detected:
                    self.ui.notify_wake_detected()
                if wake.detected and not command:
                    armed_until = time.monotonic() + 8.0
                    self.ui.write_log("Misha: Dinliyorum…")
                    continue
                armed_until = 0.0
                if not command:
                    continue
                self._voice_busy.set()
                self.ui.write_log(
                    f"You (hands-free, score {result.speaker_score:.2f}): {command}"
                )
                wake_metrics.record("command_dispatched")
                self._on_text_command(command)
                try:
                    release_provider_memory()
                except Exception as exc:
                    self.ui.write_log(f"SYS: Wake listener memory warning: {exc}")
            except Exception as exc:
                if "No speech was detected" not in str(exc) and not self._wake_listener_stop.is_set():
                    self.ui.write_log(f"SYS: Hands-free listener warning: {exc}")
                    time.sleep(0.5)
            finally:
                self._voice_busy.clear()
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
                if not self.ui.muted and not self._wake_listener_stop.is_set():
                    self.ui.set_state(
                        "LISTENING" if time.monotonic() <= armed_until else "READY"
                    )

    def start(self):
        from core.ai.runtime import get_provider
        from memory.config_manager import get_config, set_config
        from core.voice.devices import AudioDeviceError, AudioDeviceManager
        from core.voice.identity import LocalVoiceIdentity
        from core.voice.recorder import SoundDeviceRecorder
        from core.voice.service import LocalVoiceService
        from core.voice.stt import WhisperCppTranscriber
        from core.voice.vad import normalize_vad_sensitivity, vad_config_for_sensitivity

        ready, message = get_provider().healthcheck()
        if ready:
            self.ui.write_log(f"SYS: {message}")
            self.ui.write_log("SYS: MISHA local intelligence is online.")
            self.ui.set_state("READY")
        else:
            self.ui.write_log(f"SYS: {message}")
            self.ui.set_state("THINKING")

        self.ui.set_proactive_enabled(False)
        proactive_value = (get_config("proactive_enabled") or "0").strip().lower()
        if proactive_value in {"1", "true", "yes", "on"}:
            self._set_proactive_enabled(True)

        whisper_cli = get_config("whisper_cli_path") or "/opt/homebrew/bin/whisper-cli"
        whisper_model = get_config("whisper_model_path") or ""
        voice_profile = Path.home() / ".misha" / "voice" / "owner.json"
        transcriber = WhisperCppTranscriber(whisper_cli, whisper_model)
        stt_status = transcriber.status()
        identity = LocalVoiceIdentity(voice_profile)
        if not stt_status.ready:
            self.ui.set_voice_available(False, stt_status.message)
        elif not identity.is_enrolled():
            self.ui.set_voice_available(False, "Owner voice enrollment is required.")
        else:
            stored_index = get_config("audio_input_device_id")
            try:
                preferred_index = int(stored_index) if stored_index is not None else None
            except (TypeError, ValueError):
                preferred_index = None
            preferred_name = get_config("audio_input_device_name")
            try:
                device_manager = AudioDeviceManager(sample_rate=16000)
                microphone = device_manager.resolve_input(
                    preferred_index,
                    preferred_name,
                )
            except AudioDeviceError as exc:
                self.ui.set_voice_available(False, str(exc))
                return
            set_config("audio_input_device_id", str(microphone.index))
            set_config("audio_input_device_name", microphone.name)
            vad_sensitivity = normalize_vad_sensitivity(
                get_config("vad_sensitivity")
            )
            set_config("vad_sensitivity", vad_sensitivity)
            self.voice_recorder = SoundDeviceRecorder(
                device_manager=device_manager,
                preferred_input_index=microphone.index,
                preferred_input_name=microphone.name,
                vad_config=vad_config_for_sensitivity(vad_sensitivity),
                quality_warning=self.ui.write_log,
            )
            self.voice_service = LocalVoiceService(
                transcriber, identity, self._on_text_command
            )
            self.ui.set_voice_available(
                True,
                f"Hands-free local voice is active on microphone: {microphone.name}",
            )
            hands_free_value = (get_config("hands_free_enabled") or "1").strip().lower()
            hands_free_enabled = hands_free_value not in {"0", "false", "no", "off"}
            self.ui.set_hands_free_enabled(hands_free_enabled)
            self.ui.set_vad_sensitivity(vad_sensitivity)
            self._wake_listener_thread = threading.Thread(
                target=self._continuous_voice_loop,
                name="misha-hands-free-listener",
                daemon=True,
            )
            self._wake_listener_thread.start()

def main():
    import os
    if len(sys.argv) == 3 and sys.argv[1] == "--deliver-reminder":
        from core.reminder_store import REMINDER_ID
        from core.reminder_worker import deliver_reminder

        reminder_id = sys.argv[2]
        raise SystemExit(deliver_reminder(reminder_id) if REMINDER_ID.fullmatch(reminder_id) else 2)

    if os.environ.get("PORT"):
        import http.server
        import socketserver
        port_str = os.environ.get("PORT")
        port = int(port_str) if port_str else 8080
        class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"Misha Cloud Backend is Online.")
        with socketserver.TCPServer(("", port), HealthCheckHandler) as httpd:
            print(f"[MISHA] ☁️ Running in Headless Cloud Mode on port {port}")
            httpd.serve_forever()
        return

    try:
        from memory.config_manager import initialize_secure_credentials
        initialize_secure_credentials()
    except Exception as exc:
        print(f"[MISHA] Secure credential initialization failed: {type(exc).__name__}")

    from core.pin_dialog import require_pin
    require_pin()

    from ui import MishaUI
    ui = MishaUI(str(BASE_DIR / "face.png"))
    context_server = None
    if ide_context_opted_in():
        try:
            context_server = start_context_server()
            ui.add_shutdown_handler(lambda: stop_context_server(context_server))
            print("[MISHA] 🌐 IDE Context Server started on port 47384")
        except Exception as e:
            print(f"[MISHA] ⚠️ Failed to start IDE context server: {e}")
    else:
        print("[MISHA] IDE Context Server is OFF until explicit opt-in.")

    def runner():
        from memory.config_manager import get_config

        ui.wait_for_setup()
        provider = (get_config("ai_provider") or "ollama").strip().lower()
        if provider != "ollama":
            ui.write_log(
                f"SYS: Provider '{provider}' is disabled. MISHA only permits local Ollama."
            )
            ui.set_state("ERROR")
            return
        MishaLocal(ui).start()

    threading.Thread(target=runner, daemon=True).start()

    # pynput's macOS input-source lookup can call TSM APIs from its worker
    # thread. Recent macOS versions enforce main-queue access and terminate
    # the process with SIGTRAP, so keep the global shortcut off on macOS.
    # The desktop icon and in-app visibility controls remain available.
    if sys.platform != "darwin":
        try:
            from pynput import keyboard

            def on_activate_h():
                ui.toggle_visibility()

            hotkey = keyboard.GlobalHotKeys({
                '<alt>+<space>': on_activate_h
            })
            hotkey.start()
        except Exception as e:
            print(f"[MISHA] ⚠️ Global hotkey failed to start: {e}")

    ui.root.mainloop()

if __name__ == "__main__":
    main()
