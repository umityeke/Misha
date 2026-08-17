from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.executor import AgentExecutor
from agent.runtime_result import ResultStatus
from agent.verifier import VerificationStatus, verify_tool_result


class ToolVerifierTests(unittest.TestCase):
    def test_explicit_failure_text_fails_contract(self):
        result = verify_tool_result(
            "weather_report", {"city": "Istanbul"}, "Could not fetch weather"
        )
        self.assertEqual(result.status, VerificationStatus.FAILED)

    def test_file_write_is_verified_against_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "note.txt"
            target.write_text("expected", encoding="utf-8")
            result = verify_tool_result(
                "file_controller",
                {
                    "action": "write",
                    "path": str(target),
                    "content": "expected",
                },
                "Written to: note.txt",
            )
            self.assertEqual(result.status, VerificationStatus.VERIFIED)
            target.write_text("wrong", encoding="utf-8")
            mismatch = verify_tool_result(
                "file_controller",
                {
                    "action": "write",
                    "path": str(target),
                    "content": "expected",
                },
                "Written to: note.txt",
            )
            self.assertEqual(mismatch.status, VerificationStatus.FAILED)

    def test_external_effect_without_evidence_is_unverified(self):
        result = verify_tool_result(
            "send_message",
            {"receiver": "Ada", "message_text": "Hi", "platform": "WhatsApp"},
            "Message sent successfully",
        )
        self.assertEqual(result.status, VerificationStatus.UNVERIFIED)

    def test_executor_does_not_retry_unverified_external_effect(self):
        plan = {
            "goal": "send",
            "steps": [{
                "step": 1,
                "tool": "send_message",
                "description": "send",
                "parameters": {
                    "receiver": "Ada",
                    "message_text": "Hi",
                    "platform": "WhatsApp",
                },
            }],
        }
        with (
            patch("agent.executor._build_agent_context", return_value=""),
            patch("agent.executor.create_plan", return_value=plan),
            patch(
                "agent.executor._call_tool", return_value="Message sent successfully"
            ) as call,
        ):
            result = AgentExecutor().execute_result("send", approve=lambda _: True)
        self.assertEqual(result.status, ResultStatus.UNVERIFIED)
        self.assertIn("could not be independently confirmed", result.message)
        call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
