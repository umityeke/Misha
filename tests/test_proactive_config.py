import unittest
from unittest.mock import patch

from core.proactive_policy import ProactiveSettings
from memory.config_manager import (
    get_proactive_settings,
    proactive_budget_available,
    record_proactive_notification,
    save_proactive_settings,
)


class ProactiveConfigTests(unittest.TestCase):
    def test_settings_round_trip_uses_validated_json(self):
        storage = {}
        with (
            patch("memory.config_manager.set_config", side_effect=storage.__setitem__),
            patch("memory.config_manager.get_config", side_effect=storage.get),
        ):
            save_proactive_settings(ProactiveSettings.validated(
                quiet_hours_enabled=False,
                quiet_start="23:30",
                quiet_end="07:15",
                daily_limit=9,
                minimum_priority="critical",
            ))
            loaded = get_proactive_settings()
        self.assertFalse(loaded.quiet_hours_enabled)
        self.assertEqual(loaded.quiet_start, "23:30")
        self.assertEqual(loaded.quiet_end, "07:15")
        self.assertEqual(loaded.daily_limit, 9)
        self.assertEqual(loaded.minimum_priority, "critical")

    def test_invalid_settings_fail_to_private_defaults(self):
        with patch("memory.config_manager.get_config", return_value="not-json"):
            loaded = get_proactive_settings()
        self.assertTrue(loaded.quiet_hours_enabled)
        self.assertEqual(loaded.quiet_start, "22:00")
        self.assertEqual(loaded.daily_limit, 6)

    def test_daily_budget_survives_service_recreation(self):
        storage = {}
        with (
            patch("memory.config_manager.set_config", side_effect=storage.__setitem__),
            patch("memory.config_manager.get_config", side_effect=storage.get),
        ):
            self.assertTrue(proactive_budget_available("2026-08-16", 2))
            self.assertEqual(record_proactive_notification("2026-08-16"), 1)
            self.assertTrue(proactive_budget_available("2026-08-16", 2))
            self.assertEqual(record_proactive_notification("2026-08-16"), 2)
            self.assertFalse(proactive_budget_available("2026-08-16", 2))
            self.assertTrue(proactive_budget_available("2026-08-17", 2))


if __name__ == "__main__":
    unittest.main()
