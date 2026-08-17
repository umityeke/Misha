from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from core.localization import (
    localized_datetime,
    response_language_instruction,
    safe_error_message,
    translate,
)


class LocalizationTests(unittest.TestCase):
    def test_turkish_and_english_catalog(self):
        self.assertEqual(translate("settings_saved", language="tr"), "Ayarlar kaydedildi.")
        self.assertEqual(translate("settings_saved", language="en"), "Settings saved.")

    def test_response_language_is_validated_and_injected(self):
        with patch("core.localization.get_config", return_value="tr"):
            self.assertIn("Turkish", response_language_instruction())
        with patch("core.localization.get_config", return_value="unexpected"):
            self.assertIn("language used by the owner", response_language_instruction())

    def test_locale_datetime_and_error_contract(self):
        value = datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc)
        self.assertTrue(localized_datetime(value, language="tr").startswith("17.08.2026"))
        self.assertTrue(localized_datetime(value, language="en").startswith("2026-08-17"))
        with patch("core.localization.get_config", return_value="en"):
            self.assertEqual(
                safe_error_message("provider timeout"),
                "The operation could not be completed safely. [provider_timeout]",
            )


if __name__ == "__main__":
    unittest.main()
