import unittest
from pathlib import Path


class LegacyCredentialHelperTests(unittest.TestCase):
    def test_legacy_credential_and_account_helpers_are_absent(self):
        retired = {
            "ask_db_url.py",
            "ask_tokens.py",
            "gh_auth_wait.py",
            "gh_device_login.py",
            "read_tokens.py",
        }
        self.assertEqual([name for name in sorted(retired) if Path(name).exists()], [])

    def test_one_off_chat_browser_helpers_are_absent(self):
        retired = {
            "cdp_chatgpt.py",
            "chat_round2.py",
            "chat_round3.py",
            "chat_round4.py",
            "fix_chatgpt.py",
            "pw_screenshot.py",
            "read_chatgpt.py",
            "send_to_chatgpt.py",
            "talk_to_cpt.py",
            "test_ide_context.py",
        }
        self.assertEqual([name for name in sorted(retired) if Path(name).exists()], [])


if __name__ == "__main__":
    unittest.main()
