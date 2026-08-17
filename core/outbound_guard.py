from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


_LOCK = threading.RLock()


def _path() -> Path:
    override = os.getenv("MISHA_DATA_DIR", "").strip()
    base = Path(override) if override and Path(override).is_absolute() else Path.home() / ".misha"
    return base / "outbound_messages.db"


def _fingerprint(platform: str, receiver: str, message: str) -> str:
    payload = "\0".join((platform.casefold(), receiver.casefold(), message)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db = path or _path()
    db.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(db.parent, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(db, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS outbound_messages ("
        "fingerprint TEXT PRIMARY KEY,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
    )
    conn.commit()
    try:
        os.chmod(db, 0o600)
    except OSError:
        pass
    return conn


def reserve(platform: str, receiver: str, message: str, *, allow_duplicate: bool = False, db_path: Path | None = None) -> tuple[bool, str]:
    fingerprint = _fingerprint(platform, receiver, message)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=5)
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT status,updated_at FROM outbound_messages WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if row is not None and not allow_duplicate:
            try:
                updated = datetime.fromisoformat(row["updated_at"])
            except ValueError:
                updated = now
            if updated >= cutoff:
                return False, fingerprint
        stamp = now.isoformat()
        conn.execute(
            "INSERT INTO outbound_messages(fingerprint,status,created_at,updated_at) VALUES(?, 'prepared', ?, ?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET status='prepared',updated_at=excluded.updated_at",
            (fingerprint, stamp, stamp),
        )
        conn.commit()
    return True, fingerprint


def finish(fingerprint: str, status: str, *, db_path: Path | None = None) -> None:
    accepted = status if status in {"sent_unverified", "blocked", "failed"} else "failed"
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE outbound_messages SET status=?,updated_at=? WHERE fingerprint=?",
            (accepted, datetime.now(timezone.utc).isoformat(), fingerprint),
        )
        conn.commit()


def status_for(fingerprint: str, *, db_path: Path | None = None) -> str | None:
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute("SELECT status FROM outbound_messages WHERE fingerprint=?", (fingerprint,)).fetchone()
    return str(row[0]) if row else None
