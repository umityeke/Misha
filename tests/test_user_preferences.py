from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.executor import _normalize_tool_output
from core.user_preferences import personalize_address, preferred_address


class UserPreferenceTests(unittest.TestCase):
    def test_default_output_removes_fixed_sir_without_broken_punctuation(self):
        self.assertEqual(personalize_address("All done, sir.", ""), "All done.")
        self.assertEqual(personalize_address("Sir, the city is missing.", ""), "the city is missing.")

    def test_configured_address_replaces_legacy_honorific(self):
        self.assertEqual(personalize_address("All done, sir.", "Ümit"), "All done, Ümit.")
        with patch("memory.config_manager.get_config", return_value=" Ümit Yeke "):
            self.assertEqual(preferred_address(), "Ümit Yeke")

    def test_invalid_address_fails_to_neutral_and_tool_output_uses_boundary(self):
        self.assertEqual(personalize_address("Hello, sir.", "bad\x1bvalue"), "Hello.")
        with patch("core.user_preferences.preferred_address", return_value=""):
            self.assertEqual(_normalize_tool_output("respond", "Ready, sir."), "Ready.")


if __name__ == "__main__":
    unittest.main()
