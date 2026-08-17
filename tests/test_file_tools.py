import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from actions import file_controller as files


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.roots = patch.object(files, "_SAFE_ROOTS", [self.root])
        self.roots.start()
        self.data_dir = patch.dict("os.environ", {"MISHA_DATA_DIR": str(Path(self.temp.name) / "data")})
        self.data_dir.start()
        self.cipher = patch("core.file_transactions._CIPHER", Fernet(Fernet.generate_key()))
        self.cipher.start()

    def tearDown(self):
        self.cipher.stop()
        self.data_dir.stop()
        self.roots.stop()
        self.temp.cleanup()

    def test_create_write_append_read_list_and_find(self):
        self.assertIn("created", files.create_file(str(self.root), "note.txt", "one"))
        self.assertIn("Written", files.write_file(str(self.root), "note.txt", "two"))
        self.assertIn("Appended", files.write_file(str(self.root), "note.txt", "+three", append=True))
        self.assertEqual(files.read_file(str(self.root), "note.txt"), "two+three")
        self.assertIn("note.txt", files.list_files(str(self.root)))
        self.assertIn("note.txt", files.find_files(name="note", path=str(self.root)))
        self.assertEqual((self.root / "note.txt").stat().st_mode & 0o777, 0o600)

    def test_copy_move_and_rename_stay_in_allowed_root(self):
        (self.root / "a.txt").write_text("safe", encoding="utf-8")
        copies = self.root / "copies"
        copies.mkdir()
        self.assertIn("Copied", files.copy_file(str(self.root), "a.txt", str(copies)))
        self.assertIn("Moved", files.move_file(str(copies), "a.txt", str(self.root / "moved.txt")))
        self.assertIn("Renamed", files.rename_file(str(self.root), "moved.txt", "renamed.txt"))
        self.assertTrue((self.root / "renamed.txt").is_file())

    def test_copy_and_move_never_overwrite_existing_destinations(self):
        source = self.root / "source.txt"
        destination = self.root / "destination.txt"
        source.write_text("source", encoding="utf-8")
        destination.write_text("keep", encoding="utf-8")
        self.assertIn("already exists", files.copy_file(str(source), destination=str(destination)))
        self.assertIn("already exists", files.move_file(str(source), destination=str(destination)))
        self.assertEqual(destination.read_text(encoding="utf-8"), "keep")
        self.assertTrue(source.exists())

    def test_outside_workspace_and_parent_rename_are_rejected(self):
        outside = Path(self.temp.name) / "outside.txt"
        self.assertIn("Access denied", files.write_file(str(outside), content="blocked"))
        target = self.root / "safe.txt"
        target.write_text("safe", encoding="utf-8")
        self.assertIn("Access denied", files.rename_file(str(self.root), "safe.txt", "../escape.txt"))
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_symlink_read_write_copy_and_search_are_blocked(self):
        outside = Path(self.temp.name) / "private.txt"
        outside.write_text("private", encoding="utf-8")
        link = self.root / "link.txt"
        link.symlink_to(outside)
        self.assertIn("Access denied", files.read_file(str(link)))
        self.assertIn("Access denied", files.write_file(str(link), content="overwrite"))
        self.assertIn("Access denied", files.copy_file(str(link), destination=str(self.root / "copy.txt")))
        self.assertNotIn("private.txt", files.find_files(name="private", path=str(self.root)))
        self.assertEqual(outside.read_text(encoding="utf-8"), "private")

    def test_broken_symlink_is_blocked(self):
        link = self.root / "broken.txt"
        link.symlink_to(Path(self.temp.name) / "missing.txt")
        self.assertIn("Access denied", files.write_file(str(link), content="blocked"))
        self.assertFalse((Path(self.temp.name) / "missing.txt").exists())

    def test_large_read_write_and_copy_are_bounded(self):
        with patch.object(files, "MAX_READ_BYTES", 4), patch.object(files, "MAX_WRITE_BYTES", 4):
            (self.root / "large.txt").write_text("12345", encoding="utf-8")
            self.assertIn("exceeds", files.read_file(str(self.root), "large.txt"))
            self.assertIn("exceeds", files.write_file(str(self.root), "new.txt", "12345"))
        source = self.root / "source"
        source.mkdir()
        (source / "data.bin").write_bytes(b"12345")
        with patch.object(files, "MAX_COPY_BYTES", 4):
            self.assertIn("exceeds", files.copy_file(str(source), destination=str(self.root / "dest")))

    def test_delete_uses_trash_and_never_permanent_remove(self):
        target = self.root / "trash-me.txt"
        target.write_text("safe", encoding="utf-8")
        with patch.object(files, "_SEND2TRASH", True), patch.object(
            files.send2trash, "send2trash"
        ) as trash:
            result = files.delete_file(str(target))
        self.assertIn("Trash", result)
        trash.assert_called_once_with(str(target))

    def test_create_never_overwrites_existing_file(self):
        target = self.root / "existing.txt"
        target.write_text("original", encoding="utf-8")
        self.assertIn("already exists", files.create_file(str(self.root), "existing.txt", "new"))
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_write_returns_encrypted_undo_id_and_rollback_restores_content(self):
        target = self.root / "undo.txt"
        target.write_text("before", encoding="utf-8")
        result = files.write_file(str(target), content="after")
        tx_id = result.rsplit("Undo ID: ", 1)[1]
        self.assertEqual(target.read_text(encoding="utf-8"), "after")
        self.assertIn("rolled back safely", files.file_controller({
            "action": "undo", "transaction_id": tx_id,
        }))
        self.assertEqual(target.read_text(encoding="utf-8"), "before")


if __name__ == "__main__":
    unittest.main()
