from __future__ import annotations

import re
import os
import sqlite3
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


_WAKE_RE = re.compile(r"^(?:(?:hey|selam|merhaba)\s+)?(?:misha|misa)\b", re.IGNORECASE)
DEFAULT_WAKE_METRICS_PATH = Path.home() / ".misha" / "voice_metrics.db"


def _normalize(text: str) -> str:
    folded = text.casefold().replace("ı", "i").replace("ş", "s")
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", folded)
        if not unicodedata.combining(char)
    )


@dataclass(frozen=True)
class WakeWordMatch:
    detected: bool
    command: str


@dataclass(frozen=True)
class WakeGuardDecision:
    allowed: bool
    reason: str = ""


class WakeGuard:
    """Bounds repeated wake triggers without storing utterance content."""

    def __init__(
        self,
        *,
        cooldown_seconds: float = 1.5,
        window_seconds: float = 10.0,
        max_triggers: int = 4,
    ) -> None:
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.window_seconds = max(1.0, float(window_seconds))
        self.max_triggers = max(1, int(max_triggers))
        self._accepted: deque[float] = deque()
        self._lock = threading.Lock()

    def evaluate(
        self,
        *,
        now: float | None = None,
        bypass_cooldown: bool = False,
    ) -> WakeGuardDecision:
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            while self._accepted and timestamp - self._accepted[0] > self.window_seconds:
                self._accepted.popleft()
            if (
                not bypass_cooldown
                and self._accepted
                and timestamp - self._accepted[-1] < self.cooldown_seconds
            ):
                return WakeGuardDecision(False, "cooldown")
            if len(self._accepted) >= self.max_triggers:
                return WakeGuardDecision(False, "rate_limit")
            self._accepted.append(timestamp)
        return WakeGuardDecision(True)


class WakeMetrics:
    """Stores aggregate local wake counters; never transcripts or audio."""

    ALLOWED_EVENTS = {
        "verified_no_wake",
        "wake_detected",
        "wake_suppressed",
        "command_dispatched",
    }

    def __init__(self, path: str | Path = DEFAULT_WAKE_METRICS_PATH) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS wake_counts ("
            "day TEXT NOT NULL, event TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY(day, event))"
        )
        connection.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return connection

    def record(self, event: str, *, occurred_at: datetime | None = None) -> None:
        if event not in self.ALLOWED_EVENTS:
            raise ValueError("Unsupported wake metric event.")
        moment = occurred_at or datetime.now(timezone.utc)
        day = moment.astimezone(timezone.utc).date().isoformat()
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "INSERT INTO wake_counts(day, event, count) VALUES (?, ?, 1) "
                    "ON CONFLICT(day, event) DO UPDATE SET count=count+1",
                    (day, event),
                )
                connection.commit()
        except (OSError, sqlite3.Error):
            return

    def snapshot(self, *, days: int = 1) -> dict[str, int]:
        safe_days = max(1, min(int(days), 90))
        first_day = (
            datetime.now(timezone.utc).date() - timedelta(days=safe_days - 1)
        ).isoformat()
        try:
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    "SELECT event, SUM(count) FROM wake_counts WHERE day >= ? GROUP BY event",
                    (first_day,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return {}
        return {str(event): int(count) for event, count in rows}


def match_wake_word(transcript: str) -> WakeWordMatch:
    original = " ".join(str(transcript).split()).strip()
    if not original:
        return WakeWordMatch(False, "")
    normalized = _normalize(original)
    match = _WAKE_RE.match(normalized)
    if not match:
        return WakeWordMatch(False, "")
    remainder = original[match.end():]
    if remainder.startswith(("'", "’")):
        return WakeWordMatch(False, "")
    # Normalization preserves character count for the supported Turkish forms.
    command = remainder.lstrip(" ,.:;!?—-").strip()
    return WakeWordMatch(True, command)
