import json
import unittest
from unittest.mock import MagicMock, patch

from actions import weather_report


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self._raw


class WeatherToolTests(unittest.TestCase):
    def test_today_weather_is_read_only_and_does_not_open_a_browser(self):
        payload = {
            "current_condition": [{
                "temp_C": "18",
                "FeelsLikeC": "17",
                "humidity": "55",
                "weatherDesc": [{"value": "Clear"}],
            }]
        }
        with patch.object(
            weather_report, "urlopen", return_value=_Response(payload)
        ) as open_url:
            result = weather_report.weather_action({"city": "İstanbul", "time": "today"})
        self.assertIn("Clear, 18°C", result)
        request = open_url.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertTrue(request.full_url.startswith("https://wttr.in/"))
        self.assertNotIn("İstanbul", request.full_url)

    def test_tomorrow_forecast_and_session_memory(self):
        payload = {
            "weather": [
                {},
                {
                    "mintempC": "9",
                    "maxtempC": "16",
                    "hourly": [{"weatherDesc": [{"value": "Rain"}]}],
                },
            ]
        }
        memory = MagicMock()
        with patch.object(weather_report, "urlopen", return_value=_Response(payload)):
            result = weather_report.weather_action(
                {"city": "Ankara", "time": "tomorrow"}, session_memory=memory
            )
        self.assertEqual(result, "Tomorrow in Ankara: Rain, 9–16°C.")
        memory.set_last_search.assert_called_once()

    def test_invalid_or_failed_requests_do_not_leak_exception_details(self):
        with patch.object(weather_report, "urlopen", side_effect=OSError("private path")):
            failed = weather_report.weather_action({"city": "Izmir"})
        self.assertEqual(failed, "Weather data is temporarily unavailable.")
        invalid = weather_report.weather_action({"city": "bad\ncity"})
        self.assertIn("invalid", invalid)


if __name__ == "__main__":
    unittest.main()
