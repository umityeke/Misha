import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from core import memory_service
from memory import memory_manager


class MemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "memory.db"
        self.legacy_path = root / "legacy.json"
        self.patches = [
            patch.object(memory_service, "MEMORY_DB_PATH", self.db_path),
            patch.object(memory_service, "LEGACY_MEMORY_PATH", self.legacy_path),
            patch.object(memory_service, "_MEMORY_CIPHER", Fernet(Fernet.generate_key())),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_all_memory_kinds_share_private_local_store(self):
        for kind in memory_service.MemoryKind:
            memory_service.put_memory(kind, f"key-{kind.value}", "safe value")
        self.assertEqual(len(memory_service.list_memories()), 4)
        self.assertEqual(os.stat(self.db_path).st_mode & 0o777, 0o600)
        with sqlite3.connect(self.db_path) as conn:
            version = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(version, str(memory_service.SCHEMA_VERSION))

    def test_memory_content_is_authenticated_and_encrypted_at_rest(self):
        memory_service.put_memory(
            "long_term", "private-topic", "private-value", category="private-category",
            metadata={"private-note": "private-metadata"},
        )
        raw = self.db_path.read_bytes()
        for plaintext in (
            b"private-topic", b"private-value", b"private-category", b"private-metadata"
        ):
            self.assertNotIn(plaintext, raw)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT key,category,value,metadata_json,encrypted FROM memories"
            ).fetchone()
        self.assertTrue(all(str(field).startswith("enc:v1:") for field in row[:4]))
        self.assertEqual(row[4], 1)

    def test_wrong_key_fails_closed_without_returning_content(self):
        memory_service.put_memory("long_term", "topic", "protected-content")
        with patch.object(memory_service, "_MEMORY_CIPHER", Fernet(Fernet.generate_key())):
            with self.assertRaisesRegex(RuntimeError, "access was denied") as raised:
                memory_service.list_memories("long_term")
        self.assertNotIn("protected-content", str(raised.exception))

    def test_plaintext_v1_database_is_migrated_transactionally(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE memories (id TEXT PRIMARY KEY,kind TEXT,key TEXT,category TEXT,value TEXT,"
                "metadata_json TEXT,source TEXT,created_at TEXT,updated_at TEXT,expires_at TEXT)"
            )
            conn.execute(
                "INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("old-id", "long_term", "old-key", "notes", "old-value", "{}", "legacy",
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", None),
            )
        records = memory_service.list_memories("long_term")
        self.assertEqual(records[0].value, "old-value")
        self.assertNotIn(b"old-value", self.db_path.read_bytes())

    def test_working_and_long_term_upsert_but_episodes_append(self):
        memory_service.put_memory("working", "active", "one")
        memory_service.put_memory("working", "active", "two")
        memory_service.put_memory("episodic", "user", "one")
        memory_service.put_memory("episodic", "user", "two")
        self.assertEqual(len(memory_service.list_memories("working")), 1)
        self.assertEqual(memory_service.get_working_memory("active"), "two")
        self.assertEqual(len(memory_service.list_memories("episodic")), 2)

    def test_sensitive_and_model_forbidden_data_are_rejected(self):
        forbidden = (
            "api_key=super-secret-value",
            "-----BEGIN PRIVATE KEY----- abc",  # pragma: allowlist secret
            "ghp_abcdefghijklmnopqrstuvwxyz123456",  # pragma: allowlist secret
            "4111 1111 1111 1111",
        )
        for value in forbidden:
            with self.subTest(value=value), self.assertRaises(ValueError):
                memory_service.put_memory("long_term", "unsafe", value)
        with self.assertRaisesRegex(ValueError, "model may not"):
            memory_service.put_memory(
                "long_term", "otp", "my verification code is 123456", source="model"
            )

    def test_expired_records_are_purged(self):
        record = memory_service.put_memory("working", "temporary", "value")
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE memories SET expires_at=? WHERE id=?", (expired, record.id))
            conn.commit()
        self.assertEqual(memory_service.list_memories("working"), [])

    def test_view_delete_category_and_clear(self):
        first = memory_service.put_memory("long_term", "name", "Misha", category="identity")
        memory_service.put_memory("long_term", "city", "Istanbul", category="identity")
        memory_service.put_memory("decision", "topic", "decision")
        self.assertEqual(memory_service.get_memory(first.id), first)
        self.assertTrue(memory_service.delete_memory(first.id))
        self.assertEqual(memory_service.delete_category("identity"), 1)
        self.assertEqual(memory_service.clear_memory(), 1)
        self.assertEqual(memory_service.list_memories(), [])

    def test_export_import_revalidates_records(self):
        memory_service.put_memory("long_term", "language", "Turkish", category="identity")
        export_path = Path(self.temp_dir.name) / "memory-export.json"
        self.assertEqual(memory_service.export_memory(export_path), 1)
        self.assertEqual(os.stat(export_path).st_mode & 0o777, 0o600)
        memory_service.clear_memory()
        result = memory_service.import_memory(export_path)
        self.assertEqual(result, {"imported": 1, "rejected": 0})
        self.assertEqual(memory_service.list_memories("long_term")[0].value, "Turkish")

        payload = json.loads(export_path.read_text(encoding="utf-8"))
        payload["records"][0]["value"] = "password=hunter2"
        export_path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(memory_service.import_memory(export_path)["rejected"], 1)

    def test_legacy_json_is_imported_only_once(self):
        self.legacy_path.write_text(
            json.dumps({"identity": {"name": {"value": "Ümit"}}}), encoding="utf-8"
        )
        self.assertEqual(memory_service.migrate_legacy_json()["imported"], 1)
        self.assertEqual(memory_service.migrate_legacy_json()["imported"], 0)
        loaded = memory_manager.load_memory()
        self.assertEqual(loaded["identity"]["name"]["value"], "Ümit")

    def test_memory_manager_uses_unified_service(self):
        memory_manager.remember("editor", "VS Code", "preferences")
        loaded = memory_manager.load_memory()
        self.assertEqual(loaded["preferences"]["editor"]["value"], "VS Code")
        self.assertIn("Forgotten", memory_manager.forget("editor", "preferences"))


if __name__ == "__main__":
    unittest.main()
