import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from actions import computer_control, computer_settings, desktop, open_app, terminal_control
from core.system_capabilities import capability_matrix, format_capabilities
from core.ui_automation import enforce_pyautogui_safety, safe_window_title


class SystemToolSecurityTests(unittest.TestCase):
    def test_pyautogui_failsafe_is_non_optional(self):
        fake = MagicMock()
        fake.PAUSE = 0
        fake.FAILSAFE = False
        enforce_pyautogui_safety(fake)
        self.assertTrue(fake.FAILSAFE)
        self.assertGreaterEqual(fake.PAUSE, 0.05)

    def test_window_titles_reject_script_injection(self):
        self.assertEqual(safe_window_title("Visual Studio Code"), "Visual Studio Code")
        for title in ('x" & do shell script "id', "x'; rm -rf", "$(touch /tmp/x)"):
            with self.subTest(title=title), self.assertRaises(ValueError):
                safe_window_title(title)
        with patch.object(computer_control.subprocess, "run") as run:
            result = computer_control._focus_window('x" & do shell script "id')
        self.assertIn("blocked", result)
        run.assert_not_called()

    def test_screenshot_destination_is_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            desktop_dir = home / "Desktop"
            pictures_dir = home / "Pictures"
            desktop_dir.mkdir()
            pictures_dir.mkdir()
            with patch.object(computer_control, "_SAFE_SCREENSHOT_ROOTS", (desktop_dir, pictures_dir)), patch.object(
                computer_control.Path, "home", return_value=home
            ):
                self.assertEqual(
                    computer_control._safe_screenshot_path(str(pictures_dir / "safe.png")),
                    (pictures_dir / "safe.png").resolve(),
                )
                self.assertEqual(
                    computer_control._safe_screenshot_path(str(home / "private.png")),
                    desktop_dir / "misha_screenshot.png",
                )

    def test_capability_matrix_is_explicit_per_platform(self):
        with patch("core.system_capabilities.shutil.which", return_value="/usr/bin/tool"):
            matrix = capability_matrix("Darwin", pyautogui_available=True)
        self.assertEqual(set(matrix), {
            "app_open", "window_control", "volume", "brightness", "media", "screenshot", "power",
        })
        self.assertTrue(all(item.available for item in matrix.values()))
        self.assertIn("System capabilities (Darwin)", format_capabilities("Darwin"))

    def test_settings_capabilities_work_without_pyautogui(self):
        with patch.object(computer_settings, "_PYAUTOGUI", False):
            result = computer_settings.computer_settings({"action": "capabilities"})
        self.assertIn("System capabilities", result)

    def test_power_actions_require_exact_second_confirmation(self):
        with patch.object(computer_settings, "shutdown_computer") as shutdown, patch.dict(
            computer_settings.ACTION_MAP, {"shutdown": shutdown}
        ):
            rejected = computer_settings.computer_settings({"action": "shutdown", "confirmed": "yes"})
            self.assertIn("CONFIRM SHUTDOWN", rejected)
            shutdown.assert_not_called()
            accepted = computer_settings.computer_settings({
                "action": "shutdown", "confirmed": "CONFIRM SHUTDOWN",
            })
            self.assertEqual(accepted, "Done: shutdown.")
            shutdown.assert_called_once()

    def test_windows_app_launch_uses_argv_without_shell(self):
        process = MagicMock()
        with patch.object(open_app.shutil, "which", return_value="C:/Apps/tool.exe"), patch.object(
            open_app.subprocess, "Popen", return_value=process
        ) as popen, patch.object(open_app.time, "sleep"):
            self.assertTrue(open_app._launch_windows("tool --safe"))
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["C:/Apps/tool.exe", "--safe"])
        self.assertNotIn("shell", kwargs)

    def test_no_action_module_enables_shell_true(self):
        actions_dir = Path(__file__).resolve().parents[1] / "actions"
        offenders = []
        for path in actions_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                        offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_legacy_generated_code_and_terminal_are_fail_closed(self):
        self.assertIn("disabled", desktop._execute_generated_code("print('unsafe')"))
        result = terminal_control.terminal_control({"command": "echo unsafe"})
        self.assertIn("disabled", result)

    def test_wallpaper_url_is_fail_closed_and_macos_path_is_argv(self):
        self.assertIn("disabled", desktop.set_wallpaper_from_url("http://127.0.0.1/private"))
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'quote"name.png'
            image.write_bytes(b"png")
            completed = MagicMock(returncode=0)
            with patch.object(desktop, "_OS", "Darwin"), patch.object(
                desktop.subprocess, "run", return_value=completed
            ) as run:
                result = desktop.set_wallpaper(str(image))
        self.assertIn("Wallpaper set", result)
        argv = run.call_args.args[0]
        self.assertEqual(argv[-1], str(image.resolve()))
        self.assertNotIn(str(image.resolve()), argv[-2])


if __name__ == "__main__":
    unittest.main()
