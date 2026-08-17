import tempfile
import unittest
import ctypes
import subprocess
from pathlib import Path
from unittest.mock import patch

from core import credential_store


class CredentialStoreTests(unittest.TestCase):
    class _FakeSecurity:
        def __init__(self):
            self.stored = None

        def SecKeychainAddGenericPassword(
            self, _keychain, _service_len, _service, _account_len, _account,
            secret_len, secret_buffer, _item,
        ):
            self.stored = ctypes.string_at(secret_buffer, secret_len)
            return 0

    class _FakeCoreFoundation:
        def CFRelease(self, _item):
            return None

    @patch("core.credential_store.platform.system", return_value="Darwin")
    def test_secret_write_uses_security_framework_not_a_process(self, _system):
        security = self._FakeSecurity()
        with patch(
            "core.credential_store._find_raw",
            return_value=(security, self._FakeCoreFoundation(), None, None),
        ), patch("core.credential_store._default_keychain", return_value=ctypes.c_void_p(1)):
            credential_store.set_secret("database-url", "private-value")
        self.assertEqual(security.stored, b"private-value")

    @patch("core.credential_store.platform.system", return_value="Darwin")
    def test_missing_and_failed_keychain_reads_are_distinct(self, _system):
        with patch(
            "core.credential_store._find_raw",
            return_value=(None, None, None, None),
        ):
            self.assertIsNone(credential_store.get_secret("missing"))
        with self.assertRaisesRegex(credential_store.CredentialStoreError, "could not read") as raised:
            with patch(
                "core.credential_store._find_raw",
                side_effect=credential_store.CredentialStoreError(
                    "macOS Keychain could not read the requested credential."
                ),
            ):
                credential_store.get_secret("broken")
        self.assertNotIn("private backend detail", str(raised.exception))

    @patch("core.credential_store.platform.system", return_value="Linux")
    def test_linux_without_secret_tool_fails_closed(self, _system):
        with patch("core.credential_store.shutil.which", return_value=None), self.assertRaisesRegex(
            credential_store.CredentialStoreError, "secret-tool"
        ):
            credential_store.get_secret("database-url")

    @patch("core.credential_store.platform.system", return_value="Windows")
    def test_windows_dispatch_uses_credential_manager_backend(self, _system):
        with patch("core.credential_store._windows_get_secret", return_value="safe") as getter:
            self.assertEqual(credential_store.get_secret("database-url"), "safe")
        getter.assert_called_once_with("database-url")

    @patch("core.credential_store.platform.system", return_value="Linux")
    def test_linux_secret_is_sent_on_stdin_not_argv(self, _system):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch("core.credential_store.shutil.which", return_value="/usr/bin/secret-tool"), patch(
            "core.credential_store.subprocess.run", return_value=completed
        ) as run:
            credential_store.set_secret("database-url", "private-value")
        command = run.call_args.args[0]
        self.assertNotIn("private-value", command)
        self.assertEqual(run.call_args.kwargs["input"], "private-value")
        self.assertFalse(run.call_args.kwargs["check"])

    def test_dotenv_migration_verifies_keychain_before_atomic_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("KEEP=value\nDATABASE_URL=postgresql://private\n", encoding="utf-8")
            with patch("core.credential_store.set_secret") as set_secret, patch(
                "core.credential_store.get_secret", return_value="postgresql://private"
            ):
                self.assertTrue(
                    credential_store.migrate_dotenv_secret(
                        env_path, "DATABASE_URL", "database-url"
                    )
                )
            set_secret.assert_called_once_with("database-url", "postgresql://private")
            self.assertEqual(env_path.read_text(encoding="utf-8"), "KEEP=value\n")
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_failed_migration_preserves_legacy_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            original = "DATABASE_URL=postgresql://private\n"
            env_path.write_text(original, encoding="utf-8")
            with patch("core.credential_store.set_secret"), patch(
                "core.credential_store.get_secret", return_value="different"
            ), self.assertRaises(credential_store.CredentialStoreError):
                credential_store.migrate_dotenv_secret(env_path, "DATABASE_URL", "database-url")
            self.assertEqual(env_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
