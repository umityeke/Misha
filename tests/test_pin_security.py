import hashlib
import unittest
from unittest.mock import patch

from core import pin_security


class PinSecurityTests(unittest.TestCase):
    def test_new_pin_uses_salted_pbkdf2(self):
        stored = {}
        with patch.object(pin_security, "set_config", lambda key, value: stored.setdefault(key, value) is value):
            self.assertTrue(pin_security.set_pin("1234"))
        self.assertTrue(stored["hashed_pin"].startswith("pbkdf2_sha256$"))
        self.assertNotIn(hashlib.sha256(b"1234").hexdigest(), stored["hashed_pin"])

    def test_legacy_hash_verifies_and_migrates(self):
        legacy = hashlib.sha256(b"4321").hexdigest()
        with patch.object(pin_security, "get_config", return_value=legacy), patch.object(
            pin_security, "set_pin", return_value=True
        ) as migrate:
            self.assertTrue(pin_security.verify_pin("4321"))
            migrate.assert_called_once_with("4321")

    def test_invalid_pin_is_rejected(self):
        self.assertFalse(pin_security.set_pin("12ab"))


if __name__ == "__main__":
    unittest.main()
