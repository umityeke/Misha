import sqlite3
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from core.task_journal import TaskJournal


class TaskJournalTests(unittest.TestCase):
    def _journal(self, directory: str, cipher: Fernet | None = None) -> TaskJournal:
        return TaskJournal(
            Path(directory) / "task_journal.db",
            cipher=cipher or Fernet(Fernet.generate_key()),
        )

    def test_active_task_is_encrypted_and_recovered_as_interrupted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = self._journal(temp_dir)
            journal.start("request-1", "müşteriye özel güvenli görev")
            journal.set_phase(
                "request-1", "executing", completed_steps=1, total_steps=3,
                external_effect_seen=True,
            )
            with sqlite3.connect(journal.path) as conn:
                stored = conn.execute(
                    "SELECT goal_cipher,phase FROM task_journal WHERE request_id='request-1'"
                ).fetchone()
            self.assertNotIn("müşteriye", stored[0])
            self.assertTrue(stored[0].startswith("enc:v1:"))
            self.assertEqual(journal.path.stat().st_mode & 0o777, 0o600)
            recovered = journal.recover_interrupted()
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0].goal, "müşteriye özel güvenli görev")
            self.assertEqual(recovered[0].phase, "interrupted")
            self.assertTrue(recovered[0].external_effect_seen)

    def test_terminal_task_is_never_offered_for_automatic_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = self._journal(temp_dir)
            journal.start("request-2", "completed work")
            journal.set_phase("request-2", "succeeded", completed_steps=2, total_steps=2)
            self.assertEqual(journal.recover_interrupted(), ())

    def test_partial_checkpoint_requires_review_and_can_be_dismissed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = self._journal(temp_dir)
            journal.start("request-3", "partial work")
            journal.set_phase("request-3", "partial", completed_steps=1, total_steps=2)
            self.assertEqual(len(journal.recover_interrupted()), 1)
            self.assertTrue(journal.dismiss("request-3"))
            self.assertEqual(journal.recover_interrupted(), ())

    def test_wrong_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = self._journal(temp_dir)
            first.start("request-4", "private goal")
            second = self._journal(temp_dir, Fernet(Fernet.generate_key()))
            with self.assertRaisesRegex(RuntimeError, "authenticated"):
                second.recover_interrupted()

    def test_invalid_phase_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = self._journal(temp_dir)
            journal.start("request-5", "safe task")
            with self.assertRaises(ValueError):
                journal.set_phase("request-5", "run-anything")


if __name__ == "__main__":
    unittest.main()
