import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from core.voice.identity import LocalVoiceIdentity
from core.voice.recorder import write_pcm16_wav


def _sample(path: Path, frequency: float, phase: float = 0.0) -> Path:
    rate = 16000
    timeline = np.arange(rate * 2, dtype=np.float32) / rate
    signal = (
        0.55 * np.sin(2 * math.pi * frequency * timeline + phase)
        + 0.22 * np.sin(2 * math.pi * frequency * 2.1 * timeline)
        + 0.08 * np.sin(2 * math.pi * frequency * 3.7 * timeline)
    )
    return write_pcm16_wav(path, signal, sample_rate=rate)


class LocalVoiceIdentityTests(unittest.TestCase):
    def test_requires_three_enrollment_samples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            identity = LocalVoiceIdentity(root / "owner.json")
            one = _sample(root / "one.wav", 180)
            with self.assertRaises(ValueError):
                identity.enroll([one])

    def test_profile_is_private_and_matches_similar_sample(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            identity = LocalVoiceIdentity(root / "owner.json", threshold=0.8)
            samples = [
                _sample(root / f"enroll-{index}.wav", 180, index * 0.2)
                for index in range(3)
            ]
            identity.enroll(samples)
            self.assertEqual(identity.profile_path.stat().st_mode & 0o777, 0o600)
            result = identity.verify(_sample(root / "check.wav", 182, 0.4))
            self.assertTrue(result.accepted)
            self.assertGreaterEqual(result.score, 0.8)

    def test_quiet_sample_is_rejected_safely(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            identity = LocalVoiceIdentity(root / "owner.json", threshold=0.8)
            identity.enroll([
                _sample(root / f"enroll-{index}.wav", 180, index * 0.2)
                for index in range(3)
            ])
            quiet = write_pcm16_wav(
                root / "quiet.wav", np.zeros(32000, dtype=np.float32)
            )
            result = identity.verify(quiet)
            self.assertFalse(result.accepted)
            self.assertIn("failed", result.message.lower())


if __name__ == "__main__":
    unittest.main()
