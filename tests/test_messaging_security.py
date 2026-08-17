import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from actions import send_message as messaging
from agent.verifier import VerificationStatus, verify_tool_result
from core import outbound_guard
from core.action_policy import approval_reason


class MessagingSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MISHA_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_platform_resolution_is_exact_and_allowlisted(self):
        self.assertEqual(messaging._platform("WhatsApp"), ("whatsapp", "WhatsApp"))
        with self.assertRaises(ValueError):
            messaging._platform("whatsapp-and-run-something")
        with self.assertRaises(ValueError):
            messaging._platform("unknown")

    def test_recipient_and_message_are_bounded(self):
        self.assertEqual(messaging._receiver("  Ada   Lovelace "), "Ada Lovelace")
        for receiver in ("", "x\nmalicious", "x" * 101):
            with self.subTest(receiver=receiver), self.assertRaises(ValueError):
                messaging._receiver(receiver)
        with self.assertRaises(ValueError):
            messaging._message("x" * 4_001)

    def test_preview_is_side_effect_free_and_does_not_require_approval(self):
        params = {
            "action": "preview", "platform": "Telegram", "receiver": "Ada",
            "message_text": "Hello",
        }
        with patch.object(messaging, "reserve") as reserve:
            result = messaging.send_message(params)
        self.assertIn("not sent", result)
        self.assertIn("Recipient: Ada", result)
        reserve.assert_not_called()
        self.assertIsNone(approval_reason("send_message", params))

    def test_send_requires_exact_recipient_before_and_after_typing(self):
        fake_ui = MagicMock()
        params = {"platform": "WhatsApp", "receiver": "Ada", "message_text": "Hello"}
        with patch.object(messaging, "pyautogui", fake_ui), patch.object(
            messaging, "_PYAUTOGUI", True
        ), patch.object(messaging, "reserve", return_value=(True, "fingerprint")), patch.object(
            messaging, "_select_exact_recipient", return_value=True
        ), patch.object(messaging, "_active_recipient_matches", return_value=True), patch.object(
            messaging, "_paste"
        ) as paste, patch.object(messaging, "finish") as finish:
            result = messaging.send_message(params)
        paste.assert_called_once_with("Hello")
        fake_ui.press.assert_called_once_with("enter")
        finish.assert_called_once_with("fingerprint", "sent_unverified")
        self.assertIn("remote delivery is unverified", result)
        verification = verify_tool_result("send_message", params, result)
        self.assertEqual(verification.status, VerificationStatus.UNVERIFIED)

    def test_recipient_mismatch_blocks_before_message_is_typed(self):
        params = {"platform": "Telegram", "receiver": "Ada", "message_text": "private"}
        with patch.object(messaging, "reserve", return_value=(True, "fingerprint")), patch.object(
            messaging, "_select_exact_recipient", return_value=False
        ), patch.object(messaging, "_paste") as paste, patch.object(messaging, "finish") as finish:
            result = messaging.send_message(params)
        self.assertIn("blocked", result.lower())
        paste.assert_not_called()
        finish.assert_called_once_with("fingerprint", "blocked")

    def test_macos_ax_match_requires_expected_app_and_exact_title(self):
        observed = "Aktif Uygulama: WhatsApp\n- [AXStaticText] Title: 'Ada'"
        with patch.object(messaging, "_get_os", return_value="mac"), patch(
            "core.macos_observe.get_active_window_text", return_value=observed
        ):
            self.assertTrue(messaging._active_recipient_matches("WhatsApp", "Ada"))
            self.assertFalse(messaging._active_recipient_matches("WhatsApp", "Ad"))
            self.assertFalse(messaging._active_recipient_matches("Telegram", "Ada"))

    def test_duplicate_guard_stores_only_hashes_and_blocks_five_minutes(self):
        first, fingerprint = outbound_guard.reserve("whatsapp", "Ada", "private message")
        second, same = outbound_guard.reserve("whatsapp", "Ada", "private message")
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(fingerprint, same)
        db = Path(self.temp.name) / "outbound_messages.db"
        self.assertNotIn(b"private message", db.read_bytes())
        self.assertEqual(db.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
