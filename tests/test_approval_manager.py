import unittest
from unittest.mock import patch

from core.action_policy import approval_prompt
from core.approval import ApprovalError, ApprovalManager


class ApprovalManagerTests(unittest.TestCase):
    def setUp(self):
        self.audit_patch = patch("core.approval._audit_approval")
        self.audit = self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop()

    def test_grant_is_single_use_and_bound_to_exact_scope(self):
        manager = ApprovalManager()
        parameters = {"receiver": "Ada", "message_text": "Hi", "platform": "WhatsApp"}
        grant = manager.request(
            "send_message", parameters, "send a message", lambda _: True
        )
        self.assertIsNotNone(grant)
        manager.consume(grant.token, "send_message", parameters)
        with self.assertRaises(ApprovalError):
            manager.consume(grant.token, "send_message", parameters)

    def test_changed_parameters_and_expired_grant_fail_closed(self):
        now = [100.0]
        manager = ApprovalManager(ttl_seconds=2, clock=lambda: now[0])
        parameters = {"action": "delete", "path": "/tmp/a"}
        changed_grant = manager.request(
            "file_controller", parameters, "delete", lambda _: True
        )
        with self.assertRaises(ApprovalError):
            manager.consume(
                changed_grant.token,
                "file_controller",
                {"action": "delete", "path": "/tmp/b"},
            )
        expired_grant = manager.request(
            "file_controller", parameters, "delete", lambda _: True
        )
        now[0] = 103.0
        with self.assertRaises(ApprovalError):
            manager.consume(expired_grant.token, "file_controller", parameters)

    def test_missing_or_rejected_callback_issues_no_grant(self):
        manager = ApprovalManager()
        self.assertIsNone(manager.request("x", {}, "risk", None))
        self.assertIsNone(manager.request("x", {}, "risk", lambda _: False))

    def test_prompt_shows_exact_target_but_redacts_credentials(self):
        prompt = approval_prompt(
            "send_message",
            {"receiver": "Ada", "api_key": "sensitive", "message_text": "Hi"},
            "send a message",
        )
        self.assertIn('"receiver": "Ada"', prompt)
        self.assertIn("[REDACTED]", prompt)
        self.assertNotIn("sensitive", prompt)

    def test_approval_lifecycle_is_audited_without_parameters_or_token(self):
        manager = ApprovalManager()
        parameters = {"receiver": "Ada", "message_text": "private"}
        grant = manager.request(
            "send_message", parameters, "external message", lambda _: True
        )
        manager.consume(grant.token, "send_message", parameters)
        calls = [call.args for call in self.audit.call_args_list]
        self.assertIn(
            ("request", "presented", "send_message"),
            [args[:3] for args in calls],
        )
        self.assertIn(
            ("request", "approved", "send_message"),
            [args[:3] for args in calls],
        )
        self.assertIn(
            ("consume", "consumed", "send_message"),
            [args[:3] for args in calls],
        )
        rendered_calls = repr(self.audit.call_args_list)
        self.assertNotIn("private", rendered_calls)
        self.assertNotIn(grant.token, rendered_calls)


if __name__ == "__main__":
    unittest.main()
