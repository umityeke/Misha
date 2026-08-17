import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from core.ai.ollama import OllamaProvider
from core.ai.provider import GenerationRequest, ProviderError, ProviderErrorKind


class OllamaProviderTests(unittest.TestCase):
    def test_cloud_model_alias_is_rejected(self):
        with self.assertRaises(ValueError):
            OllamaProvider("gpt-oss:120b-cloud")

    def test_generation_requests_non_streaming_response(self):
        provider = OllamaProvider("local-model")
        with patch.object(provider, "_request", return_value={"response": "OK"}) as request:
            self.assertEqual(provider.generate(GenerationRequest("hello")), "OK")
        payload = request.call_args.args[1]
        self.assertFalse(payload["stream"])

    def test_unload_uses_zero_keep_alive(self):
        provider = OllamaProvider("local-model")
        with patch.object(provider, "_request", return_value={}) as request:
            provider.unload()
        self.assertEqual(request.call_args.args[1]["keep_alive"], 0)

    def test_transient_runner_startup_response_is_retried(self):
        provider = OllamaProvider("local-model")
        responses = [
            {"response": "", "done": False},
            {"response": "ready", "done": True},
        ]
        with patch.object(provider, "_request", side_effect=responses) as request:
            with patch("core.ai.ollama.time.sleep"):
                result = provider.generate(GenerationRequest("hello"))
        self.assertEqual(result, "ready")
        self.assertEqual(request.call_count, 2)

    def test_offline_healthcheck_fails_softly(self):
        provider = OllamaProvider("local-model")
        with patch.object(provider, "_request", side_effect=RuntimeError("offline")):
            ready, message = provider.healthcheck()
        self.assertFalse(ready)
        self.assertIn("offline", message)

    def test_retryable_provider_error_uses_bounded_backoff_and_jitter(self):
        provider = OllamaProvider(
            "local-model",
            max_attempts=3,
            initial_backoff_seconds=0.5,
            maximum_backoff_seconds=1.0,
            jitter_ratio=0.2,
        )
        transient = ProviderError(
            ProviderErrorKind.OFFLINE,
            "offline",
            retryable=True,
        )
        responses = [transient, transient, {"response": "ready"}]
        with (
            patch.object(provider, "_request", side_effect=responses) as request,
            patch("core.ai.ollama.random.uniform", side_effect=[0.05, 0.1]),
            patch("core.ai.ollama.time.sleep") as sleep,
        ):
            result = provider.generate(GenerationRequest("hello"))
        self.assertEqual(result, "ready")
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.55, 1.1])

    def test_permanent_provider_error_is_not_retried(self):
        provider = OllamaProvider("local-model")
        permanent = ProviderError(
            ProviderErrorKind.REQUEST,
            "bad request",
            retryable=False,
        )
        with patch.object(provider, "_request", side_effect=permanent) as request:
            with self.assertRaises(ProviderError):
                provider.generate(GenerationRequest("hello"))
        self.assertEqual(request.call_count, 1)

    def test_http_error_is_classified_without_leaking_response_body(self):
        provider = OllamaProvider("local-model")
        error = HTTPError(
            provider.base_url,
            503,
            "unavailable",
            {},
            BytesIO(b"secret backend detail"),
        )
        with patch("core.ai.ollama.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as raised:
                provider._request("/api/generate", {})
        self.assertEqual(raised.exception.kind, ProviderErrorKind.SERVER)
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("secret", str(raised.exception))

    def test_rate_limit_is_typed_retryable_and_body_is_redacted(self):
        provider = OllamaProvider("local-model")
        error = HTTPError(
            provider.base_url,
            429,
            "too many requests",
            {},
            BytesIO(b"private quota detail"),
        )
        with patch("core.ai.ollama.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as raised:
                provider._request("/api/generate", {})
        self.assertEqual(raised.exception.kind, ProviderErrorKind.RATE_LIMIT)
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertNotIn("private", str(raised.exception))

    def test_unreachable_service_is_typed_as_retryable_offline(self):
        provider = OllamaProvider("local-model")
        with patch("core.ai.ollama.urlopen", side_effect=URLError("connection refused")):
            with self.assertRaises(ProviderError) as raised:
                provider._request("/api/generate", {})
        self.assertEqual(raised.exception.kind, ProviderErrorKind.OFFLINE)
        self.assertTrue(raised.exception.retryable)

    def test_healthcheck_selects_installed_completion_fallback(self):
        provider = OllamaProvider(
            "primary:latest",
            fallback_models=("fallback:latest",),
        )
        responses = [
            {"models": [{"name": "fallback:latest"}]},
            {"capabilities": ["completion", "tools"]},
        ]
        with patch.object(provider, "_request", side_effect=responses) as request:
            ready, message = provider.healthcheck()
        self.assertTrue(ready)
        self.assertEqual(provider.active_model, "fallback:latest")
        self.assertIn("fallback", message)
        self.assertEqual(request.call_args_list[1].args[0], "/api/show")

    def test_healthcheck_rejects_non_completion_model(self):
        provider = OllamaProvider("embedding-model")
        responses = [
            {"models": [{"model": "embedding-model"}]},
            {"capabilities": ["embedding"]},
        ]
        with patch.object(provider, "_request", side_effect=responses):
            ready, message = provider.healthcheck()
        self.assertFalse(ready)
        self.assertIn("does not support text completion", message)

    def test_generation_uses_model_selected_by_capability_check(self):
        provider = OllamaProvider("primary", fallback_models=("fallback",))
        responses = [
            {"models": [{"name": "fallback"}]},
            {"capabilities": ["completion"]},
            {"response": "ok"},
        ]
        with patch.object(provider, "_request", side_effect=responses) as request:
            self.assertTrue(provider.healthcheck()[0])
            self.assertEqual(provider.generate(GenerationRequest("hello")), "ok")
        generation_payload = request.call_args_list[2].args[1]
        self.assertEqual(generation_payload["model"], "fallback")


if __name__ == "__main__":
    unittest.main()
