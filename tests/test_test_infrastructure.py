import unittest
from datetime import datetime, timezone

from tests.fakes import (
    FakeAudioBackend,
    FakeProvider,
    FakeToolRegistry,
    FrozenClock,
    NetworkFixture,
)


class TestInfrastructureTests(unittest.TestCase):
    def test_provider_is_deterministic_and_rejects_unexpected_calls(self):
        provider = FakeProvider("one")
        self.assertEqual(provider.generate({"prompt": "x"}), "one")
        with self.assertRaises(AssertionError):
            provider.generate({"prompt": "extra"})

    def test_fake_audio_and_tool_registry(self):
        audio = FakeAudioBackend()
        self.assertEqual(audio.query_devices()[0]["name"], "Fake Microphone")
        registry = FakeToolRegistry()
        registry.register("echo", lambda value: value["text"])
        self.assertEqual(registry.call("echo", {"text": "ok"}), "ok")

    def test_frozen_clock_advances_only_explicitly(self):
        clock = FrozenClock(datetime(2030, 1, 1, tzinfo=timezone.utc))
        before = clock.monotonic()
        clock.advance(seconds=5)
        self.assertEqual(clock.monotonic() - before, 5)

    def test_network_fixture_is_allowlist_only(self):
        network = NetworkFixture()
        network.queue("GET", "https://example.test/data", {"ok": True})
        self.assertEqual(network.request("GET", "https://example.test/data"), {"ok": True})
        with self.assertRaises(AssertionError):
            network.request("GET", "https://unexpected.test/")


if __name__ == "__main__":
    unittest.main()
