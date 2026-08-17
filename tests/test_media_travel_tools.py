from __future__ import annotations

import unittest
from unittest.mock import patch

from actions import flight_finder, youtube_video
from core.action_policy import approval_reason


class YouTubeToolTests(unittest.TestCase):
    def test_url_policy_accepts_only_exact_youtube_hosts(self):
        self.assertTrue(youtube_video._is_valid_youtube_url(
            "https://www.youtube.com/watch?v=abcdefghijk"
        ))
        self.assertTrue(youtube_video._is_valid_youtube_url("https://youtu.be/abcdefghijk"))
        for value in (
            "https://youtube.com.attacker.example/watch?v=abcdefghijk",
            "https://youtube.com@attacker.example/watch?v=abcdefghijk",
            "file://youtube.com/video",
        ):
            with self.subTest(value=value):
                self.assertFalse(youtube_video._is_valid_youtube_url(value))

    def test_summarize_uses_provided_url_without_opening_a_dialog(self):
        with patch.object(youtube_video, "_ask_for_url") as dialog, patch.object(
            youtube_video, "_get_transcript", return_value="safe transcript"
        ), patch.object(youtube_video, "_summarize_locally", return_value="summary"):
            result = youtube_video.youtube_video({
                "action": "summarize",
                "url": "https://youtu.be/abcdefghijk",
            })
        self.assertEqual(result, "summary")
        dialog.assert_not_called()


class FlightToolTests(unittest.TestCase):
    def test_url_encodes_route_text_and_drops_stale_hardcoded_tfs(self):
        url = flight_finder._build_google_flights_url(
            "İstanbul & test", "London", "2026-09-01", passengers=2
        )
        self.assertIn("%26", url)
        self.assertNotIn("tfs=", url)
        self.assertIn("adults=2", url)

    def test_invalid_dates_and_reverse_return_fail_before_browser(self):
        with patch.object(flight_finder, "_search_flights_browser") as search:
            invalid = flight_finder.flight_finder({
                "origin": "Istanbul", "destination": "London", "date": "2026-99-99",
            })
            reversed_trip = flight_finder.flight_finder({
                "origin": "Istanbul", "destination": "London", "date": "2026-09-10",
                "return_date": "2026-09-01",
            })
        self.assertIn("invalid", invalid.casefold())
        self.assertIn("cannot be before", reversed_trip)
        search.assert_not_called()

    def test_media_and_travel_external_effects_require_approval(self):
        self.assertIsNotNone(approval_reason("youtube_video", {"action": "play"}))
        self.assertIsNotNone(approval_reason("flight_finder", {
            "origin": "IST", "destination": "LHR", "date": "2026-09-01",
        }))


if __name__ == "__main__":
    unittest.main()
