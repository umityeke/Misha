import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.patch_transaction import PatchTransaction, rollback_transaction


class PatchTransactionBoundaryTests(unittest.TestCase):
    def test_rejects_absolute_and_parent_paths(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as tx_dir:
            with patch("core.patch_transaction.TRANSACTIONS_DIR", tx_dir):
                tx = PatchTransaction(workspace)
                with self.assertRaises(ValueError):
                    tx.stage_edit("../outside.txt", "blocked")
                with self.assertRaises(ValueError):
                    tx.stage_edit(str(Path(workspace).parent / "outside.txt"), "blocked")

    def test_accepts_workspace_relative_path(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as tx_dir:
            with patch("core.patch_transaction.TRANSACTIONS_DIR", tx_dir):
                tx = PatchTransaction(workspace)
                diff = tx.stage_edit("src/example.py", "print('ok')\n")
                self.assertIn("src/example.py", diff)

    def test_rejects_malformed_rollback_id(self):
        self.assertEqual(rollback_transaction("../../escape"), "Invalid transaction ID.")


if __name__ == "__main__":
    unittest.main()
