import unittest

from agent.tool_registry import RiskLevel, TOOL_REGISTRY
from core.action_policy import approval_reason


class ActionPolicyTests(unittest.TestCase):
    def test_every_registered_non_read_only_tool_fails_closed_to_approval(self):
        sample = {str: "value", int: 1, float: 1.0, bool: True, list: [], dict: {}}
        for name, spec in TOOL_REGISTRY.items():
            if spec.risk is RiskLevel.READ_ONLY and not spec.external_impact:
                continue
            parameters = {field: sample[field_type] for field, field_type in spec.required.items()}
            with self.subTest(tool=name, risk=spec.risk):
                self.assertIsNotNone(approval_reason(name, parameters))

    def test_external_and_destructive_actions_require_approval(self):
        cases = (
            ("remember_rule", {"rule": "always be concise"}),
            ("open_app", {"app_name": "Calculator"}),
            ("send_message", {"receiver": "Ada"}),
            ("game_updater", {"action": "install"}),
            ("browser_control", {"action": "go_to"}),
            ("file_controller", {"action": "delete"}),
            ("git_controller", {"action": "push"}),
            ("db_manager", {"action": "query", "query": "DELETE FROM notes"}),
            ("computer_settings", {"action": "shutdown"}),
            ("computer_control", {"action": "click"}),
            ("desktop_control", {"action": "wallpaper"}),
            ("code_helper", {"action": "run"}),
            ("dev_agent", {"description": "change project"}),
            ("developer_tools", {"action": "edit"}),
            ("developer_tools", {"action": "rollback"}),
            ("developer_tools", {"action": "test"}),
            ("developer_tools", {"action": "git_push"}),
            ("rollback_edit", {"action": "rollback"}),
            ("file_controller", {"action": "write"}),
            ("file_controller", {"action": "undo", "transaction_id": "tx_0000000000000000"}),
            ("reminder", {"date": "2026-08-17", "time": "09:00", "message": "x"}),
        )
        for tool, args in cases:
            with self.subTest(tool=tool, args=args):
                self.assertIsNotNone(approval_reason(tool, args))

    def test_read_only_actions_do_not_require_approval(self):
        cases = (
            ("file_controller", {"action": "read"}),
            ("developer_tools", {"action": "search"}),
            ("developer_tools", {"action": "git_status"}),
            ("git_controller", {"action": "status"}),
            ("db_manager", {"action": "query", "query": " SELECT * FROM notes"}),
            ("weather_report", {"city": "Istanbul"}),
        )
        for tool, args in cases:
            with self.subTest(tool=tool, args=args):
                self.assertIsNone(approval_reason(tool, args))


if __name__ == "__main__":
    unittest.main()
