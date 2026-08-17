import tempfile
import unittest
from pathlib import Path

from actions.dev_agent import _safe_project_path


class DevAgentPathSecurityTests(unittest.TestCase):
    def test_project_paths_stay_inside_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(
                _safe_project_path(root, "src/main.py"),
                (root / "src/main.py").resolve(),
            )
            with self.assertRaises(ValueError):
                _safe_project_path(root, "../outside.py")
            with self.assertRaises(ValueError):
                _safe_project_path(root, "/tmp/outside.py")


if __name__ == "__main__":
    unittest.main()
