import json
import unittest
from unittest.mock import patch

from core.ai import runtime
from core.ai.provider import GenerationRequest


class _FakeProvider:
    name = "fake"

    def __init__(self, response: str):
        self.response = response
        self.requests = []

    def generate(self, request: GenerationRequest) -> str:
        self.requests.append(request)
        return self.response

    def healthcheck(self):
        return True, "ready"

    def unload(self):
        self.unloaded = True


class LocalAIRuntimeTests(unittest.TestCase):
    def test_generate_text_uses_provider(self):
        provider = _FakeProvider("local answer")
        with patch.object(runtime, "get_provider", return_value=provider):
            result = runtime.generate_text("hello", system="private")
        self.assertEqual(result, "local answer")
        self.assertEqual(provider.requests[0].prompt, "hello")
        self.assertFalse(provider.requests[0].json_mode)
        self.assertEqual(provider.requests[0].options["num_ctx"], 8192)

    def test_generate_json_accepts_fenced_payload(self):
        provider = _FakeProvider('```json\n{"safe": true}\n```')
        with patch.object(runtime, "get_provider", return_value=provider):
            result = runtime.generate_json("return json")
        self.assertEqual(result, {"safe": True})
        self.assertTrue(provider.requests[0].json_mode)

    def test_extract_json_rejects_non_json(self):
        with self.assertRaises(ValueError):
            runtime._extract_json("not a structured response")

    def test_release_provider_memory_uses_provider_hook(self):
        provider = _FakeProvider("unused")
        provider.unloaded = False
        with patch.object(runtime, "get_provider", return_value=provider):
            runtime.release_provider_memory()
        self.assertTrue(provider.unloaded)

    def test_get_provider_passes_deduplicated_local_fallbacks(self):
        values = {
            "ai_provider": "ollama",
            "local_model": "primary",
            "ollama_base_url": "http://127.0.0.1:11434",
            "local_model_fallbacks": json.dumps(["fallback", "fallback", "primary"]),
        }
        provider = _FakeProvider("unused")
        with (
            patch.object(runtime, "get_config", side_effect=lambda key: values.get(key)),
            patch.object(runtime, "_ollama_provider", return_value=provider) as factory,
        ):
            self.assertIs(runtime.get_provider(), provider)
        factory.assert_called_once_with(
            "primary",
            "http://127.0.0.1:11434",
            ("fallback",),
        )

    def test_get_provider_rejects_deceptive_remote_ollama_host(self):
        values = {
            "ai_provider": "ollama",
            "local_model": "primary",
            "ollama_base_url": "http://localhost.attacker.invalid:11434",
        }
        with patch.object(
            runtime,
            "get_config",
            side_effect=lambda key: values.get(key),
        ):
            with self.assertRaises(RuntimeError):
                runtime.get_provider()


if __name__ == "__main__":
    unittest.main()
