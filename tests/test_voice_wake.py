import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.voice.wake import WakeGuard, WakeMetrics, match_wake_word


class WakeWordTests(unittest.TestCase):
    def test_turkish_and_english_spellings_are_detected(self):
        for transcript in (
            "Misha, projeyi aç",
            "Mişa projeyi aç",
            "MİŞA, projeyi aç",
        ):
            with self.subTest(transcript=transcript):
                match = match_wake_word(transcript)
                self.assertTrue(match.detected)
                self.assertEqual(match.command, "projeyi aç")

    def test_wake_word_alone_arms_followup(self):
        match = match_wake_word("Mişa!")
        self.assertTrue(match.detected)
        self.assertEqual(match.command, "")

    def test_unrelated_speech_is_ignored(self):
        match = match_wake_word("Bugün projeyi aç")
        self.assertFalse(match.detected)
        self.assertEqual(match.command, "")

    def test_partial_word_does_not_trigger(self):
        self.assertFalse(match_wake_word("Mishal projeyi aç").detected)

    def test_name_in_middle_of_sentence_does_not_trigger(self):
        self.assertFalse(
            match_wake_word("Bugün Misha hakkında konuşalım").detected
        )

    def test_optional_greeting_prefix_is_supported(self):
        for transcript in ("Hey Misha, nasılsın?", "Selam Mişa hava nasıl?"):
            with self.subTest(transcript=transcript):
                self.assertTrue(match_wake_word(transcript).detected)

    def test_possessive_name_is_not_a_command(self):
        self.assertFalse(match_wake_word("Misha'nın sesi güzel").detected)

    def test_guard_enforces_cooldown_and_rate_limit(self):
        guard = WakeGuard(cooldown_seconds=1.0, window_seconds=10, max_triggers=2)
        self.assertTrue(guard.evaluate(now=0).allowed)
        self.assertEqual(guard.evaluate(now=0.5).reason, "cooldown")
        self.assertTrue(
            guard.evaluate(now=0.5, bypass_cooldown=True).allowed
        )
        self.assertEqual(guard.evaluate(now=2.0).reason, "rate_limit")
        self.assertTrue(guard.evaluate(now=11.1).allowed)

    def test_metrics_store_only_approved_aggregate_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "wake.db"
            metrics = WakeMetrics(path)
            now = datetime.now(timezone.utc)
            metrics.record("wake_detected", occurred_at=now)
            metrics.record("wake_detected", occurred_at=now)
            metrics.record("command_dispatched", occurred_at=now)
            self.assertEqual(
                metrics.snapshot(),
                {"command_dispatched": 1, "wake_detected": 2},
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                metrics.record("raw_transcript")


if __name__ == "__main__":
    unittest.main()
