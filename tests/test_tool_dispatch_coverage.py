import unittest
from unittest.mock import patch

from agent.executor import _call_tool
from agent.tool_registry import TOOL_REGISTRY


_DISPATCH_TARGETS = {
    "remember_rule": "memory.learning_store.add_rule",
    "open_app": "actions.open_app.open_app",
    "web_search": "actions.web_search.web_search",
    "game_updater": "actions.game_updater.game_updater",
    "browser_control": "actions.browser_control.browser_control",
    "file_controller": "actions.file_controller.file_controller",
    "code_helper": "actions.code_helper.code_helper",
    "developer_tools": "actions.developer_tools.developer_tools",
    "db_manager": "actions.db_manager.db_manager",
    "screen_process": "actions.screen_processor.screen_process",
    "send_message": "actions.send_message.send_message",
    "reminder": "actions.reminder.reminder",
    "personal_apps": "actions.personal_apps.personal_apps",
    "youtube_video": "actions.youtube_video.youtube_video",
    "weather_report": "actions.weather_report.weather_action",
    "computer_settings": "actions.computer_settings.computer_settings",
    "desktop_control": "actions.desktop.desktop_control",
    "computer_control": "actions.computer_control.computer_control",
    "flight_finder": "actions.flight_finder.flight_finder",
}


def _value(value_type):
    return {
        str: "safe-test-value",
        int: 1,
        float: 1.0,
        bool: False,
        list: [],
        dict: {},
    }[value_type]


class ToolDispatchCoverageTests(unittest.TestCase):
    def test_every_registered_tool_has_a_dispatch_contract(self):
        expected = set(TOOL_REGISTRY) - {"respond"}
        self.assertEqual(set(_DISPATCH_TARGETS), expected)

    def test_every_registered_tool_dispatches_once_without_real_side_effects(self):
        for tool, spec in TOOL_REGISTRY.items():
            parameters = {
                field: _value(value_type)
                for field, value_type in spec.required.items()
            }
            with self.subTest(tool=tool):
                if tool == "respond":
                    self.assertEqual(
                        _call_tool(tool, parameters, speak=None),
                        "safe-test-value",
                    )
                    continue
                with patch(_DISPATCH_TARGETS[tool], return_value=f"{tool}-ok") as action:
                    self.assertEqual(
                        _call_tool(tool, parameters, speak=None),
                        f"{tool}-ok",
                    )
                action.assert_called_once()
                if tool == "remember_rule":
                    self.assertEqual(action.call_args.kwargs["rule"], parameters["rule"])
                    self.assertEqual(action.call_args.kwargs["scope"], "global")
                else:
                    self.assertEqual(action.call_args.kwargs["parameters"], parameters)


if __name__ == "__main__":
    unittest.main()
