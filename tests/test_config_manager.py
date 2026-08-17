import os
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from memory import config_manager


class LocalConfigFallbackTests(unittest.TestCase):
    def test_data_directory_override_must_be_absolute(self):
        import importlib
        import memory.config_manager as config_module

        original = config_module.LOCAL_CONFIG_PATH
        try:
            with patch.dict(os.environ, {"MISHA_DATA_DIR": "relative/path"}):
                reloaded = importlib.reload(config_module)
                self.assertEqual(reloaded.LOCAL_CONFIG_PATH, Path.home() / ".misha" / "config.db")
        finally:
            config_module.LOCAL_CONFIG_PATH = original

    def test_set_and_get_work_without_postgres(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            config_manager, "DATABASE_URL", None
        ), patch.object(
            config_manager, "LOCAL_CONFIG_PATH", Path(temp_dir) / "config.db"
        ):
            self.assertTrue(config_manager.set_config("os_system", "mac"))
            self.assertEqual(config_manager.get_config("os_system"), "mac")
            self.assertEqual(config_manager.LOCAL_CONFIG_PATH.stat().st_mode & 0o777, 0o600)

    def test_remote_config_is_opt_in(self):
        with patch.object(config_manager, "DATABASE_URL", "postgres://example"), patch.object(
            config_manager, "REMOTE_CONFIG_ENABLED", False
        ), patch.object(config_manager, "psycopg2") as psycopg2:
            self.assertIsNone(config_manager._get_conn())
            psycopg2.connect.assert_not_called()

    def test_credentials_are_rejected_and_legacy_local_values_are_scrubbed(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            config_manager, "LOCAL_CONFIG_PATH", Path(temp_dir) / "config.db"
        ):
            config_manager._init_local_config()
            with sqlite3.connect(config_manager.LOCAL_CONFIG_PATH) as conn:
                conn.execute("INSERT INTO app_config(key,value) VALUES('api_key','private')")
            config_manager._init_local_config()
            with sqlite3.connect(config_manager.LOCAL_CONFIG_PATH) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM app_config WHERE key='api_key'"
                ).fetchone()[0]
            self.assertEqual(count, 0)
            with self.assertRaisesRegex(ValueError, "Credentials cannot"):
                config_manager.set_config("access_token", "private")


if __name__ == "__main__":
    unittest.main()
