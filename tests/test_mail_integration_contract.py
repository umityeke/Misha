import tempfile
import unittest
from pathlib import Path

from core.integrations.mail import (
    MailMessage,
    MailService,
    MailSubmission,
    sensitive_content_warning,
    submission_fingerprint,
)


class _MailProvider:
    def __init__(self):
        self.messages = []
        self.receipt = MailSubmission(True, "receipt-1")

    def inbox(self, limit):
        return self.messages[:limit]

    def search(self, query, limit):
        return [message for message in self.messages if query.lower() in message.subject.lower()][:limit]

    def thread(self, thread_id):
        return [message for message in self.messages if message.thread_id == thread_id]

    def create_draft(self, message):
        return MailMessage(**{**message.__dict__, "message_id": "draft-1"})

    def send(self, message):
        return self.receipt


class MailIntegrationContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.provider = _MailProvider()
        self.service = MailService(self.provider, allowed_roots=(self.root,))

    def tearDown(self):
        self.temp.cleanup()

    def message(self, **changes):
        values = {
            "message_id": "message-1",
            "thread_id": "thread-1",
            "sender": "sender@example.com",
            "recipients": ("owner@example.com",),
            "subject": "Project update",
            "body": "The build passed all tests.",
            "attachments": (),
        }
        values.update(changes)
        return MailMessage(**values)

    def test_inbox_search_summary_draft_and_reply_contract(self):
        original = self.message()
        self.provider.messages.append(original)
        self.assertEqual(self.service.inbox(), [original])
        self.assertEqual(self.service.search("project"), [original])
        self.assertIn("build passed", self.service.summarize(original))
        self.assertEqual(self.service.draft(original).message_id, "draft-1")
        reply = self.service.reply_draft(original, "Thanks")
        self.assertEqual(reply.thread_id, "thread-1")
        self.assertEqual(reply.recipients, ("sender@example.com",))

    def test_attachment_and_sensitive_content_safety(self):
        safe = self.root / "report.txt"
        safe.write_text("report", encoding="utf-8")
        self.assertEqual(self.service.draft(self.message(attachments=(safe,))).attachments, (safe,))
        blocked = self.root / "payload.ps1"
        blocked.write_text("unsafe", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "blocked"):
            self.service.draft(self.message(attachments=(blocked,)))
        self.assertIsNotNone(sensitive_content_warning(self.message(body="My password is x")))

    def test_send_requires_exact_final_approval_and_provider_receipt(self):
        message = self.message()
        with self.assertRaises(PermissionError):
            self.service.send(message, approved_fingerprint="wrong")
        approved = submission_fingerprint(message)
        self.assertEqual(self.service.send(message, approved_fingerprint=approved).receipt_id, "receipt-1")
        self.provider.receipt = MailSubmission(True, "")
        self.assertFalse(self.service.send(message, approved_fingerprint=approved).accepted)
        sensitive = self.message(body="The API key is private")
        with self.assertRaisesRegex(PermissionError, "Sensitive"):
            self.service.send(sensitive, approved_fingerprint=submission_fingerprint(sensitive))


if __name__ == "__main__":
    unittest.main()
