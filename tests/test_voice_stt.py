import subprocess
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from core.voice.recorder import write_pcm16_wav
from core.voice.stt import WhisperCppTranscriber


class WhisperCppTranscriberTests(unittest.TestCase):
    def test_missing_binary_fails_healthcheck(self):
        transcriber = WhisperCppTranscriber("/missing/whisper-cli", "/missing/model")
        self.assertFalse(transcriber.status().ready)

    def test_transcription_uses_argument_list_without_shell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o700)
            model = root / "ggml-small.bin"
            model.write_bytes(b"model")
            audio = write_pcm16_wav(
                root / "speech.wav", np.zeros(16000, dtype=np.float32)
            )
            transcriber = WhisperCppTranscriber(executable, model)

            def fake_run(command, **kwargs):
                output_base = Path(command[command.index("--output-file") + 1])
                output_base.with_suffix(".txt").write_text(
                    "Misha test komutu", encoding="utf-8"
                )
                self.assertIsInstance(command, list)
                self.assertNotIn("shell", kwargs)
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("core.voice.stt.subprocess.run", side_effect=fake_run):
                self.assertEqual(transcriber.transcribe(audio), "Misha test komutu")

    def test_gpu_segfault_retries_once_with_cpu_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o700)
            model = root / "model.bin"
            model.write_bytes(b"model")
            audio = write_pcm16_wav(
                root / "speech.wav", np.zeros(16000, dtype=np.float32)
            )
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                if len(commands) == 1:
                    return subprocess.CompletedProcess(command, -signal.SIGSEGV, "", "")
                output_base = Path(command[command.index("--output-file") + 1])
                output_base.with_suffix(".txt").write_text("Misha", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            transcriber = WhisperCppTranscriber(executable, model)
            with patch("core.voice.stt.subprocess.run", side_effect=fake_run):
                self.assertEqual(transcriber.transcribe(audio), "Misha")
            self.assertNotIn("--no-gpu", commands[0])
            self.assertIn("--no-gpu", commands[1])

    def test_transcription_failure_does_not_expose_backend_detail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o700)
            model = root / "model.bin"
            model.write_bytes(b"model")
            audio = write_pcm16_wav(
                root / "speech.wav", np.zeros(16000, dtype=np.float32)
            )
            failed = subprocess.CompletedProcess(
                [str(executable)], 2, "", "private backend path"
            )
            with patch("core.voice.stt.subprocess.run", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "failed safely") as raised:
                    WhisperCppTranscriber(executable, model).transcribe(audio)
            self.assertNotIn("private backend path", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
