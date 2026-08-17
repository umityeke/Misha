from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QTextEdit, QTimeEdit,
)

from core.pin_dialog import PinDialog
from ui import (
    AccessibilitySettingsDialog,
    FileDropZone,
    MishaUI,
    ModelProviderSettingsDialog,
    ProactiveSettingsDialog,
    SettingsCenterDialog,
    SetupOverlay,
)
from ui import C


class UIAcceptanceTests(unittest.TestCase):
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
        self.get_patch = patch(
            "memory.config_manager.get_config", side_effect=lambda key: self.config.get(key)
        )
        self.set_patch = patch("memory.config_manager.set_config", return_value=True)
        self.launch_patch = patch(
            "core.desktop_lifecycle.launch_at_login_enabled", return_value=False
        )
        self.get_patch.start()
        self.set_patch.start()
        self.launch_patch.start()

    def tearDown(self):
        self.launch_patch.stop()
        self.set_patch.stop()
        self.get_patch.stop()

    def test_minimum_window_renders_without_clipping_root(self):
        ui = MishaUI("")
        window = ui._win
        window.resize(window.minimumSize())
        self.app.processEvents()
        frame = window.grab()
        self.assertFalse(frame.isNull())
        self.assertEqual(frame.size(), window.size())
        self.assertGreaterEqual(window.width(), 1040)
        self.assertGreaterEqual(window.height(), 680)
        ui.quit()

    def test_setup_overlay_and_pin_dialog_render_offscreen(self):
        overlay = SetupOverlay()
        overlay.resize(520, 430)
        overlay.show()
        with patch("core.pin_dialog.is_pin_set", return_value=False):
            pin = PinDialog()
        pin.show()
        self.app.processEvents()
        self.assertFalse(overlay.grab().isNull())
        self.assertFalse(pin.grab().isNull())
        self.assertEqual(pin.pin_input.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(pin.pin_input.accessibleName(), "Four digit Misha PIN")
        overlay.close()
        pin.close()

    def test_approval_dialog_defaults_to_deny_and_returns_both_choices(self):
        ui = MishaUI("")
        for choice, expected in (
            (QMessageBox.StandardButton.No, False),
            (QMessageBox.StandardButton.Yes, True),
        ):
            result: list[bool] = []
            with patch("ui.QMessageBox.question", return_value=choice) as question:
                worker = threading.Thread(
                    target=lambda: result.append(ui.ask_approval("Exact safe target")),
                    daemon=True,
                )
                worker.start()
                deadline = time.monotonic() + 2
                while worker.is_alive() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(0.005)
                worker.join(timeout=0.1)
                self.assertEqual(result, [expected])
                self.assertEqual(
                    question.call_args.args[-1], QMessageBox.StandardButton.No
                )
        ui.quit()

    def test_file_drop_selection_emits_exact_regular_file(self):
        zone = FileDropZone()
        selected: list[str] = []
        zone.file_selected.connect(selected.append)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "context.txt"
            target.write_text("safe context", encoding="utf-8")
            zone._set_file(str(target))
            self.app.processEvents()
            self.assertEqual(selected, [str(target)])
            self.assertEqual(zone.current_file(), str(target))
        zone.close()

    def test_interactive_accessibility_tree_has_names_and_keyboard_focus(self):
        ui = MishaUI("")
        controls = [
            *ui._win.findChildren(QPushButton),
            *ui._win.findChildren(QLineEdit),
        ]
        self.assertGreater(len(controls), 10)
        for control in controls:
            with self.subTest(control=control.objectName() or control.text()):
                self.assertTrue(control.accessibleName().strip())
                self.assertEqual(control.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        ui.quit()

    def test_font_scaling_reduce_motion_and_focus_ring_are_applied(self):
        self.config["font_scale"] = "1.3"
        self.config["reduce_motion"] = "1"
        ui = MishaUI("")
        self.assertEqual(self.app.property("misha_font_scale"), 1.3)
        self.assertTrue(self.app.property("misha_reduce_motion"))
        self.assertGreaterEqual(self.app.font().pointSize(), 13)
        self.assertFalse(ui._win.hud._tmr.isActive())
        self.assertFalse(ui._win._drop_zone._anim_tmr.isActive())
        self.assertIn("QPushButton:focus", self.app.styleSheet())
        ui.quit()

    def test_accessibility_settings_dialog_returns_bounded_preferences(self):
        dialog = AccessibilitySettingsDialog(1.3, True)
        self.assertEqual(dialog.values(), (1.3, True))
        dialog.scale.setCurrentIndex(dialog.scale.count() - 1)
        dialog.reduce_motion.setChecked(False)
        self.assertEqual(dialog.values(), (1.5, False))
        self.assertTrue(dialog.scale.accessibleName())
        dialog.close()

    def test_model_settings_are_local_explicit_and_bounded(self):
        dialog = ModelProviderSettingsDialog("qwen3-coder:30b", ["fallback:latest"], 8192)
        self.assertEqual(
            dialog.values(), ("qwen3-coder:30b", ["fallback:latest"], 8192)
        )
        self.assertTrue(dialog.model.accessibleName())
        dialog.close()

    def test_settings_center_exposes_all_required_safe_categories(self):
        dialog = SettingsCenterDialog({
            "always_on_top": True,
            "launch_at_login": False,
            "hands_free": True,
            "voice_sensitivity": "high",
            "screen_observation": False,
            "ide_context": False,
            "ui_language": "tr",
            "response_language": "auto",
            "debug_logging": False,
        })
        values = dialog.values()
        self.assertTrue(values["always_on_top"])
        self.assertTrue(values["hands_free"])
        self.assertEqual(values["voice_sensitivity"], "high")
        self.assertEqual(values["ui_language"], "tr")
        self.assertEqual(values["response_language"], "auto")
        self.assertFalse(values["screen_observation"])
        self.assertFalse(values["ide_context"])
        self.assertTrue(values["safe_mode"])
        self.assertFalse(dialog.safe_mode.isEnabled())
        self.assertEqual(
            [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())],
            ["General", "Voice", "Integrations", "Privacy", "Language", "Advanced / Debug"],
        )
        labels = {button.text() for button in dialog.findChildren(QPushButton)}
        self.assertIn("Manage encrypted memory", labels)
        self.assertIn("Review operating-system permissions", labels)
        self.assertIn("View redacted security audit", labels)
        self.assertIn("Open owner voice and device diagnostics", labels)
        dialog.close()

    def test_key_palette_contrast_and_non_color_state_labels(self):
        def luminance(hex_color: str) -> float:
            values = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def ratio(first: str, second: str) -> float:
            high, low = sorted((luminance(first), luminance(second)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        self.assertGreaterEqual(ratio(C.TEXT, C.BG), 4.5)
        self.assertGreaterEqual(ratio(C.WHITE, C.PANEL), 4.5)
        ui = MishaUI("")
        for state in ("LISTENING", "MUTED", "AWAITING_APPROVAL", "VERIFYING"):
            ui.set_state(state)
            self.app.processEvents()
            self.assertIn(state, ui._win._header_state.text())
            self.assertTrue(ui._win._hero_title.text())
        ui.quit()

    def test_verified_wake_has_distinct_audio_and_visual_acknowledgement(self):
        ui = MishaUI("")
        with patch.object(QApplication, "beep") as beep:
            ui.notify_wake_detected()
            self.app.processEvents()
            beep.assert_called_once_with()
        self.assertEqual(ui._win.hud.state, "WAKE_DETECTED")
        self.assertIn("WAKE_DETECTED", ui._win._header_state.text())
        self.assertEqual(ui._win._hero_title.text(), "I heard you")
        pulses = ui._win.hud._pulses
        self.assertEqual(len(pulses), 3)
        self.assertEqual([round(pulses[index + 1] - pulses[index]) for index in range(2)], [14, 14])
        self.assertLessEqual(pulses[0], 4.0)
        ui.quit()

    def test_all_auxiliary_dialog_controls_are_keyboard_and_screen_reader_ready(self):
        from core.proactive_policy import ProactiveSettings

        ui = MishaUI("")
        dialogs = [
            AccessibilitySettingsDialog(1.0, False),
            ModelProviderSettingsDialog("qwen3-coder:30b", [], 8192),
            ProactiveSettingsDialog(ProactiveSettings.validated(), ()),
            SettingsCenterDialog({"hands_free": True, "voice_sensitivity": "normal"}),
        ]
        control_types = (
            QPushButton, QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox,
            QTimeEdit, QCheckBox,
        )
        for dialog in dialogs:
            dialog.show()
            self.app.processEvents()
            controls = [
                control for control in dialog.findChildren(control_types)
                if control.isVisible()
            ]
            self.assertTrue(controls)
            for control in controls:
                with self.subTest(dialog=dialog.windowTitle(), control=control.__class__.__name__):
                    self.assertTrue(control.accessibleName().strip())
                    self.assertEqual(control.focusPolicy(), Qt.FocusPolicy.StrongFocus)
            dialog.close()
        ui.quit()


if __name__ == "__main__":
    unittest.main()
