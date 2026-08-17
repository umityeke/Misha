from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.executor import AgentExecutor
from agent.planner import create_plan
from agent.runtime_result import ResultStatus
from agent.verifier import VerificationResult, VerificationStatus


class AgentAcceptanceTests(unittest.TestCase):
    def test_intent_routes_only_to_the_validated_requested_tool(self):
        cases = (
            (
                "search public Python release news",
                {"query": "Python release news"},
                "web_search",
            ),
            (
                "inspect this selected workspace",
                {"action": "git_status"},
                "developer_tools",
            ),
            (
                "list my reminders",
                {"action": "list"},
                "reminder",
            ),
        )
        for goal, parameters, expected_tool in cases:
            raw = {
                "goal": goal,
                "steps": [{"tool": expected_tool, "parameters": parameters}],
            }
            with self.subTest(goal=goal), patch(
                "agent.planner.generate_json", return_value=raw
            ):
                plan = create_plan(goal)
                self.assertEqual(plan["steps"][0]["tool"], expected_tool)

    def test_hallucinated_tool_falls_back_without_executing_it(self):
        hallucinated = {
            "goal": "run magic",
            "steps": [{"tool": "magic_root_shell", "parameters": {}}],
        }
        with patch("agent.planner.generate_json", return_value=hallucinated):
            plan = create_plan("run magic")
        self.assertEqual(plan["steps"][0]["tool"], "respond")
        self.assertNotIn("magic_root_shell", str(plan))

    def test_planner_disables_extended_thinking_and_bounds_output(self):
        raw = {
            "goal": "check weather",
            "steps": [{"tool": "weather_report", "parameters": {"city": "Istanbul"}}],
        }
        with patch("agent.planner.generate_json", return_value=raw) as generate:
            create_plan("check weather")
        self.assertEqual(
            generate.call_args.kwargs["options"],
            {"num_predict": 320, "think": False},
        )

    def test_agent_rollback_is_approval_gated_and_verified(self):
        plan = {
            "goal": "rollback code edit",
            "steps": [
                {
                    "step": 1,
                    "tool": "developer_tools",
                    "description": "rollback the selected transaction",
                    "parameters": {
                        "action": "rollback",
                        "transaction_id": "tx-safe-test",
                    },
                }
            ],
        }
        approvals: list[str] = []
        verified = VerificationResult(VerificationStatus.VERIFIED, "rollback confirmed")
        with patch("agent.executor._build_agent_context", return_value=""), patch(
            "agent.executor.create_plan", return_value=plan
        ), patch("agent.executor._call_tool", return_value="Rollback completed"), patch(
            "agent.executor.verify_tool_result", return_value=verified
        ), patch.object(AgentExecutor, "_summarize", return_value="rolled back"):
            result = AgentExecutor().execute_result(
                "rollback code edit",
                approve=lambda prompt: approvals.append(prompt) or True,
            )
        self.assertEqual(result.status, ResultStatus.SUCCEEDED)
        self.assertEqual(len(approvals), 1)
        self.assertIn("roll back", approvals[0])
        self.assertEqual(result.step_results[0].verification, verified)


if __name__ == "__main__":
    unittest.main()
