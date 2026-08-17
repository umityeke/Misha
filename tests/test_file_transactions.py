import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from core import file_transactions as transactions


class FileTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.db = Path(self.temp.name) / "private" / "transactions.db"
        self.cipher = patch.object(transactions, "_CIPHER", Fernet(Fernet.generate_key()))
        self.cipher.start()

    def tearDown(self):
        self.cipher.stop()
        self.temp.cleanup()

    def test_snapshot_is_encrypted_and_permissions_are_private(self):
        target = self.root / "secret.txt"
        target.write_text("very private before value", encoding="utf-8")
        tx_id = transactions.apply_text_edit(target, "public after value", db_path=self.db)

        raw = self.db.read_bytes()
        self.assertNotIn(b"very private before value", raw)
        self.assertNotIn(str(target).encode(), raw)
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.db.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(transactions.transaction_status(tx_id, db_path=self.db), "applied")

    def test_wrong_key_cannot_decrypt_snapshot(self):
        target = self.root / "secret.txt"
        target.write_text("before", encoding="utf-8")
        tx_id = transactions.apply_text_edit(target, "after", db_path=self.db)

        with patch.object(transactions, "_CIPHER", Fernet(Fernet.generate_key())):
            with self.assertRaisesRegex(RuntimeError, "authentication failed"):
                transactions.rollback_text_edit(tx_id, allowed_roots=[self.root], db_path=self.db)
        self.assertEqual(target.read_text(encoding="utf-8"), "after")

    def test_rollback_refuses_to_overwrite_a_later_change(self):
        target = self.root / "note.txt"
        target.write_text("before", encoding="utf-8")
        tx_id = transactions.apply_text_edit(target, "after", db_path=self.db)
        target.write_text("user changed it", encoding="utf-8")

        result = transactions.rollback_text_edit(tx_id, allowed_roots=[self.root], db_path=self.db)
        self.assertIn("Rollback blocked", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "user changed it")
        self.assertEqual(transactions.transaction_status(tx_id, db_path=self.db), "applied")

    def test_rollback_of_new_file_removes_it_and_is_single_use(self):
        target = self.root / "new.txt"
        tx_id = transactions.apply_text_edit(target, "created", db_path=self.db)
        self.assertIn("rolled back safely", transactions.rollback_text_edit(
            tx_id, allowed_roots=[self.root], db_path=self.db
        ))
        self.assertFalse(target.exists())
        self.assertIn("already rolled_back", transactions.rollback_text_edit(
            tx_id, allowed_roots=[self.root], db_path=self.db
        ))

    def test_malformed_unknown_and_outside_transactions_are_rejected(self):
        self.assertEqual(
            transactions.rollback_text_edit("bad", allowed_roots=[self.root], db_path=self.db),
            "Invalid transaction ID.",
        )
        self.assertEqual(
            transactions.rollback_text_edit("tx_0000000000000000", allowed_roots=[self.root], db_path=self.db),
            "Transaction not found.",
        )
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("before", encoding="utf-8")
        tx_id = transactions.apply_text_edit(outside, "after", db_path=self.db)
        self.assertIn("outside", transactions.rollback_text_edit(
            tx_id, allowed_roots=[self.root], db_path=self.db
        ))
        self.assertEqual(outside.read_text(encoding="utf-8"), "after")

    def test_parent_replaced_with_symlink_is_rejected(self):
        folder = self.root / "folder"
        folder.mkdir()
        target = folder / "note.txt"
        target.write_text("before", encoding="utf-8")
        tx_id = transactions.apply_text_edit(target, "after", db_path=self.db)
        moved = self.root / "real-folder"
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)

        result = transactions.rollback_text_edit(tx_id, allowed_roots=[self.root], db_path=self.db)
        self.assertIn("outside", result)
        self.assertEqual((moved / "note.txt").read_text(encoding="utf-8"), "after")

    def test_failed_atomic_write_is_recorded_without_claiming_success(self):
        target = self.root / "failure.txt"
        with patch.object(transactions, "_atomic_write", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                transactions.apply_text_edit(target, "data", db_path=self.db)
        with sqlite3.connect(self.db) as conn:
            status = conn.execute("SELECT status FROM file_transactions").fetchone()[0]
        self.assertEqual(status, "failed")
        self.assertFalse(target.exists())

    def test_copy_move_rename_and_folder_transactions_are_reversible(self):
        source = self.root / "source.txt"
        source.write_text("stable", encoding="utf-8")
        copied = self.root / "copied.txt"
        copy_tx = transactions.apply_path_operation(
            "copy", source, copied, db_path=self.db
        )
        self.assertTrue(copied.exists())
        self.assertIn("rolled back safely", transactions.rollback_text_edit(
            copy_tx, allowed_roots=[self.root], db_path=self.db
        ))
        self.assertFalse(copied.exists())

        moved = self.root / "moved.txt"
        move_tx = transactions.apply_path_operation(
            "move", source, moved, db_path=self.db
        )
        self.assertFalse(source.exists())
        self.assertIn("rolled back safely", transactions.rollback_text_edit(
            move_tx, allowed_roots=[self.root], db_path=self.db
        ))
        self.assertEqual(source.read_text(encoding="utf-8"), "stable")

        renamed = self.root / "renamed.txt"
        rename_tx = transactions.apply_path_operation(
            "rename", source, renamed, db_path=self.db
        )
        self.assertIn("rolled back safely", transactions.rollback_text_edit(
            rename_tx, allowed_roots=[self.root], db_path=self.db
        ))
        self.assertTrue(source.exists())

        folder = self.root / "new-folder"
        folder_tx = transactions.apply_path_operation(
            "create_folder", folder, db_path=self.db
        )
        self.assertTrue(folder.is_dir())
        self.assertIn("rolled back safely", transactions.rollback_text_edit(
            folder_tx, allowed_roots=[self.root], db_path=self.db
        ))
        self.assertFalse(folder.exists())

    def test_path_rollback_refuses_later_user_changes(self):
        source = self.root / "source.txt"
        source.write_text("before", encoding="utf-8")
        copied = self.root / "copied.txt"
        tx_id = transactions.apply_path_operation("copy", source, copied, db_path=self.db)
        copied.write_text("user changed", encoding="utf-8")
        result = transactions.rollback_text_edit(
            tx_id, allowed_roots=[self.root], db_path=self.db
        )
        self.assertIn("changed after", result)
        self.assertEqual(copied.read_text(encoding="utf-8"), "user changed")


if __name__ == "__main__":
    unittest.main()
