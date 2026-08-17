from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from main import ide_context_opted_in
from ui import PrivacyOnboardingDialog


class OnboardingOptInTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_screen_and_ide_choices_default_off_and_are_independent(self):
        dialog = PrivacyOnboardingDialog()
        self.assertEqual(dialog.opt_in_values(), (False, False))
        dialog.ide_opt_in.setChecked(True)
        self.assertEqual(dialog.opt_in_values(), (False, True))
        self.assertTrue(dialog.screen_opt_in.accessibleName())
        self.assertTrue(dialog.ide_opt_in.accessibleName())
        dialog.close()

    def test_ide_server_config_gate_defaults_off_and_accepts_explicit_opt_in(self):
        for value, expected in ((None, False), ("0", False), ("1", True), ("true", True)):
            with self.subTest(value=value), patch(
                "memory.config_manager.get_config", return_value=value
            ):
                self.assertEqual(ide_context_opted_in(), expected)


if __name__ == "__main__":
    unittest.main()
