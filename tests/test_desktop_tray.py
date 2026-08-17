import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui import MishaUI
from core.task_journal import TaskSnapshot


class DesktopTrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config = {
            "ai_provider": "ollama",
            "os_system": "darwin",
            "privacy_onboarding_completed": "1",
            "always_on_top": "1",
        }
        get_config = lambda key: self.config.get(key)
        self.get_patch = patch("memory.config_manager.get_config", side_effect=get_config)
        self.set_patch = patch("memory.config_manager.set_config", return_value=True)
        self.launch_patch = patch("core.desktop_lifecycle.launch_at_login_enabled", return_value=False)
        self.get_patch.start()
        self.set_config = self.set_patch.start()
        self.launch_patch.start()
        self.ui = MishaUI("")
        self.app.processEvents()

    def tearDown(self):
        self.ui.quit()
        self.app.processEvents()
        self.launch_patch.stop()
        self.set_patch.stop()
        self.get_patch.stop()

    def test_tray_exposes_complete_desktop_controls(self):
        self.assertEqual(
            set(self.ui._tray_actions),
            {"show", "mute", "wake", "always_on_top", "startup", "quit"},
        )
        self.assertFalse(self.app.quitOnLastWindowClosed())

    def test_window_close_hides_until_explicit_quit(self):
        self.assertTrue(self.ui._win.isVisible())
        self.ui._win.close()
        self.app.processEvents()
        self.assertTrue(self.ui._win.isHidden())
        self.assertFalse(self.ui._win._allow_close)

    def test_tray_mute_and_wake_actions_stay_synchronized(self):
        self.ui._win._voice_available = True
        self.ui._set_muted_from_tray(True)
        self.assertTrue(self.ui._win._muted)
        self.assertTrue(self.ui._tray_actions["mute"].isChecked())
        self.assertFalse(self.ui._tray_actions["wake"].isChecked())
        self.ui._set_muted_from_tray(False)
        self.assertFalse(self.ui._win._muted)
        self.assertFalse(self.ui._tray_actions["mute"].isChecked())
        self.assertTrue(self.ui._tray_actions["wake"].isChecked())

    def test_always_on_top_preference_is_persisted(self):
        self.ui._win.set_always_on_top(False)
        self.set_config.assert_any_call("always_on_top", "0")

    def test_runtime_verifying_and_recovering_states_are_visible(self):
        self.ui.set_state("VERIFYING")
        self.app.processEvents()
        self.assertEqual(self.ui._win._hero_title.text(), "Verifying")
        self.ui.set_state("RECOVERING")
        self.app.processEvents()
        self.assertEqual(self.ui._win._hero_title.text(), "Recovering")

    def test_recovery_dialog_is_protected_and_never_executes_task(self):
        from ui import TaskRecoveryDialog

        record = TaskSnapshot(
            request_id="task-1", goal="Review project", phase="interrupted",
            completed_steps=1, total_steps=3, external_effect_seen=True,
            created_at="2026-08-16T10:00:00+00:00",
            updated_at="2026-08-16T10:01:00+00:00",
        )
        dismiss = Mock(return_value=True)
        dialog = TaskRecoveryDialog((record,), dismiss, self.ui._win)
        self.assertIn("Protected", dialog.windowTitle())
        self.assertIn("Nothing was automatically resumed", dialog.note.text())
        dialog.tasks.setCurrentRow(0)
        dialog.dismiss_selected()
        dismiss.assert_called_once_with("task-1")
        self.assertEqual(dialog.tasks.count(), 0)
        dialog.close()

    def test_plan_preview_is_forwarded_to_thread_safe_log(self):
        with patch.object(self.ui, "write_log") as write_log:
            self.ui.show_plan("SYS: Plan ready — 1 step(s), 0 approval-gated.")
        write_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
