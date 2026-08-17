import unittest

from core.security import is_command_risky, request_approval, validate_command


class CommandSecurityTests(unittest.TestCase):
    def test_all_non_empty_shell_commands_require_approval(self):
        for command in ("pwd", "git status", " echo ok; rm -rf /tmp/example"):
            self.assertTrue(is_command_risky(command))

    def test_empty_and_nul_commands_are_rejected(self):
        self.assertFalse(validate_command("")[0])
        self.assertFalse(validate_command("echo ok\x00rm -rf /tmp/example")[0])

    def test_approval_callback_controls_execution(self):
        self.assertFalse(request_approval("pwd", lambda _: False))
        self.assertTrue(request_approval("pwd", lambda _: True))


if __name__ == "__main__":
    unittest.main()
