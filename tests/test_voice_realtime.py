import unittest

from core.voice.events import VoiceEvent
from core.voice.realtime import (
    AudioChunk,
    DropOldestAsyncQueue,
    RealtimeConnectionManager,
    RealtimeInterruptionCoordinator,
    RealtimeVoiceSession,
)


class _Session:
    def __init__(self, input_queue=None, output_queue=None):
        self.interrupted = False
        self.input_queue = input_queue
        self.output_queue = output_queue

    async def connect(self):
        pass

    async def send_audio(self, chunk):
        pass

    async def interrupt(self):
        if self.input_queue is not None:
            assert self.input_queue.empty()
        if self.output_queue is not None:
            assert self.output_queue.empty()
        self.interrupted = True

    async def close(self):
        pass

    async def events(self):
        yield VoiceEvent("ready", "test-session")


class _FailingSession(_Session):
    async def interrupt(self):
        raise ConnectionError("sensitive provider detail")


class _ConnectSession(_Session):
    def __init__(self, *, fail: bool):
        super().__init__()
        self.fail = fail
        self.closed = False

    async def connect(self):
        if self.fail:
            raise ConnectionError("private provider endpoint")

    async def close(self):
        self.closed = True


class RealtimeVoiceTests(unittest.IsolatedAsyncioTestCase):
    def test_audio_chunk_validation(self):
        self.assertEqual(AudioChunk(b"pcm").mime_type, "audio/pcm")
        with self.assertRaises(ValueError):
            AudioChunk(b"")

    def test_provider_neutral_session_contract_is_runtime_checkable(self):
        self.assertIsInstance(_Session(), RealtimeVoiceSession)

    async def test_full_queue_drops_oldest_and_keeps_fresh_audio(self):
        queue = DropOldestAsyncQueue[str](maximum_size=2)
        self.assertFalse(queue.put_latest("oldest"))
        self.assertFalse(queue.put_latest("middle"))
        self.assertTrue(queue.put_latest("newest"))
        self.assertEqual(await queue.get(), "middle")
        queue.task_done()
        self.assertEqual(await queue.get(), "newest")
        queue.task_done()
        self.assertEqual(queue.stats.accepted, 3)
        self.assertEqual(queue.stats.dropped, 1)
        self.assertEqual(queue.stats.current_size, 0)

    async def test_clear_pending_removes_all_buffered_audio(self):
        queue = DropOldestAsyncQueue[int](maximum_size=3)
        queue.put_latest(1)
        queue.put_latest(2)
        self.assertEqual(queue.clear_pending(), 2)
        self.assertTrue(queue.empty())
        await queue.join()

    def test_queue_rejects_unbounded_or_zero_capacity(self):
        with self.assertRaises(ValueError):
            DropOldestAsyncQueue(maximum_size=0)

    async def test_interrupt_clears_queues_before_notifying_provider(self):
        input_queue = DropOldestAsyncQueue[object](maximum_size=4)
        output_queue = DropOldestAsyncQueue[object](maximum_size=4)
        input_queue.put_latest(b"stale input")
        output_queue.put_latest(b"stale output 1")
        output_queue.put_latest(b"stale output 2")
        session = _Session(input_queue, output_queue)
        coordinator = RealtimeInterruptionCoordinator(
            session, input_queue, output_queue
        )
        result = await coordinator.interrupt()
        self.assertTrue(session.interrupted)
        self.assertTrue(result.provider_notified)
        self.assertEqual(result.input_chunks_cleared, 1)
        self.assertEqual(result.output_chunks_cleared, 2)
        await input_queue.join()
        await output_queue.join()

    async def test_provider_failure_does_not_restore_stale_audio_or_leak_detail(self):
        input_queue = DropOldestAsyncQueue[object](maximum_size=2)
        output_queue = DropOldestAsyncQueue[object](maximum_size=2)
        input_queue.put_latest(b"input")
        output_queue.put_latest(b"output")
        coordinator = RealtimeInterruptionCoordinator(
            _FailingSession(), input_queue, output_queue
        )
        result = await coordinator.interrupt()
        self.assertFalse(result.provider_notified)
        self.assertEqual(result.provider_error, "ConnectionError")
        self.assertNotIn("sensitive", result.provider_error)
        self.assertTrue(input_queue.empty())
        self.assertTrue(output_queue.empty())

    async def test_network_reconnect_is_fresh_bounded_and_redacted(self):
        sessions = [_ConnectSession(fail=True), _ConnectSession(fail=True), _ConnectSession(fail=False)]
        manager = RealtimeConnectionManager(
            lambda: sessions.pop(0), maximum_attempts=3, retry_delay_seconds=0
        )
        result = await manager.connect()
        self.assertTrue(result.connected)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.error_type, "")
        self.assertIsNotNone(manager.session)

        failures = [_ConnectSession(fail=True), _ConnectSession(fail=True)]
        failed_manager = RealtimeConnectionManager(
            lambda: failures.pop(0), maximum_attempts=2, retry_delay_seconds=0
        )
        failed = await failed_manager.connect()
        self.assertFalse(failed.connected)
        self.assertEqual(failed.attempts, 2)
        self.assertEqual(failed.error_type, "ConnectionError")
        self.assertNotIn("private", failed.error_type)

    async def test_session_resume_closes_stale_session_and_uses_fresh_state(self):
        old = _ConnectSession(fail=False)
        fresh = _ConnectSession(fail=False)
        manager = RealtimeConnectionManager(
            lambda: fresh, maximum_attempts=1, retry_delay_seconds=0
        )
        manager.session = old
        result = await manager.resume()
        self.assertTrue(result.connected)
        self.assertTrue(old.closed)
        self.assertIs(manager.session, fresh)

    async def test_offline_to_online_transition_recovers_without_stale_session(self):
        online = False

        def factory():
            return _ConnectSession(fail=not online)

        manager = RealtimeConnectionManager(
            factory, maximum_attempts=1, retry_delay_seconds=0
        )
        offline = await manager.connect()
        self.assertFalse(offline.connected)
        self.assertIsNone(manager.session)
        online = True
        recovered = await manager.resume()
        self.assertTrue(recovered.connected)
        self.assertIsNotNone(manager.session)


if __name__ == "__main__":
    unittest.main()
