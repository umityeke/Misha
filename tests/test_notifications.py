from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from core.notifications import deliver_notification


class NotificationTests(unittest.TestCase):
    def test_macos_uses_argv_and_never_interpolates_content_into_script(self):
        hostile = 'hello " & do shell script "unsafe"'
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch("core.notifications.shutil.which", return_value="/usr/bin/osascript"), patch(
            "core.notifications.subprocess.run", return_value=completed
        ) as run:
            receipt = deliver_notification("Misha", hostile, os_name="Darwin")
        self.assertTrue(receipt.delivered)
        command = run.call_args.args[0]
        self.assertNotIn(hostile, command[2])
        self.assertEqual(command[-1], hostile)
        self.assertFalse(run.call_args.kwargs["check"])

    def test_linux_priority_and_bounds_are_enforced(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch("core.notifications.shutil.which", return_value="/usr/bin/notify-send"), patch(
            "core.notifications.subprocess.run", return_value=completed
        ) as run:
            receipt = deliver_notification(" T " * 100, " M " * 400, priority="critical", os_name="Linux")
        self.assertTrue(receipt.delivered)
        command = run.call_args.args[0]
        self.assertIn("--urgency=critical", command)
        self.assertLessEqual(len(command[-2]), 80)
        self.assertLessEqual(len(command[-1]), 500)

    def test_unavailable_or_invalid_channel_fails_closed(self):
        self.assertFalse(deliver_notification("", "message", os_name="Darwin").delivered)
        with patch("core.notifications.shutil.which", return_value=None), patch(
            "core.notifications.subprocess.run"
        ) as run:
            receipt = deliver_notification("Misha", "message", os_name="Darwin")
        self.assertFalse(receipt.delivered)
        run.assert_not_called()

    def test_windows_text_is_passed_only_as_arguments(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch("core.notifications.shutil.which", return_value="powershell"), patch(
            "core.notifications.subprocess.run", return_value=completed
        ) as run:
            receipt = deliver_notification("<Misha>", "& dangerous", os_name="Windows")
        self.assertTrue(receipt.delivered)
        command = run.call_args.args[0]
        self.assertNotIn("& dangerous", command[5])
        self.assertEqual(command[-2:], ["<Misha>", "& dangerous"])


if __name__ == "__main__":
    unittest.main()
