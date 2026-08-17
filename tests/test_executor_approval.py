import unittest
from unittest.mock import patch

from agent.executor import AgentExecutor
from agent.verifier import VerificationResult, VerificationStatus


class ExecutorApprovalTests(unittest.TestCase):
    def test_approved_exact_scope_executes_once(self):
        plan = {
            "goal": "send",
            "steps": [{
                "step": 1,
                "tool": "send_message",
                "description": "send",
                "parameters": {
                    "receiver": "Ada",
                    "message_text": "Hello",
                    "platform": "WhatsApp",
                },
            }],
        }
        prompts = []
        with patch("agent.executor._build_agent_context", return_value=""), patch(
            "agent.executor.create_plan", return_value=plan
        ), patch("agent.executor._call_tool", return_value="sent") as call_tool, patch.object(
            AgentExecutor, "_summarize", return_value="done"
        ), patch(
            "agent.executor.verify_tool_result",
            return_value=VerificationResult(VerificationStatus.VERIFIED, "confirmed"),
        ):
            result = AgentExecutor().execute(
                "send",
                approve=lambda prompt: prompts.append(prompt) or True,
            )
        self.assertEqual(result, "done")
        call_tool.assert_called_once()
        self.assertEqual(len(prompts), 1)
        self.assertIn('"receiver": "Ada"', prompts[0])

    def test_executor_rejects_invalid_parameters_before_tool_call(self):
        plan = {
            "goal": "respond",
            "steps": [{
                "step": 1,
                "tool": "respond",
                "description": "respond",
                "parameters": {"message": "ok", "unexpected": "blocked"},
            }],
        }
        with patch("agent.executor._build_agent_context", return_value=""), patch(
            "agent.executor.create_plan", return_value=plan
        ), patch("agent.executor._call_tool") as call_tool:
            result = AgentExecutor().execute("respond")
        self.assertIn("Task rejected", result)
        call_tool.assert_not_called()

    def test_risky_tool_fails_closed_without_approval_callback(self):
        plan = {
            "goal": "delete file",
            "steps": [
                {
                    "step": 1,
                    "tool": "file_controller",
                    "description": "delete file",
                    "parameters": {"action": "delete", "path": "/tmp/example"},
                    "critical": True,
                }
            ],
        }
        with patch("agent.executor._build_agent_context", return_value=""), patch(
            "agent.executor.create_plan", return_value=plan
        ), patch(
            "agent.executor._call_tool"
        ) as call_tool:
            result = AgentExecutor().execute("delete file")
        self.assertIn("Approval required", result)
        call_tool.assert_not_called()

    def test_rejected_approval_does_not_call_tool(self):
        plan = {
            "goal": "send message",
            "steps": [
                {
                    "step": 1,
                    "tool": "send_message",
                    "description": "send",
                    "parameters": {
                        "receiver": "Ada",
                        "message_text": "Hello",
                        "platform": "WhatsApp",
                    },
                    "critical": True,
                }
            ],
        }
        with patch("agent.executor._build_agent_context", return_value=""), patch(
            "agent.executor.create_plan", return_value=plan
        ), patch(
            "agent.executor._call_tool"
        ) as call_tool:
            result = AgentExecutor().execute("send", approve=lambda _: False)
        self.assertIn("rejected", result)
        call_tool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
