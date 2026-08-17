import unittest

from core.audit_view import format_audit_events


class AuditViewTests(unittest.TestCase):
    def test_view_only_renders_allowlisted_metadata(self):
        rendered = format_audit_events([{
            "timestamp": "2026-08-16T20:00:00+00:00",
            "category": "tool_execution",
            "action": "send_message",
            "status": "rejected",
            "tool": "send_message",
            "details": {
                "reason": "approval_required",
                "message": "private message body",
                "password": "secret-value",
                "path": "/Users/person/private.txt",
            },
        }])
        self.assertIn("tool_execution / send_message", rendered)
        self.assertIn("reason=approval_required", rendered)
        self.assertNotIn("private message body", rendered)
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("/Users/person", rendered)

    def test_control_characters_are_removed_and_output_is_bounded(self):
        event = {
            "timestamp": "now",
            "category": "safe\nforged",
            "action": "x" * 500,
            "status": "ok",
            "details": {"reason": "line\nforge"},
        }
        rendered = format_audit_events([event])
        self.assertNotIn("safe\nforged", rendered)
        self.assertLess(len(rendered), 1000)

    def test_empty_view_has_clear_message(self):
        self.assertEqual(
            format_audit_events([]), "No local security events yet."
        )


if __name__ == "__main__":
    unittest.main()
