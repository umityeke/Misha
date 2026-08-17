from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import audit_logger


class AuditSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "audit.db"
        self.path_patch = patch.object(audit_logger, "AUDIT_DB_PATH", self.db_path)
        self.remote_patch = patch.object(audit_logger, "REMOTE_AUDIT_ENABLED", False)
        self.path_patch.start()
        self.remote_patch.start()

    def tearDown(self):
        self.remote_patch.stop()
        self.path_patch.stop()
        self.tempdir.cleanup()

    def test_event_is_structured_private_and_local_file_is_protected(self):
        event = audit_logger.AuditEvent(
            category="tool_execution",
            action="execute",
            status="succeeded",
            tool="send_message",
            details={
                "parameters": {
                    "message_text": "private hello",
                    "api_key": "raw-secret",
                    "path": "/Users/person/private/file.txt",
                },
                "output": "Message sent to Ada",
            },
        )
        self.assertTrue(audit_logger.log_event(event))
        stored = audit_logger.list_events()[0]
        serialized = json.dumps(stored)
        self.assertEqual(stored["event_id"], event.event_id)
        self.assertNotIn("private hello", serialized)
        self.assertNotIn("raw-secret", serialized)
        self.assertNotIn("/Users/person/private", serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertEqual(os.stat(self.db_path).st_mode & 0o777, 0o600)

    def test_retention_and_user_clear(self):
        old = audit_logger.AuditEvent(
            category="test",
            action="old",
            status="ok",
            timestamp=(datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
        )
        current = audit_logger.AuditEvent(
            category="test", action="current", status="ok"
        )
        self.assertTrue(audit_logger.log_event(old))
        self.assertTrue(audit_logger.log_event(current))
        events = audit_logger.list_events()
        self.assertEqual([item["action"] for item in events], ["current"])
        self.assertEqual(audit_logger.clear_events(), 1)
        self.assertEqual(audit_logger.list_events(), [])

    def test_audit_failure_is_fail_soft(self):
        event = audit_logger.AuditEvent(category="test", action="x", status="ok")
        with patch.object(audit_logger, "_store_local", side_effect=OSError("disk full")):
            self.assertFalse(audit_logger.log_event(event))

    def test_remote_requires_explicit_opt_in(self):
        with patch.object(audit_logger, "psycopg2", object()):
            with self.assertRaisesRegex(RuntimeError, "explicit opt-in"):
                audit_logger._get_conn()


if __name__ == "__main__":
    unittest.main()
