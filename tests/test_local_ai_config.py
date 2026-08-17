import unittest
from unittest.mock import patch

from memory import config_manager


class LocalAIConfigTests(unittest.TestCase):
    def test_local_configuration_needs_no_api_key(self):
        stored = {}
        with patch.object(
            config_manager,
            "set_config",
            side_effect=lambda key, value: stored.__setitem__(key, value) or True,
        ):
            config_manager.save_local_ai_config(
                "qwen3-coder:30b",
                fallback_models=["qwen2.5-coder:14b", "qwen2.5-coder:14b"],
            )
        self.assertEqual(stored["ai_provider"], "ollama")
        self.assertEqual(stored["local_model"], "qwen3-coder:30b")
        self.assertNotIn("gemini_api_key", stored)
        self.assertEqual(
            stored["local_model_fallbacks"],
            '["qwen2.5-coder:14b"]',
        )

    def test_remote_ollama_address_is_rejected_by_default(self):
        for address in (
            "https://untrusted.example",
            "http://localhost.untrusted.example:11434",
        ):
            with self.subTest(address=address), self.assertRaises(ValueError):
                config_manager.save_local_ai_config("qwen3-coder:30b", address)

    def test_paid_provider_is_not_considered_configured(self):
        values = {"ai_provider": "gemini", "gemini_api_key": "x" * 40}
        with patch.object(
            config_manager,
            "get_config",
            side_effect=lambda key: values.get(key),
        ):
            self.assertFalse(config_manager.is_configured())

    def test_invalid_fallback_model_name_is_rejected(self):
        with self.assertRaises(ValueError):
            config_manager.save_local_ai_config(
                "qwen3-coder:30b",
                fallback_models=["x" * 129],
            )

    def test_context_length_is_bounded_and_persisted(self):
        stored = {}
        with patch.object(
            config_manager,
            "set_config",
            side_effect=lambda key, value: stored.__setitem__(key, value) or True,
        ):
            config_manager.save_local_ai_config(context_length=16384)
        self.assertEqual(stored["local_context_length"], "16384")
        for invalid in (1024, 65536, "not-a-number"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                config_manager.save_local_ai_config(context_length=invalid)

    def test_cloud_model_aliases_are_rejected(self):
        with self.assertRaises(ValueError):
            config_manager.save_local_ai_config("gpt-oss:120b-cloud")
        with self.assertRaises(ValueError):
            config_manager.save_local_ai_config(
                "qwen3-coder:30b",
                fallback_models=["gpt-oss:120b-cloud"],
            )


if __name__ == "__main__":
    unittest.main()
