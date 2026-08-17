from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class VoiceSessionState(str, Enum):
    IDLE = "idle"
    WAKE_DETECTED = "wake_detected"
    VERIFYING_SPEAKER = "verifying_speaker"
    LISTENING = "listening"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    RESPONDING = "responding"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    ERROR = "error"


_NORMAL_TRANSITIONS = {
    VoiceSessionState.IDLE: {
        VoiceSessionState.WAKE_DETECTED,
        VoiceSessionState.PAUSED,
    },
    VoiceSessionState.WAKE_DETECTED: {
        VoiceSessionState.VERIFYING_SPEAKER,
        VoiceSessionState.IDLE,
    },
    VoiceSessionState.VERIFYING_SPEAKER: {
        VoiceSessionState.LISTENING,
        VoiceSessionState.IDLE,
    },
    VoiceSessionState.LISTENING: {
        VoiceSessionState.UNDERSTANDING,
        VoiceSessionState.IDLE,
    },
    VoiceSessionState.UNDERSTANDING: {
        VoiceSessionState.PLANNING,
        VoiceSessionState.RESPONDING,
    },
    VoiceSessionState.PLANNING: {
        VoiceSessionState.AWAITING_APPROVAL,
        VoiceSessionState.EXECUTING,
        VoiceSessionState.RESPONDING,
    },
    VoiceSessionState.AWAITING_APPROVAL: {
        VoiceSessionState.EXECUTING,
        VoiceSessionState.RESPONDING,
    },
    VoiceSessionState.EXECUTING: {
        VoiceSessionState.VERIFYING,
        VoiceSessionState.RECOVERING,
        VoiceSessionState.RESPONDING,
        VoiceSessionState.PLANNING,
    },
    VoiceSessionState.VERIFYING: {
        VoiceSessionState.EXECUTING,
        VoiceSessionState.RECOVERING,
        VoiceSessionState.RESPONDING,
    },
    VoiceSessionState.RECOVERING: {
        VoiceSessionState.EXECUTING,
        VoiceSessionState.PLANNING,
        VoiceSessionState.RESPONDING,
    },
    VoiceSessionState.RESPONDING: {
        VoiceSessionState.LISTENING,
        VoiceSessionState.IDLE,
    },
    VoiceSessionState.PAUSED: {
        VoiceSessionState.IDLE,
    },
    VoiceSessionState.CANCELLED: {
        VoiceSessionState.IDLE,
    },
    VoiceSessionState.ERROR: {
        VoiceSessionState.IDLE,
    },
}


@dataclass(frozen=True)
class StateTransition:
    previous: VoiceSessionState
    current: VoiceSessionState
    reason: str
    created_at: str


class VoiceStateMachine:
    def __init__(self, *, history_limit: int = 2048) -> None:
        if not 64 <= int(history_limit) <= 10_000:
            raise ValueError("Voice history limit must be between 64 and 10000.")
        self._state = VoiceSessionState.IDLE
        self._history: deque[StateTransition] = deque(maxlen=int(history_limit))
        self._lock = threading.RLock()

    @property
    def state(self) -> VoiceSessionState:
        with self._lock:
            return self._state

    @property
    def history(self) -> tuple[StateTransition, ...]:
        with self._lock:
            return tuple(self._history)

    def can_transition(self, target: VoiceSessionState) -> bool:
        with self._lock:
            if target in {VoiceSessionState.CANCELLED, VoiceSessionState.ERROR}:
                return self._state not in {
                    VoiceSessionState.CANCELLED,
                    VoiceSessionState.ERROR,
                }
            return target in _NORMAL_TRANSITIONS[self._state]

    def transition(
        self,
        target: VoiceSessionState,
        reason: str = "",
    ) -> StateTransition:
        with self._lock:
            if target == self._state:
                raise ValueError(f"Voice state is already {target.value}.")
            if not self.can_transition(target):
                raise ValueError(
                    f"Invalid voice transition: {self._state.value} -> {target.value}"
                )
            transition = StateTransition(
                previous=self._state,
                current=target,
                reason=reason.strip(),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._state = target
            self._history.append(transition)
            return transition
