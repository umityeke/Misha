import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.verifier import VerificationStatus, verify_tool_result


class GitVerifierTests(unittest.TestCase):
    @patch("actions.developer_tools.selected_workspace", return_value=Path("/tmp/project"))
    def test_read_only_git_operation_requires_confirmed_repository(self, _workspace):
        completed = subprocess.CompletedProcess([], 0, "true\n", "")
        with patch("agent.verifier.subprocess.run", return_value=completed) as run:
            result = verify_tool_result(
                "developer_tools", {"action": "git_status"}, "## main"
            )
        self.assertIs(result.status, VerificationStatus.VERIFIED)
        self.assertEqual(run.call_args.args[0], ["git", "rev-parse", "--is-inside-work-tree"])

    @patch("actions.developer_tools.selected_workspace", return_value=Path("/tmp/project"))
    def test_git_push_is_verified_against_exact_remote_ref(self, _workspace):
        head = "a" * 40
        results = [
            subprocess.CompletedProcess([], 0, head + "\n", ""),
            subprocess.CompletedProcess([], 0, "origin/main\n", ""),
            subprocess.CompletedProcess([], 0, f"{head}\trefs/heads/main\n", ""),
        ]
        with patch("agent.verifier.subprocess.run", side_effect=results) as run:
            result = verify_tool_result(
                "developer_tools", {"action": "git_push"}, "Git push completed: ok"
            )
        self.assertIs(result.status, VerificationStatus.VERIFIED)
        self.assertEqual(
            run.call_args_list[-1].args[0],
            ["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"],
        )

    @patch("actions.developer_tools.selected_workspace", return_value=Path("/tmp/project"))
    def test_git_push_mismatch_fails_and_network_error_is_unverified(self, _workspace):
        mismatch = [
            subprocess.CompletedProcess([], 0, "a" * 40, ""),
            subprocess.CompletedProcess([], 0, "origin/main", ""),
            subprocess.CompletedProcess([], 0, f"{'b' * 40}\trefs/heads/main", ""),
        ]
        with patch("agent.verifier.subprocess.run", side_effect=mismatch):
            result = verify_tool_result(
                "developer_tools", {"action": "git_push"}, "Git push completed: ok"
            )
        self.assertIs(result.status, VerificationStatus.FAILED)
        with patch("agent.verifier.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            unavailable = verify_tool_result(
                "developer_tools", {"action": "git_push"}, "Git push completed: ok"
            )
        self.assertIs(unavailable.status, VerificationStatus.UNVERIFIED)


if __name__ == "__main__":
    unittest.main()
