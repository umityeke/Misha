import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import doctor


class EnvironmentDoctorTests(unittest.TestCase):
    def test_supported_python_range(self):
        self.assertTrue(doctor.check_python((3, 11, 9)).ok)
        self.assertFalse(doctor.check_python((3, 14, 0)).ok)

    def test_local_configuration_rejects_paid_provider_and_remote_url(self):
        values = {
            "ai_provider": "gemini",
            "local_model": "qwen3-coder:30b",
            "ollama_base_url": "https://example.invalid",
        }
        checks = doctor.check_local_configuration(values.get)
        self.assertFalse(next(c for c in checks if c.name == "config:provider").ok)
        self.assertFalse(next(c for c in checks if c.name == "config:ollama-url").ok)

    def test_private_voice_profile_rejects_broad_permissions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir) / "owner.json"
            profile.write_text("{}", encoding="utf-8")
            os.chmod(profile, 0o644)
            self.assertFalse(doctor.check_private_file("voice", profile, required=True).ok)
            os.chmod(profile, 0o600)
            self.assertTrue(doctor.check_private_file("voice", profile, required=True).ok)

    def test_optional_command_does_not_become_required(self):
        with patch("scripts.doctor.shutil.which", return_value=None):
            result = doctor.check_command("ffmpeg", required=False)
        self.assertFalse(result.ok)
        self.assertFalse(result.required)


if __name__ == "__main__":
    unittest.main()
