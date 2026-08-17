import unittest
from datetime import datetime

from core.proactive_policy import ProactiveSettings, normalize_priority


class ProactivePolicyTests(unittest.TestCase):
    def test_overnight_quiet_hours_wrap_midnight(self):
        settings = ProactiveSettings.validated(
            quiet_hours_enabled=True, quiet_start="22:00", quiet_end="08:00"
        )
        self.assertTrue(settings.is_quiet_time(datetime(2026, 8, 16, 23, 30)))
        self.assertTrue(settings.is_quiet_time(datetime(2026, 8, 17, 7, 59)))
        self.assertFalse(settings.is_quiet_time(datetime(2026, 8, 17, 8, 0)))

    def test_daytime_quiet_window_is_supported(self):
        settings = ProactiveSettings.validated(
            quiet_start="12:00", quiet_end="13:00"
        )
        self.assertTrue(settings.is_quiet_time(datetime(2026, 8, 16, 12, 30)))
        self.assertFalse(settings.is_quiet_time(datetime(2026, 8, 16, 13, 0)))

    def test_priority_floor_is_deterministic(self):
        settings = ProactiveSettings.validated(minimum_priority="normal")
        self.assertFalse(settings.permits_priority("low"))
        self.assertTrue(settings.permits_priority("normal"))
        self.assertTrue(settings.permits_priority("critical"))

    def test_invalid_settings_fall_back_and_limits_are_bounded(self):
        low = ProactiveSettings.validated(
            quiet_start="bad", quiet_end="bad", daily_limit=-10,
            minimum_priority="invented",
        )
        high = ProactiveSettings.validated(daily_limit=500)
        self.assertEqual((low.quiet_start, low.quiet_end), ("22:00", "08:00"))
        self.assertEqual(low.daily_limit, 1)
        self.assertEqual(high.daily_limit, 50)
        self.assertEqual(normalize_priority("invented"), "normal")


if __name__ == "__main__":
    unittest.main()
