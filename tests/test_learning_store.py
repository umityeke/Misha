import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import learning_store


class LearningStoreTests(unittest.TestCase):
    def test_rule_is_persisted_and_formatted(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            learning_store, "LEARNING_DB_PATH", Path(temp_dir) / "learning.db"
        ):
            learning_store.add_rule("Run tests before marking work complete.")
            rules = learning_store.list_rules()
            self.assertEqual(rules[0]["scope"], "global")
            self.assertIn("Run tests", learning_store.format_rules_for_prompt())
            self.assertEqual(
                learning_store.LEARNING_DB_PATH.stat().st_mode & 0o777,
                0o600,
            )

    def test_credentials_are_rejected(self):
        with self.assertRaises(ValueError):
            learning_store._validate_rule("api_key = abc123")
        with self.assertRaises(ValueError):
            learning_store._validate_rule("şifre: 1234")


if __name__ == "__main__":
    unittest.main()
