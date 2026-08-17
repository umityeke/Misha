import unittest
from unittest.mock import patch

from actions import personal_apps as module
from agent.executor import _call_tool
from agent.verifier import VerificationStatus, verify_tool_result
from core.action_policy import approval_reason


class PersonalAppsTests(unittest.TestCase):
    def test_mail_inbox_and_search_are_bounded_read_only_actions(self):
        rows = [{
            "id": "1", "sender": "Ada <ada@example.com>", "subject": "Plan",
            "received_at": "today", "unread": True, "preview": "Safe preview",
        }]
        with patch.object(module, "_run_script", return_value=rows) as run:
            output = _call_tool("personal_apps", {"action": "mail_inbox", "limit": 500}, None)
            self.assertIn("subject=Plan", output)
            self.assertEqual(run.call_args.args[1][1], "100")
        self.assertIsNone(approval_reason("personal_apps", {"action": "mail_inbox"}))
        self.assertIsNone(approval_reason("personal_apps", {"action": "mail_search"}))

    def test_mail_draft_validates_recipient_and_send_requires_specific_approval(self):
        invalid = module.personal_apps({
            "action": "mail_draft", "receiver": "not-an-email", "subject": "x",
        })
        self.assertIn("failed", invalid)
        with patch.object(module, "_run_script", return_value={"id": "draft-1"}):
            output = module.personal_apps({
                "action": "mail_draft", "receiver": "ada@example.com", "subject": "Plan",
            })
        self.assertIn("draft created", output)
        reason = approval_reason("personal_apps", {
            "action": "mail_send", "receiver": "ada@example.com", "subject": "Plan",
        })
        self.assertIn("ada@example.com", reason or "")

    def test_sensitive_mail_is_blocked_without_separate_approval(self):
        output = module.personal_apps({
            "action": "mail_send", "receiver": "ada@example.com", "subject": "API key",
            "body": "secret",
        })
        self.assertIn("separate explicit approval", output)

    def test_reply_draft_is_bound_to_exact_numeric_local_message(self):
        with patch.object(module, "_run_script", return_value={"id": "reply-1"}) as run:
            output = module.personal_apps({
                "action": "mail_reply_draft", "original_message_id": "42", "body": "Thanks",
            })
            self.assertIn("original_message_id=42", output)
            self.assertEqual(run.call_args.args[1][-1], "42")
        invalid = module.personal_apps({
            "action": "mail_reply_draft", "original_message_id": "42 or 1=1", "body": "x",
        })
        self.assertIn("numeric local Mail ID", invalid)
        self.assertIsNotNone(approval_reason(
            "personal_apps", {"action": "mail_reply_draft", "original_message_id": "42"}
        ))

    def test_calendar_read_and_create_use_timezone_aware_exact_target(self):
        with patch.object(module, "_run_script", return_value=[{"id": "cal-1", "name": "Home"}]):
            self.assertIn("name=Home", module.personal_apps({"action": "calendar_list"}))
        with patch.object(
            module, "_run_script", return_value={"id": "event-1", "calendar": "Home"}
        ) as run:
            output = module.personal_apps({
                "action": "calendar_create", "calendar_name": "Home", "title": "Planning",
                "start": "2030-06-10T09:00:00+03:00", "end": "2030-06-10T10:00:00+03:00",
            })
            self.assertIn("id=event-1", output)
            self.assertEqual(run.call_args.args[1][3], "Home")
        self.assertIsNotNone(approval_reason("personal_apps", {"action": "calendar_create"}))

    def test_calendar_update_and_delete_require_exact_event_id(self):
        base = {
            "calendar_name": "Home", "event_id": "event-1", "title": "Updated",
            "start": "2030-06-10T11:00:00+03:00", "end": "2030-06-10T12:00:00+03:00",
        }
        with patch.object(
            module, "_run_script", return_value={"id": "event-1", "calendar": "Home", "updated": True}
        ) as run:
            output = module.personal_apps({"action": "calendar_update", **base})
            self.assertIn("event updated", output)
            self.assertEqual(run.call_args.args[1][-1], "event-1")
        with patch.object(
            module, "_run_script", return_value={"id": "event-1", "deleted": True}
        ):
            output = module.personal_apps({"action": "calendar_delete", "event_id": "event-1"})
            self.assertIn("event deleted", output)
        self.assertIsNotNone(approval_reason(
            "personal_apps", {"action": "calendar_delete", "event_id": "event-1"}
        ))

    def test_verifier_does_not_claim_remote_mail_delivery(self):
        result = verify_tool_result(
            "personal_apps", {"action": "mail_send"},
            "Local Mail accepted the send command; id=1; remote delivery is unverified.",
        )
        self.assertEqual(result.status, VerificationStatus.UNVERIFIED)


if __name__ == "__main__":
    unittest.main()
