import unittest

from core.observation_privacy import (
    normalize_denylist,
    protect_observation,
    redact_observation,
)


class ObservationPrivacyTests(unittest.TestCase):
    def test_password_managers_are_blocked_before_text_collection(self):
        result = protect_observation("1Password 8", "Vault", "visible content")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "password_manager")

    def test_credential_windows_are_blocked(self):
        result = protect_observation("Safari", "Enter verification code", "123456")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "credential_screen")

    def test_private_memory_windows_are_excluded_from_observation(self):
        result = protect_observation(
            "Misha", "Private Memory — Protected", "decrypted user preference"
        )
        self.assertFalse(result.allowed)

    def test_task_recovery_window_is_excluded_from_observation(self):
        result = protect_observation(
            "Misha", "Task Recovery — Protected", "private interrupted goal"
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "credential_screen")

    def test_user_app_or_domain_denylist_is_enforced(self):
        by_app = protect_observation(
            "Private Notes", "Document", "text", denylist=("private notes",)
        )
        by_domain = protect_observation(
            "Safari", "bank.example account", "text", denylist=("bank.example",)
        )
        self.assertFalse(by_app.allowed)
        self.assertFalse(by_domain.allowed)
        self.assertEqual(by_domain.reason, "user_denylist")

    def test_sensitive_values_are_redacted_locally(self):
        raw = (
            "api_key=super-secret john@example.com 4111 1111 1111 1111 "
            "https://name:password@example.com/private"
        )
        result = redact_observation(raw)
        self.assertNotIn("super-secret", result)
        self.assertNotIn("john@example.com", result)
        self.assertNotIn("4111 1111 1111 1111", result)
        self.assertNotIn("name:password", result)
        self.assertIn("[REDACTED]", result)

    def test_private_keys_are_removed_and_output_is_bounded(self):
        private_key = (
            "-----BEGIN PRIVATE KEY-----\nvery-secret-material\n"  # pragma: allowlist secret
            "-----END PRIVATE KEY-----"
        )
        result = redact_observation(private_key + ("x" * 20_000))
        self.assertNotIn("very-secret-material", result)
        self.assertLessEqual(len(result), 16_000)

    def test_denylist_is_normalized_deduplicated_and_bounded(self):
        values = [" Example.COM ", "example.com", "x" * 201]
        self.assertEqual(normalize_denylist(values), ("example.com",))


if __name__ == "__main__":
    unittest.main()
