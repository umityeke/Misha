import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.desktop_lifecycle import (
    LAUNCH_AGENT_LABEL,
    launch_agent_path,
    set_launch_at_login,
)


class DesktopLifecycleTests(unittest.TestCase):
    def test_launch_agent_is_user_scoped_atomic_and_shell_free(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.desktop_lifecycle.sys.platform", "darwin"
        ):
            home = Path(temp_dir)
            executable = home / "Misha.app" / "Contents" / "MacOS" / "Misha"
            active = set_launch_at_login(True, home=home, command=[str(executable)])
            target = launch_agent_path(home)
            self.assertTrue(active)
            self.assertTrue(target.is_file())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with target.open("rb") as handle:
                payload = plistlib.load(handle)
            self.assertEqual(payload["Label"], LAUNCH_AGENT_LABEL)
            self.assertEqual(payload["ProgramArguments"], [str(executable)])
            self.assertTrue(payload["RunAtLoad"])
            self.assertNotIn("Program", payload)

    def test_disabling_only_removes_misha_launch_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.desktop_lifecycle.sys.platform", "darwin"
        ):
            home = Path(temp_dir)
            target = launch_agent_path(home)
            target.parent.mkdir(parents=True)
            target.write_text("owned by Misha", encoding="utf-8")
            neighbor = target.with_name("com.example.keep.plist")
            neighbor.write_text("keep", encoding="utf-8")
            self.assertFalse(set_launch_at_login(False, home=home))
            self.assertFalse(target.exists())
            self.assertTrue(neighbor.exists())

    def test_non_macos_fails_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.desktop_lifecycle.sys.platform", "linux"
        ):
            home = Path(temp_dir)
            self.assertFalse(set_launch_at_login(True, home=home, command=["/bin/true"]))
            self.assertFalse(launch_agent_path(home).exists())

    def test_relative_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.desktop_lifecycle.sys.platform", "darwin"
        ):
            with self.assertRaises(ValueError):
                set_launch_at_login(True, home=Path(temp_dir), command=["Misha"])


if __name__ == "__main__":
    unittest.main()
