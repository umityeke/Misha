import tempfile
import unittest
from pathlib import Path

import numpy as np

from core.voice.diagnostics import analyze_microphone_wav
from core.voice.recorder import write_pcm16_wav


class VoiceDiagnosticsTests(unittest.TestCase):
    def _analyze(self, samples):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.wav"
            write_pcm16_wav(path, np.asarray(samples, dtype=np.float32))
            return analyze_microphone_wav(path)

    def test_healthy_microphone_level_is_accepted(self):
        signal = np.sin(np.linspace(0, 100, 16_000)) * 0.15
        result = self._analyze(signal)
        self.assertTrue(result.ready)
        self.assertGreater(result.rms, 0.006)
        self.assertLess(result.peak, 0.98)

    def test_low_microphone_level_is_rejected(self):
        result = self._analyze(np.zeros(16_000) + 0.001)
        self.assertFalse(result.ready)
        self.assertIn("too low", result.message)

    def test_clipping_is_rejected(self):
        result = self._analyze(np.ones(16_000))
        self.assertFalse(result.ready)
        self.assertIn("clipping", result.message)


if __name__ == "__main__":
    unittest.main()
