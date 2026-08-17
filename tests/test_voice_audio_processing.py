import unittest

import numpy as np

from core.voice.audio_processing import (
    PCMJitterBuffer,
    apply_automatic_gain,
    resample_mono,
)


class VoiceAudioProcessingTests(unittest.TestCase):
    def test_resampling_preserves_duration_and_bounds(self):
        source = np.sin(np.linspace(0, 20, 4800, dtype=np.float32)) * 0.2
        result = resample_mono(source, 48000, 16000)
        self.assertEqual(result.dtype, np.float32)
        self.assertEqual(result.size, 1600)
        self.assertLessEqual(float(np.max(np.abs(result))), 0.21)

    def test_agc_raises_quiet_speech_but_never_clips(self):
        quiet = np.full(1600, 0.025, dtype=np.float32)
        result = apply_automatic_gain(quiet)
        self.assertGreater(float(np.sqrt(np.mean(result ** 2))), 0.09)
        self.assertLessEqual(float(np.max(np.abs(result))), 0.98)
        clipped = np.array([1.0, -1.0], dtype=np.float32)
        np.testing.assert_array_equal(apply_automatic_gain(clipped), clipped)

    def test_jitter_reorders_and_conceals_missing_frames(self):
        buffer = PCMJitterBuffer(4, prefill_frames=2, maximum_frames=4)
        self.assertTrue(buffer.push(11, b"BBBB"))
        self.assertIsNone(buffer.pop())
        self.assertTrue(buffer.push(10, b"AAAA"))
        self.assertEqual(buffer.pop(), b"AAAA")
        self.assertEqual(buffer.pop(), b"BBBB")
        self.assertTrue(buffer.push(13, b"DDDD"))
        self.assertEqual(buffer.pop(), b"\x00" * 4)
        self.assertEqual(buffer.pop(), b"DDDD")
        self.assertEqual(buffer.stats.missing_filled, 1)
        self.assertEqual(buffer.stats.underruns, 1)
        self.assertFalse(buffer.push(12, b"late"))
        self.assertEqual(buffer.stats.late_dropped, 1)


if __name__ == "__main__":
    unittest.main()
