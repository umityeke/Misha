import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import config_manager


class LocalVoiceConfigTests(unittest.TestCase):
    def test_rejects_missing_voice_components(self):
        with self.assertRaises(ValueError):
            config_manager.save_local_voice_config("/missing/cli", "/missing/model.bin")

    def test_saves_valid_local_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cli = root / "whisper-cli"
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o700)
            model = root / "model.bin"
            model.write_bytes(b"model")
            stored = {}
            with patch.object(config_manager, "set_config", stored.__setitem__):
                config_manager.save_local_voice_config(str(cli), str(model))
            self.assertEqual(stored["whisper_cli_path"], str(cli.resolve()))
            self.assertEqual(stored["whisper_model_path"], str(model.resolve()))


if __name__ == "__main__":
    unittest.main()
