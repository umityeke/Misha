import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions.db_manager import db_manager
from agent.verifier import VerificationStatus, verify_tool_result
from core.action_policy import approval_reason


class DatabaseToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name).resolve()
        self.database = self.workspace / "sample.sqlite"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            connection.execute("INSERT INTO items(name) VALUES ('first')")
        self.workspace_patch = patch(
            "actions.db_manager.selected_workspace", return_value=self.workspace
        )
        self.workspace_patch.start()
        self.params = {"workspace": str(self.workspace), "db_path": "sample.sqlite"}

    def tearDown(self):
        self.workspace_patch.stop()
        self.temp.cleanup()

    def test_read_query_is_bounded_and_independently_verified(self):
        params = {**self.params, "action": "query", "query": "SELECT id, name FROM items"}
        output = db_manager(params)
        self.assertEqual(output, 'Database result: [[1, "first"]]')
        result = verify_tool_result("db_manager", params, output)
        self.assertIs(result.status, VerificationStatus.VERIFIED)
        self.assertIsNone(approval_reason("db_manager", params))

    def test_mutation_requires_exact_readback_and_approval(self):
        params = {
            **self.params,
            "action": "execute",
            "query": "INSERT INTO items(name) VALUES ('second')",
            "verify_query": "SELECT name FROM items ORDER BY id",
            "expected_json": json.dumps([["first"], ["second"]]),
        }
        output = db_manager(params)
        self.assertIn("committed and verified", output)
        result = verify_tool_result("db_manager", params, output)
        self.assertIs(result.status, VerificationStatus.VERIFIED)
        self.assertIn("database mutation", approval_reason("db_manager", params) or "")

    def test_failed_mutation_verification_rolls_back(self):
        params = {
            **self.params,
            "action": "execute",
            "query": "DELETE FROM items",
            "verify_query": "SELECT count(*) FROM items",
            "expected_json": "[[99]]",
        }
        output = db_manager(params)
        self.assertTrue(output.startswith("Database error:"))
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM items").fetchone()[0], 1)

    def test_path_escape_and_non_read_query_fail_closed(self):
        escaped = db_manager({**self.params, "action": "query", "db_path": "../outside.db", "query": "SELECT 1"})
        mutation = db_manager({**self.params, "action": "query", "query": "DELETE FROM items"})
        self.assertTrue(escaped.startswith("Database error:"))
        self.assertTrue(mutation.startswith("Database error:"))


if __name__ == "__main__":
    unittest.main()
