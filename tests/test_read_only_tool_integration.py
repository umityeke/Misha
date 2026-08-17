import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import developer_tools, screen_processor, weather_report, web_search
from agent.executor import _call_tool
from agent.tool_registry import RiskLevel, TOOL_REGISTRY


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self._raw


class ReadOnlyToolIntegrationTests(unittest.TestCase):
    def test_every_registry_read_only_tool_has_a_safe_fixture_integration(self):
        cases = {
            "respond": self._respond,
            "web_search": self._web_search,
            "screen_process": self._screen_process,
            "weather_report": self._weather,
            "developer_tools": self._developer_search,
        }
        registered = {
            name for name, spec in TOOL_REGISTRY.items()
            if spec.risk is RiskLevel.READ_ONLY
        }
        self.assertEqual(set(cases), registered)
        for name, integration in cases.items():
            with self.subTest(tool=name):
                output = integration()
                self.assertTrue(output)

    @staticmethod
    def _respond():
        return _call_tool("respond", {"message": "fixture response"}, None)

    @staticmethod
    def _web_search():
        fixture = [{"title": "Docs", "snippet": "Safe fixture", "url": "https://example.com"}]
        with patch.object(web_search, "_ddg_search", return_value=fixture):
            return _call_tool("web_search", {"query": "fixture"}, None)

    @staticmethod
    def _screen_process():
        with patch.object(screen_processor, "_active_window_text", return_value="Editor text"), patch.object(
            screen_processor, "generate_text", return_value="Local analysis"
        ):
            return _call_tool("screen_process", {"text": "Summarize", "angle": "screen"}, None)

    @staticmethod
    def _weather():
        payload = {
            "current_condition": [{
                "temp_C": "20",
                "FeelsLikeC": "20",
                "humidity": "40",
                "weatherDesc": [{"value": "Sunny"}],
            }]
        }
        with patch.object(weather_report, "urlopen", return_value=_Response(payload)):
            return _call_tool("weather_report", {"city": "Istanbul"}, None)

    @staticmethod
    def _developer_search():
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "main.py").write_text("# fixture needle\n", encoding="utf-8")
            with patch.object(developer_tools, "_allowed_roots", return_value=[workspace]):
                return _call_tool(
                    "developer_tools",
                    {"action": "search", "workspace": str(workspace), "query": "needle"},
                    None,
                )


if __name__ == "__main__":
    unittest.main()
