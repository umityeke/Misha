from __future__ import annotations

import asyncio
import unittest

from scripts.soak_voice_runtime import run_soak


class VoiceSoakTests(unittest.TestCase):
    def test_bounded_soak_exercises_state_vad_and_realtime_queues(self):
        report = asyncio.run(
            run_soak(
                1.0,
                cycle_pause_seconds=0,
                max_cycles=3,
            )
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["cycles"], 3)
        self.assertEqual(report["interruptions"], 3)
        self.assertEqual(report["state_history_entries"], 27)
        self.assertFalse(report["acoustic_hardware_measured"])
        self.assertEqual(report["errors"], [])

    def test_soak_rejects_unbounded_duration(self):
        with self.assertRaises(ValueError):
            asyncio.run(run_soak(28_801))


if __name__ == "__main__":
    unittest.main()
