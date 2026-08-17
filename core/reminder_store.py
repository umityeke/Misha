from __future__ import annotations

import os
import re
import sqlite3
import threading
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core.credential_store import get_or_create_secret


_LOCK = threading.RLock()
_CIPHER: Fernet | None = None
REMINDER_ID = re.compile(r"rem_[0-9a-f]{16}")


def data_path() -> Path:
    override = os.getenv("MISHA_DATA_DIR", "").strip()
    base = Path(override) if override and Path(override).is_absolute() else Path.home() / ".misha"
    return base / "reminders.db"


def _cipher() -> Fernet:
    global _CIPHER
    if _CIPHER is None:
        key = get_or_create_secret("reminder-encryption-key", lambda: Fernet.generate_key().decode("ascii"))
        _CIPHER = Fernet(key.encode("ascii"))
    return _CIPHER


def _encrypt(value: str) -> str:
    return "enc:v1:" + _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    if not value.startswith("enc:v1:"):
        raise RuntimeError("Unencrypted reminder content was rejected.")
    try:
        return _cipher().decrypt(value[7:].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise RuntimeError("Reminder content authentication failed.") from exc


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db = path or data_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(db.parent, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(db, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA secure_delete=ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reminders ("
        "reminder_id TEXT PRIMARY KEY,message_cipher TEXT NOT NULL,local_iso TEXT NOT NULL,"
        "utc_iso TEXT NOT NULL,timezone TEXT NOT NULL,fold INTEGER NOT NULL,repeat_rule TEXT NOT NULL,"
        "scheduler_id TEXT NOT NULL,status TEXT NOT NULL,last_delivered_at TEXT,"
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    try:
        os.chmod(db, 0o600)
    except OSError:
        pass
    return conn


def create_reminder_record(
    *, message: str, local_iso: str, utc_iso: str, timezone: str, fold: int,
    repeat_rule: str, scheduler_id: str = "", db_path: Path | None = None,
) -> str:
    reminder_id = f"rem_{uuid.uuid4().hex[:16]}"
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO reminders(reminder_id,message_cipher,local_iso,utc_iso,timezone,fold,"
            "repeat_rule,scheduler_id,status) VALUES(?,?,?,?,?,?,?,?,'prepared')",
            (reminder_id, _encrypt(message), local_iso, utc_iso, timezone, int(fold), repeat_rule, scheduler_id),
        )
        conn.commit()
    return reminder_id


def set_scheduled(reminder_id: str, scheduler_id: str, *, db_path: Path | None = None) -> None:
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE reminders SET scheduler_id=?,status='scheduled',updated_at=CURRENT_TIMESTAMP "
            "WHERE reminder_id=?", (scheduler_id, reminder_id),
        )
        conn.commit()


def mark_failed(reminder_id: str, *, db_path: Path | None = None) -> None:
    with _LOCK, _connect(db_path) as conn:
        conn.execute("UPDATE reminders SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE reminder_id=?", (reminder_id,))
        conn.commit()


def get_reminder(reminder_id: str, *, db_path: Path | None = None) -> dict | None:
    if not REMINDER_ID.fullmatch(str(reminder_id)):
        return None
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM reminders WHERE reminder_id=?", (reminder_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["message"] = _decrypt(item.pop("message_cipher"))
    return item


def list_reminders(*, include_terminal: bool = False, limit: int = 100, db_path: Path | None = None) -> list[dict]:
    where = "" if include_terminal else "WHERE status IN ('prepared','scheduled')"
    with _LOCK, _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM reminders {where} ORDER BY utc_iso LIMIT ?", (max(1, min(int(limit), 200)),)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["message"] = _decrypt(item.pop("message_cipher"))
        result.append(item)
    return result


def mark_delivered(reminder_id: str, delivered_at: str, *, db_path: Path | None = None) -> None:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT repeat_rule FROM reminders WHERE reminder_id=?", (reminder_id,)).fetchone()
        if row is None:
            return
        status = "delivered" if row[0] == "none" else "scheduled"
        conn.execute(
            "UPDATE reminders SET status=?,last_delivered_at=?,updated_at=CURRENT_TIMESTAMP WHERE reminder_id=?",
            (status, delivered_at, reminder_id),
        )
        conn.commit()


def mark_deleted(reminder_id: str, *, db_path: Path | None = None) -> bool:
    with _LOCK, _connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE reminders SET status='deleted',updated_at=CURRENT_TIMESTAMP "
            "WHERE reminder_id=? AND status!='deleted'", (reminder_id,),
        )
        conn.commit()
    return cursor.rowcount > 0
