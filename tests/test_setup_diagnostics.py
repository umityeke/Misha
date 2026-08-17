import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.setup_diagnostics import collect_setup_checks, setup_is_ready


class SetupDiagnosticsTests(unittest.TestCase):
    def test_all_local_components_can_report_ready(self):
        provider = Mock()
        provider.healthcheck.return_value = (True, "Local model ready")
        devices = Mock()
        microphone = Mock()
        microphone.name = "Built-in Mic"
        speaker = Mock()
        speaker.name = "Built-in Output"
        devices.resolve_input.return_value = microphone
        devices.resolve_output.return_value = speaker
        tts = Mock()
        tts.status.return_value = Mock(ready=True, message="ready")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            whisper_cli = root / "whisper-cli"
            whisper_model = root / "model.bin"
            profile = root / "owner.json"
            whisper_cli.write_text("binary")
            whisper_cli.chmod(0o700)
            whisper_model.write_text("model")
            profile.write_text("{}")
            profile.chmod(0o600)
            values = {
                "whisper_cli_path": str(whisper_cli),
                "whisper_model_path": str(whisper_model),
            }
            with patch("core.setup_diagnostics.Path.home", return_value=root):
                expected_profile = root / ".misha" / "voice" / "owner.json"
                expected_profile.parent.mkdir(parents=True)
                profile.replace(expected_profile)
                checks = collect_setup_checks(
                    getter=values.get, provider=provider,
                    device_manager=devices, tts=tts,
                )
        self.assertTrue(setup_is_ready(checks))
        self.assertEqual({check.key for check in checks}, {
            "local_ai", "speech_recognition", "owner_voice",
            "microphone", "speaker", "wake_word",
        })

    def test_missing_components_fail_without_sensitive_paths(self):
        provider = Mock()
        provider.healthcheck.return_value = (False, "offline")
        devices = Mock()
        devices.resolve_input.side_effect = RuntimeError("/Users/private/mic")
        devices.resolve_output.side_effect = RuntimeError("/Users/private/speaker")
        tts = Mock()
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.setup_diagnostics.Path.home", return_value=Path(temp_dir)
        ):
            checks = collect_setup_checks(
                getter=lambda _key: None, provider=provider,
                device_manager=devices, tts=tts,
            )
        self.assertFalse(setup_is_ready(checks))
        rendered = repr(checks)
        self.assertNotIn("/Users/private", rendered)


if __name__ == "__main__":
    unittest.main()
