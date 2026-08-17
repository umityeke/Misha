from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class FakeProvider:
    def __init__(self, *responses: str):
        self.responses = deque(responses)
        self.requests: list[Any] = []

    def generate(self, request: Any) -> str:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("FakeProvider received an unexpected request")
        return self.responses.popleft()


@dataclass
class FakeAudioDevice:
    index: int = 0
    name: str = "Fake Microphone"
    max_input_channels: int = 1
    max_output_channels: int = 0
    default_samplerate: float = 16_000.0


class FakeAudioBackend:
    def __init__(self, devices: list[FakeAudioDevice] | None = None):
        self.devices = devices or [FakeAudioDevice()]
        self.recordings: deque[bytes] = deque()

    def query_devices(self):
        return [device.__dict__.copy() for device in self.devices]

    def queue_recording(self, pcm: bytes) -> None:
        self.recordings.append(bytes(pcm))


class FakeToolRegistry:
    def __init__(self):
        self.handlers: dict[str, Any] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, name: str, handler) -> None:
        self.handlers[name] = handler

    def call(self, name: str, parameters: dict[str, Any]):
        self.calls.append((name, dict(parameters)))
        if name not in self.handlers:
            raise ValueError(f"Unknown fake tool: {name}")
        return self.handlers[name](dict(parameters))


class FrozenClock:
    def __init__(self, value: datetime | None = None):
        self.value = value or datetime(2030, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def monotonic(self) -> float:
        return self.value.timestamp()

    def advance(self, **delta) -> datetime:
        self.value += timedelta(**delta)
        return self.value


class NetworkFixture:
    """Local fake transport that fails on unqueued network requests."""

    def __init__(self):
        self.responses: dict[tuple[str, str], deque[Any]] = {}
        self.calls: list[tuple[str, str, Any]] = []

    def queue(self, method: str, url: str, response: Any) -> None:
        self.responses.setdefault((method.upper(), url), deque()).append(response)

    def request(self, method: str, url: str, body: Any = None) -> Any:
        key = (method.upper(), url)
        self.calls.append((key[0], key[1], body))
        queue = self.responses.get(key)
        if not queue:
            raise AssertionError(f"Unexpected network request: {key[0]} {key[1]}")
        return queue.popleft()
