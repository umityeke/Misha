from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Sequence

import numpy as np
import psutil  # type: ignore

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.voice.events import VoiceEvent
from core.voice.realtime import (
    AudioChunk,
    DropOldestAsyncQueue,
    RealtimeInterruptionCoordinator,
)
from core.voice.state import VoiceSessionState, VoiceStateMachine
from core.voice.vad import EnergyVoiceActivityDetector, VADState


class _SoakSession:
    def __init__(self) -> None:
        self.interruptions = 0

    async def connect(self) -> None:
        return None

    async def send_audio(self, chunk: AudioChunk) -> None:
        if not chunk.data:
            raise ValueError("Audio chunk must not be empty.")

    async def interrupt(self) -> None:
        self.interruptions += 1

    async def events(self) -> AsyncIterator[VoiceEvent]:
        if False:
            yield VoiceEvent("unused", "soak")

    async def close(self) -> None:
        return None


def _exercise_state(machine: VoiceStateMachine) -> None:
    for target in (
        VoiceSessionState.WAKE_DETECTED,
        VoiceSessionState.VERIFYING_SPEAKER,
        VoiceSessionState.LISTENING,
        VoiceSessionState.UNDERSTANDING,
        VoiceSessionState.PLANNING,
        VoiceSessionState.EXECUTING,
        VoiceSessionState.VERIFYING,
        VoiceSessionState.RESPONDING,
        VoiceSessionState.IDLE,
    ):
        machine.transition(target, "soak")


def _exercise_vad() -> None:
    detector = EnergyVoiceActivityDetector()
    frame = detector.frame_samples
    for _ in range(10):
        detector.process(np.zeros(frame, dtype=np.float32))
    for _ in range(3):
        detector.process(np.full(frame, 0.08, dtype=np.float32))
    for _ in range(25):
        decision = detector.process(np.zeros(frame, dtype=np.float32))
        if decision.state is VADState.COMPLETE:
            return
    raise RuntimeError("Synthetic VAD cycle did not complete.")


async def run_soak(
    duration_seconds: float,
    *,
    maximum_rss_growth_mib: float = 96.0,
    cycle_pause_seconds: float = 0.01,
    max_cycles: int | None = None,
) -> dict[str, object]:
    if duration_seconds <= 0 or duration_seconds > 28_800:
        raise ValueError("Soak duration must be between 0 and 28800 seconds.")
    if maximum_rss_growth_mib <= 0:
        raise ValueError("RSS growth limit must be positive.")
    process = psutil.Process(os.getpid())
    rss_before = process.memory_info().rss
    peak_rss = rss_before
    threads_before = threading.active_count()
    started_wall = datetime.now(timezone.utc)
    started = time.monotonic()
    deadline = started + float(duration_seconds)
    machine = VoiceStateMachine()
    session = _SoakSession()
    input_queue: DropOldestAsyncQueue[object] = DropOldestAsyncQueue(4)
    output_queue: DropOldestAsyncQueue[object] = DropOldestAsyncQueue(4)
    coordinator = RealtimeInterruptionCoordinator(session, input_queue, output_queue)
    cycles = 0
    errors: list[str] = []

    while time.monotonic() < deadline and (max_cycles is None or cycles < max_cycles):
        try:
            _exercise_state(machine)
            _exercise_vad()
            for index in range(6):
                input_queue.put_latest((cycles, index))
                output_queue.put_latest((cycles, index))
            result = await coordinator.interrupt()
            if not result.provider_notified or result.input_chunks_cleared != 4:
                raise RuntimeError("Realtime interruption invariant failed.")
            if result.output_chunks_cleared != 4:
                raise RuntimeError("Realtime output queue invariant failed.")
        except Exception as exc:
            errors.append(type(exc).__name__)
            break
        cycles += 1
        peak_rss = max(peak_rss, process.memory_info().rss)
        if cycle_pause_seconds:
            await asyncio.sleep(max(0.0, min(float(cycle_pause_seconds), 1.0)))

    elapsed = time.monotonic() - started
    rss_after = process.memory_info().rss
    growth_mib = max(0.0, (rss_after - rss_before) / 1024 / 1024)
    passed = not errors and cycles > 0 and growth_mib <= maximum_rss_growth_mib
    return {
        "schema_version": 1,
        "passed": passed,
        "started_at": started_wall.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(elapsed, 3),
        "cycles": cycles,
        "state_history_entries": len(machine.history),
        "interruptions": session.interruptions,
        "input_queue": input_queue.stats.__dict__,
        "output_queue": output_queue.stats.__dict__,
        "rss_before_mib": round(rss_before / 1024 / 1024, 1),
        "rss_after_mib": round(rss_after / 1024 / 1024, 1),
        "peak_rss_mib": round(peak_rss / 1024 / 1024, 1),
        "rss_growth_mib": round(growth_mib, 1),
        "maximum_rss_growth_mib": float(maximum_rss_growth_mib),
        "threads_before": threads_before,
        "threads_after": threading.active_count(),
        "errors": errors,
        "scope": "synthetic-local-voice-state-vad-queue",
        "acoustic_hardware_measured": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded local voice stability soak.")
    parser.add_argument("--duration-seconds", type=float, default=1800.0)
    parser.add_argument("--maximum-rss-growth-mib", type=float, default=96.0)
    parser.add_argument("--cycle-pause-seconds", type=float, default=0.01)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_soak(
            args.duration_seconds,
            maximum_rss_growth_mib=args.maximum_rss_growth_mib,
            cycle_pause_seconds=args.cycle_pause_seconds,
        )
    )
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
