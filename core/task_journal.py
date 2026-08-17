from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core.credential_store import get_or_create_secret


_ACTIVE_PHASES = frozenset({
    "planning", "awaiting_approval", "executing", "verifying", "recovering",
    "responding",
})
_TERMINAL_PHASES = frozenset({
    "succeeded", "failed", "cancelled", "rejected", "timed_out", "unverified",
    "partial", "dismissed",
})


def _default_path() -> Path:
    override = os.getenv("MISHA_DATA_DIR", "").strip()
    base = Path(override) if override and Path(override).is_absolute() else Path.home() / ".misha"
    return base / "task_journal.db"


@dataclass(frozen=True)
class TaskSnapshot:
    request_id: str
    goal: str
    phase: str
    completed_steps: int
    total_steps: int
    external_effect_seen: bool
    created_at: str
    updated_at: str


def _cipher_from_keychain() -> Fernet:
    key = get_or_create_secret(
        "task-journal-encryption-key",
        lambda: Fernet.generate_key().decode("ascii"),
    )
    try:
        return Fernet(key.encode("ascii"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Task recovery encryption key is invalid.") from exc


class TaskJournal:
    """Encrypted, local task checkpoints. Never resumes effects automatically."""

    def __init__(self, path: Path | None = None, *, cipher: Fernet | None = None):
        self.path = Path(path) if path is not None else _default_path()
        self._cipher = cipher or _cipher_from_keychain()
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA secure_delete=ON")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS task_journal ("
                "request_id TEXT PRIMARY KEY, goal_cipher TEXT NOT NULL, phase TEXT NOT NULL, "
                "completed_steps INTEGER NOT NULL DEFAULT 0, total_steps INTEGER NOT NULL DEFAULT 0, "
                "external_effect_seen INTEGER NOT NULL DEFAULT 0, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _encrypt(self, value: str) -> str:
        bounded = " ".join(str(value).split()).strip()[:2_000]
        return "enc:v1:" + self._cipher.encrypt(bounded.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        if not str(value).startswith("enc:v1:"):
            raise RuntimeError("Unencrypted task recovery content was rejected.")
        try:
            return self._cipher.decrypt(str(value)[7:].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("Task recovery content could not be authenticated.") from exc

    def start(self, request_id: str, goal: str) -> None:
        task_id = str(request_id).strip()
        if not task_id or len(task_id) > 128:
            raise ValueError("A bounded request ID is required for task recovery.")
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO task_journal(request_id,goal_cipher,phase,created_at,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(request_id) DO NOTHING",
                (task_id, self._encrypt(goal), "planning", now, now),
            )
            conn.commit()

    def set_phase(
        self,
        request_id: str,
        phase: str,
        *,
        completed_steps: int | None = None,
        total_steps: int | None = None,
        external_effect_seen: bool | None = None,
    ) -> None:
        normalized = str(phase).strip().lower()
        if normalized not in _ACTIVE_PHASES | _TERMINAL_PHASES | {"interrupted"}:
            raise ValueError("Unsupported task journal phase.")
        assignments = ["phase=?", "updated_at=?"]
        values: list[object] = [normalized, self._now()]
        if completed_steps is not None:
            assignments.append("completed_steps=?")
            values.append(max(0, int(completed_steps)))
        if total_steps is not None:
            assignments.append("total_steps=?")
            values.append(max(0, int(total_steps)))
        if external_effect_seen is not None:
            assignments.append("external_effect_seen=?")
            values.append(1 if external_effect_seen else 0)
        values.append(str(request_id))
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE task_journal SET {', '.join(assignments)} WHERE request_id=?",
                tuple(values),
            )
            conn.commit()

    def recover_interrupted(self) -> tuple[TaskSnapshot, ...]:
        """Mark orphaned active work interrupted and return user-review records."""
        with self._lock, self._connect() as conn:
            placeholders = ",".join("?" for _ in _ACTIVE_PHASES)
            conn.execute(
                f"UPDATE task_journal SET phase='interrupted',updated_at=? "
                f"WHERE phase IN ({placeholders})",
                (self._now(), *sorted(_ACTIVE_PHASES)),
            )
            rows = conn.execute(
                "SELECT * FROM task_journal WHERE phase IN ('interrupted','partial') "
                "ORDER BY updated_at DESC LIMIT 50"
            ).fetchall()
            conn.commit()
        return tuple(self._snapshot(row) for row in rows)

    def dismiss(self, request_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE task_journal SET phase='dismissed',updated_at=? "
                "WHERE request_id=? AND phase IN ('interrupted','partial')",
                (self._now(), str(request_id)),
            )
            conn.commit()
            return cursor.rowcount == 1

    def purge_old_terminal(self, days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
        phases = tuple(sorted(_TERMINAL_PHASES))
        placeholders = ",".join("?" for _ in phases)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM task_journal WHERE phase IN ({placeholders}) AND updated_at<?",
                (*phases, cutoff),
            )
            conn.commit()
            return cursor.rowcount

    def _snapshot(self, row: sqlite3.Row) -> TaskSnapshot:
        return TaskSnapshot(
            request_id=str(row["request_id"]),
            goal=self._decrypt(row["goal_cipher"]),
            phase=str(row["phase"]),
            completed_steps=int(row["completed_steps"]),
            total_steps=int(row["total_steps"]),
            external_effect_seen=bool(row["external_effect_seen"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
