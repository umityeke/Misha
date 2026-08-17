from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any
import uuid

from dotenv import load_dotenv

try:
    import psycopg2
except ImportError:
    psycopg2 = None


load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
REMOTE_AUDIT_ENABLED = os.getenv("MISHA_REMOTE_AUDIT_ENABLED", "0").lower() in {
    "1", "true", "yes", "on"
}
AUDIT_DB_PATH = Path.home() / ".misha" / "audit.db"
_LOCK = threading.RLock()

_SECRET_KEYS = {
    "api_key", "apikey", "authorization", "cookie", "credential", "password",
    "refresh_token", "secret", "token",
}
_PRIVATE_KEYS = {
    "content", "message", "message_text", "output", "prompt", "rule", "selection",
    "text",
}
_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*[^\s,;]+"
)
_PATH_RE = re.compile(r"(?<![\w])(?:/Users|/home|/private|/tmp)/[^\s,'\"}\]]+")


@dataclass(frozen=True)
class AuditEvent:
    category: str
    action: str
    status: str
    request_id: str = ""
    tool: str = ""
    risk: str = ""
    duration_seconds: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _private_summary(value: Any) -> str:
    raw = str(value)
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"[PRIVATE length={len(raw)} sha256={digest}]"


def redact(value: Any, *, redact_paths: bool = True, key: str = "") -> Any:
    normalized_key = key.casefold()
    if normalized_key in _SECRET_KEYS or any(
        marker in normalized_key for marker in ("password", "secret", "token", "api_key")
    ):
        return "[REDACTED]"
    if normalized_key in _PRIVATE_KEYS:
        return _private_summary(value)
    if isinstance(value, dict):
        return {
            str(item_key): redact(item, redact_paths=redact_paths, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, redact_paths=redact_paths) for item in value]
    if isinstance(value, str):
        cleaned = _SECRET_VALUE_RE.sub("[REDACTED]", value)
        return _PATH_RE.sub("[PATH]", cleaned) if redact_paths else cleaned
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _private_summary(value)


def _retention_days() -> int:
    try:
        value = int(os.getenv("MISHA_AUDIT_RETENTION_DAYS", "30"))
    except ValueError:
        value = 30
    return max(1, min(value, 365))


def _connect_local() -> sqlite3.Connection:
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(AUDIT_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            category TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            request_id TEXT NOT NULL,
            tool TEXT NOT NULL,
            risk TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            details_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp)"
    )
    connection.commit()
    try:
        os.chmod(AUDIT_DB_PATH, 0o600)
    except OSError:
        pass
    return connection


def _get_conn():
    if psycopg2 is None:
        raise RuntimeError(
            "Remote audit logging requires the remote extra: pip install '.[remote]'"
        )
    if not REMOTE_AUDIT_ENABLED:
        raise RuntimeError("Remote audit logging requires explicit opt-in.")
    if not DATABASE_URL:
        raise RuntimeError("Remote audit logging is disabled because DATABASE_URL is unset.")
    return psycopg2.connect(DATABASE_URL, connect_timeout=3)


def _store_local(event: AuditEvent, details: dict[str, Any]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_retention_days())).isoformat()
    with _LOCK, _connect_local() as connection:
        connection.execute("DELETE FROM audit_events WHERE timestamp < ?", (cutoff,))
        connection.execute(
            """
            INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id, event.timestamp, event.category, event.action,
                event.status, event.request_id, event.tool, event.risk,
                event.duration_seconds,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
            ),
        )


def _store_remote(event: AuditEvent, details: dict[str, Any]) -> None:
    if not REMOTE_AUDIT_ENABLED:
        return
    connection = _get_conn()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY, timestamp TIMESTAMPTZ NOT NULL,
                    category TEXT, action TEXT, status TEXT, request_id TEXT,
                    tool TEXT, risk TEXT, duration_seconds DOUBLE PRECISION,
                    details_json JSONB
                )
                """
            )
            cursor.execute(
                "INSERT INTO audit_events VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    event.event_id, event.timestamp, event.category, event.action,
                    event.status, event.request_id, event.tool, event.risk,
                    event.duration_seconds, json.dumps(details, ensure_ascii=False),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def log_event(event: AuditEvent, *, redact_paths: bool = True) -> bool:
    """Fail-soft audit write; never changes whether a tool may execute."""
    try:
        details = redact(event.details, redact_paths=redact_paths)
        _store_local(event, details)
        try:
            _store_remote(event, details)
        except Exception:
            pass
        return True
    except Exception:
        return False


def log_action(action_name: str, parameters: dict, status: str, output: str) -> bool:
    """Backward-compatible adapter for legacy callers."""
    return log_event(AuditEvent(
        category="legacy_action",
        action=str(action_name)[:120],
        status=str(status)[:40],
        details={"parameters": parameters, "output": output},
    ))


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    with _LOCK, _connect_local() as connection:
        rows = connection.execute(
            "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json"))
        result.append(item)
    return result


def clear_events() -> int:
    with _LOCK, _connect_local() as connection:
        count = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        connection.execute("DELETE FROM audit_events")
    return int(count)
