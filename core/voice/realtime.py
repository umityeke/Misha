from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Callable, Generic, Protocol, TypeVar, runtime_checkable

from core.voice.events import VoiceEvent


@dataclass(frozen=True)
class AudioChunk:
    data: bytes
    mime_type: str = "audio/pcm"

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("Audio chunk data must be non-empty bytes.")
        if not self.mime_type.strip():
            raise ValueError("Audio chunk MIME type cannot be empty.")


@runtime_checkable
class RealtimeVoiceSession(Protocol):
    """Provider-neutral contract for a streaming voice connection."""

    async def connect(self) -> None: ...

    async def send_audio(self, chunk: AudioChunk) -> None: ...

    async def interrupt(self) -> None: ...

    def events(self) -> AsyncIterator[VoiceEvent]: ...

    async def close(self) -> None: ...


T = TypeVar("T")


@dataclass(frozen=True)
class AudioQueueStats:
    accepted: int
    dropped: int
    current_size: int
    maximum_size: int


@dataclass(frozen=True)
class RealtimeInterruptionResult:
    input_chunks_cleared: int
    output_chunks_cleared: int
    provider_notified: bool
    provider_error: str = ""


@dataclass(frozen=True)
class RealtimeConnectionResult:
    connected: bool
    attempts: int
    error_type: str = ""


class RealtimeConnectionManager:
    """Create a fresh provider-neutral session with bounded reconnect attempts."""

    def __init__(
        self,
        session_factory: Callable[[], RealtimeVoiceSession],
        *,
        maximum_attempts: int = 3,
        retry_delay_seconds: float = 0.25,
    ) -> None:
        if not 1 <= int(maximum_attempts) <= 5:
            raise ValueError("Realtime reconnect attempts must be between 1 and 5.")
        if not 0 <= float(retry_delay_seconds) <= 5:
            raise ValueError("Realtime reconnect delay must be between 0 and 5 seconds.")
        self.session_factory = session_factory
        self.maximum_attempts = int(maximum_attempts)
        self.retry_delay_seconds = float(retry_delay_seconds)
        self.session: RealtimeVoiceSession | None = None

    async def connect(self) -> RealtimeConnectionResult:
        error_type = ""
        for attempt in range(1, self.maximum_attempts + 1):
            candidate = self.session_factory()
            try:
                await candidate.connect()
            except Exception as exc:
                error_type = type(exc).__name__
                try:
                    await candidate.close()
                except Exception:
                    pass
                if attempt < self.maximum_attempts and self.retry_delay_seconds:
                    await asyncio.sleep(self.retry_delay_seconds)
                continue
            self.session = candidate
            return RealtimeConnectionResult(True, attempt)
        self.session = None
        return RealtimeConnectionResult(False, self.maximum_attempts, error_type)

    async def resume(self) -> RealtimeConnectionResult:
        """Discard stale provider state and establish a fresh bounded session."""
        previous = self.session
        self.session = None
        if previous is not None:
            try:
                await previous.close()
            except Exception:
                pass
        return await self.connect()


class DropOldestAsyncQueue(asyncio.Queue[T], Generic[T]):
    """A bounded queue that preserves fresh realtime audio under backpressure."""

    def __init__(self, maximum_size: int = 64) -> None:
        if maximum_size < 1:
            raise ValueError("Audio queue maximum size must be positive.")
        super().__init__(maxsize=int(maximum_size))
        self._accepted = 0
        self._dropped = 0

    def put_latest(self, item: T) -> bool:
        """Insert without blocking; return True when the oldest item was dropped."""
        dropped = False
        if self.full():
            self.get_nowait()
            self.task_done()
            self._dropped += 1
            dropped = True
        self.put_nowait(item)
        self._accepted += 1
        return dropped

    def clear_pending(self) -> int:
        removed = 0
        while not self.empty():
            self.get_nowait()
            self.task_done()
            removed += 1
        return removed

    @property
    def stats(self) -> AudioQueueStats:
        return AudioQueueStats(
            accepted=self._accepted,
            dropped=self._dropped,
            current_size=self.qsize(),
            maximum_size=self.maxsize,
        )


class RealtimeInterruptionCoordinator:
    """Clears stale audio before forwarding an interruption to the provider."""

    def __init__(
        self,
        session: RealtimeVoiceSession,
        input_queue: DropOldestAsyncQueue[object],
        output_queue: DropOldestAsyncQueue[object],
    ) -> None:
        self.session = session
        self.input_queue = input_queue
        self.output_queue = output_queue
        self._lock = asyncio.Lock()

    async def interrupt(self) -> RealtimeInterruptionResult:
        async with self._lock:
            input_cleared = self.input_queue.clear_pending()
            output_cleared = self.output_queue.clear_pending()
            try:
                await self.session.interrupt()
            except Exception as exc:
                error_name = type(exc).__name__
                return RealtimeInterruptionResult(
                    input_chunks_cleared=input_cleared,
                    output_chunks_cleared=output_cleared,
                    provider_notified=False,
                    provider_error=error_name,
                )
            return RealtimeInterruptionResult(
                input_chunks_cleared=input_cleared,
                output_chunks_cleared=output_cleared,
                provider_notified=True,
            )
