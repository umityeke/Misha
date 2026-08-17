import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from actions import developer_tools as tools
from agent.tool_registry import get_tool_spec, validate_tool_parameters
from agent.verifier import VerificationStatus, verify_tool_result


class DeveloperToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.data = self.root / "data"
        self.roots = patch.object(tools, "_allowed_roots", return_value=[self.root])
        self.roots.start()
        self.environment = patch.dict("os.environ", {"MISHA_DATA_DIR": str(self.data)})
        self.environment.start()
        self.cipher = patch("core.file_transactions._CIPHER", Fernet(Fernet.generate_key()))
        self.cipher.start()

    def tearDown(self):
        self.cipher.stop()
        self.environment.stop()
        self.roots.stop()
        self.temp.cleanup()

    def call(self, action, **parameters):
        return tools.developer_tools({
            "action": action, "workspace": str(self.workspace), **parameters,
        })

    def test_workspace_selection_is_absolute_bounded_and_persisted(self):
        stored = {}
        with patch.object(tools, "set_config", side_effect=stored.__setitem__):
            result = tools.select_workspace(str(self.workspace))
        self.assertIn("selected", result)
        self.assertEqual(stored[tools.WORKSPACE_KEY], str(self.workspace))
        with self.assertRaises(ValueError):
            tools.validate_workspace("relative")
        outside = self.root.parent
        with self.assertRaises(ValueError):
            tools.validate_workspace(str(outside))

    def test_search_and_context_are_bounded_and_ignore_symlinks(self):
        (self.workspace / "main.py").write_text("needle = 1\n", encoding="utf-8")
        outside = self.root / "outside.py"
        outside.write_text("needle = 'private'\n", encoding="utf-8")
        (self.workspace / "linked.py").symlink_to(outside)
        result = self.call("search", query="needle")
        self.assertIn("main.py:1", result)
        self.assertNotIn("private", result)
        self.assertEqual(self.call("context", file_path="main.py"), "needle = 1\n")
        self.assertIn("escapes", self.call("context", file_path="../outside.py"))

    def test_diff_transactional_edit_and_rollback(self):
        target = self.workspace / "main.py"
        target.write_text("before\n", encoding="utf-8")
        preview = self.call("diff_preview", file_path="main.py", content="after\n")
        self.assertIn("-before", preview)
        result = self.call("edit", file_path="main.py", content="after\n")
        tx_id = result.split("Undo ID: ", 1)[1].splitlines()[0]
        self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
        verified = verify_tool_result(
            "developer_tools",
            {"action": "edit", "workspace": str(self.workspace), "file_path": "main.py", "content": "after\n"},
            result,
        )
        self.assertEqual(verified.status, VerificationStatus.VERIFIED)
        rolled_back = self.call("rollback", transaction_id=tx_id)
        self.assertIn("rolled back safely", rolled_back)
        self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_rollback_refuses_a_later_user_edit(self):
        target = self.workspace / "main.py"
        target.write_text("before", encoding="utf-8")
        result = self.call("edit", file_path="main.py", content="after")
        tx_id = result.split("Undo ID: ", 1)[1].splitlines()[0]
        target.write_text("later", encoding="utf-8")
        self.assertIn("Rollback blocked", self.call("rollback", transaction_id=tx_id))
        self.assertEqual(target.read_text(encoding="utf-8"), "later")

    def test_git_read_and_commit_suggestion(self):
        subprocess.run(["git", "init", "-q"], cwd=self.workspace, check=True)
        (self.workspace / "new.py").write_text("x = 1\n", encoding="utf-8")
        self.assertIn("new.py", self.call("git_status"))
        self.assertIn("update new.py", self.call("commit_suggest"))
        self.assertIn("no output", self.call("git_diff"))

    def test_quality_command_is_allowlisted_sandboxed_and_bounded(self):
        (self.workspace / "tests").mkdir()
        completed = subprocess.CompletedProcess([], 0, "ok", "")
        with patch.object(tools.shutil, "which", return_value="/usr/bin/sandbox-exec"), patch.object(
            tools.subprocess, "run", return_value=completed
        ) as run:
            result = self.call("test")
        self.assertIn("passed", result)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["/usr/bin/sandbox-exec", "-p"])
        self.assertIn("(deny network*)", command[2])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_schema_and_dynamic_approval_contract(self):
        validated = validate_tool_parameters("developer_tools", {
            "action": "search", "workspace": str(self.workspace), "query": "x",
        })
        self.assertEqual(validated["action"], "search")
        spec = get_tool_spec("developer_tools")
        self.assertEqual(spec.verifier, "developer_state")
        self.assertEqual(spec.rollback, "encrypted_snapshot")


if __name__ == "__main__":
    unittest.main()
