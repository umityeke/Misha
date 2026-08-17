import unittest
from unittest.mock import patch

from core import macos_permissions


class MacOSPermissionsTests(unittest.TestCase):
    def test_authorization_status_values_are_normalized(self):
        self.assertEqual(macos_permissions._status_name(0), "not_requested")
        self.assertEqual(macos_permissions._status_name(3), "granted")
        self.assertEqual(macos_permissions._status_name(99), "unknown")

    def test_non_macos_status_is_explicitly_not_applicable(self):
        with patch.object(macos_permissions.sys, "platform", "linux"):
            statuses = macos_permissions.get_permission_statuses()
        self.assertEqual(len(statuses), 4)
        self.assertTrue(all(item.status == "not_applicable" for item in statuses))

    def test_unknown_permission_never_opens_anything(self):
        with (
            patch.object(macos_permissions.sys, "platform", "darwin"),
            patch.object(macos_permissions.subprocess, "run") as run,
        ):
            self.assertFalse(macos_permissions.open_permission_settings("unknown"))
        run.assert_not_called()

    def test_known_permission_opens_only_allowlisted_route(self):
        with (
            patch.object(macos_permissions.sys, "platform", "darwin"),
            patch.object(macos_permissions.subprocess, "run") as run,
        ):
            self.assertTrue(macos_permissions.open_permission_settings("accessibility"))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "open")
        self.assertEqual(
            command[1],
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        )

    def test_settings_open_failure_is_fail_soft(self):
        with (
            patch.object(macos_permissions.sys, "platform", "darwin"),
            patch.object(
                macos_permissions.subprocess, "run", side_effect=OSError("unavailable")
            ),
        ):
            self.assertFalse(macos_permissions.open_permission_settings("microphone"))


if __name__ == "__main__":
    unittest.main()
