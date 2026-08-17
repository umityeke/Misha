from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from core.credential_store import get_or_create_secret

try:
    import psycopg2
except ImportError:  # Optional legacy remote adapter only.
    psycopg2 = None

MEMORY_DB_PATH = Path.home() / ".misha" / "memory.db"
LEGACY_MEMORY_PATH = Path.home() / ".misha" / "memory" / "long_term.json"
SCHEMA_VERSION = 2
MAX_VALUE_LENGTH = 4_000
MAX_METADATA_LENGTH = 2_000
_LOCK = threading.RLock()
_MEMORY_CIPHER: Fernet | None = None


class MemoryKind(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    DECISION = "decision"
    LONG_TERM = "long_term"


RETENTION_DAYS: dict[MemoryKind, int | None] = {
    MemoryKind.WORKING: 7,
    MemoryKind.EPISODIC: 30,
    MemoryKind.DECISION: 365,
    MemoryKind.LONG_TERM: None,
}
MAX_ENTRIES = {
    MemoryKind.WORKING: 200,
    MemoryKind.EPISODIC: 2_000,
    MemoryKind.DECISION: 1_000,
    MemoryKind.LONG_TERM: 500,
}
_SENSITIVE_PATTERNS = (
    ("private_key", re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("credential", re.compile(r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|parola|şifre|secret)\s*[:=]\s*\S+")),
    ("provider_token", re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{12,}\b")),
    ("github_token", re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("payment_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
)


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    kind: str
    key: str
    category: str
    value: str
    metadata: dict[str, Any]
    source: str
    created_at: str
    updated_at: str
    expires_at: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _normalize_kind(kind: MemoryKind | str) -> MemoryKind:
    try:
        return kind if isinstance(kind, MemoryKind) else MemoryKind(str(kind))
    except ValueError as exc:
        raise ValueError(f"Unknown memory kind: {kind}") from exc


def classify_sensitive(value: str) -> list[str]:
    return [name for name, pattern in _SENSITIVE_PATTERNS if pattern.search(str(value))]


def _validate_text(value: Any, *, field: str, maximum: int) -> str:
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        raise ValueError(f"Memory {field} cannot be empty.")
    if len(normalized) > maximum:
        raise ValueError(f"Memory {field} exceeds {maximum} characters.")
    return normalized


def _validate_value(value: Any, source: str) -> str:
    normalized = _validate_text(value, field="value", maximum=MAX_VALUE_LENGTH)
    labels = classify_sensitive(normalized)
    if labels:
        raise ValueError(f"Forbidden sensitive data cannot be stored in memory: {', '.join(labels)}")
    if source == "model" and re.search(
        r"(?i)\b(?:one[- ]time code|verification code|recovery code|seed phrase|tc kimlik|ssn)\b",
        normalized,
    ):
        raise ValueError("The model may not automatically store authentication or government identity data.")
    return normalized


def _get_cipher() -> Fernet:
    global _MEMORY_CIPHER
    if _MEMORY_CIPHER is None:
        key = get_or_create_secret(
            "memory-encryption-key",
            lambda: Fernet.generate_key().decode("ascii"),
        )
        try:
            _MEMORY_CIPHER = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("The Keychain memory key is invalid; encrypted memory is locked.") from exc
    return _MEMORY_CIPHER


def _encrypt_text(value: str) -> str:
    return "enc:v1:" + _get_cipher().encrypt(str(value).encode("utf-8")).decode("ascii")


def _decrypt_text(value: str) -> str:
    text = str(value)
    if not text.startswith("enc:v1:"):
        raise RuntimeError("Unencrypted memory content was rejected.")
    try:
        return _get_cipher().decrypt(text[7:].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("Encrypted memory could not be authenticated; access was denied.") from exc


def _blind_index(field: str, value: str) -> str:
    cipher = _get_cipher()
    raw_key = cipher._signing_key + cipher._encryption_key
    return hmac.new(raw_key, f"{field}\0{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def _migrate_encryption(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
    needs_migration = "encrypted" not in columns
    if not needs_migration:
        needs_migration = bool(
            conn.execute("SELECT 1 FROM memories WHERE encrypted!=1 LIMIT 1").fetchone()
        )
    if needs_migration:
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA secure_delete=ON")
    if "key_hash" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN key_hash TEXT")
    if "category_hash" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN category_hash TEXT")
    if "encrypted" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN encrypted INTEGER NOT NULL DEFAULT 0")
    rows = conn.execute(
        "SELECT id,key,category,value,metadata_json FROM memories WHERE encrypted=0"
    ).fetchall()
    for row in rows:
        key = str(row["key"])
        category = str(row["category"])
        conn.execute(
            "UPDATE memories SET key=?,category=?,value=?,metadata_json=?,key_hash=?,category_hash=?,encrypted=1 WHERE id=?",
            (
                _encrypt_text(key), _encrypt_text(category), _encrypt_text(str(row["value"])),
                _encrypt_text(str(row["metadata_json"])), _blind_index("key", key),
                _blind_index("category", category), row["id"],
            ),
        )
    remaining = conn.execute("SELECT COUNT(*) FROM memories WHERE encrypted!=1").fetchone()[0]
    if remaining:
        raise RuntimeError("Plaintext memory migration was incomplete; access was denied.")
    if rows:
        conn.commit()
        conn.execute("VACUUM")


def _connect() -> sqlite3.Connection:
    MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MEMORY_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('working','episodic','decision','long_term')),
            key TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            value TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL CHECK(source IN ('user','model','system','import','legacy')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            key_hash TEXT NOT NULL,
            category_hash TEXT NOT NULL,
            encrypted INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    _migrate_encryption(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_kind_updated ON memories(kind, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_expiry ON memories(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_lookup ON memories(kind,key_hash,category_hash)")
    conn.execute(
        "INSERT INTO schema_meta(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    try:
        os.chmod(MEMORY_DB_PATH, 0o600)
    except OSError:
        pass
    return conn


@contextmanager
def _connection():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    try:
        key = _decrypt_text(row["key"])
        category = _decrypt_text(row["category"])
        value = _decrypt_text(row["value"])
        metadata = json.loads(_decrypt_text(row["metadata_json"]))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Encrypted memory metadata is invalid; access was denied.") from exc
    return MemoryRecord(
        id=row["id"], kind=row["kind"], key=key, category=category,
        value=value, metadata=metadata if isinstance(metadata, dict) else {},
        source=row["source"], created_at=row["created_at"], updated_at=row["updated_at"],
        expires_at=row["expires_at"],
    )


def purge_expired() -> int:
    with _LOCK, _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?", (_iso(_now()),)
        )
        conn.commit()
        return cursor.rowcount


def _enforce_size_limit(conn: sqlite3.Connection, kind: MemoryKind) -> None:
    count = conn.execute("SELECT COUNT(*) FROM memories WHERE kind=?", (kind.value,)).fetchone()[0]
    overflow = count - MAX_ENTRIES[kind]
    if overflow > 0:
        conn.execute(
            "DELETE FROM memories WHERE id IN "
            "(SELECT id FROM memories WHERE kind=? ORDER BY updated_at ASC LIMIT ?)",
            (kind.value, overflow),
        )


def put_memory(
    kind: MemoryKind | str,
    key: str,
    value: Any,
    *,
    category: str = "",
    metadata: dict[str, Any] | None = None,
    source: str = "user",
    replace: bool | None = None,
) -> MemoryRecord:
    memory_kind = _normalize_kind(kind)
    safe_key = _validate_text(key, field="key", maximum=160)
    safe_category = " ".join(str(category).split()).strip()[:120]
    safe_source = str(source).strip().lower()
    if safe_source not in {"user", "model", "system", "import", "legacy"}:
        raise ValueError("Unknown memory source.")
    safe_value = _validate_value(value, safe_source)
    safe_metadata = metadata or {}
    if not isinstance(safe_metadata, dict):
        raise ValueError("Memory metadata must be an object.")
    metadata_json = json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True)
    if len(metadata_json) > MAX_METADATA_LENGTH or classify_sensitive(metadata_json):
        raise ValueError("Memory metadata is too large or contains sensitive data.")
    now = _now()
    retention = RETENTION_DAYS[memory_kind]
    expires_at = _iso(now + timedelta(days=retention)) if retention else None
    should_replace = replace if replace is not None else memory_kind in {
        MemoryKind.WORKING, MemoryKind.LONG_TERM,
    }

    with _LOCK, _connection() as conn:
        conn.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?", (_iso(now),))
        existing = None
        if should_replace:
            existing = conn.execute(
                "SELECT id,created_at FROM memories WHERE kind=? AND category_hash=? AND key_hash=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (memory_kind.value, _blind_index("category", safe_category), _blind_index("key", safe_key)),
            ).fetchone()
        record_id = existing["id"] if existing else str(uuid.uuid4())
        created_at = existing["created_at"] if existing else _iso(now)
        if existing:
            conn.execute(
                "UPDATE memories SET key=?,category=?,value=?,metadata_json=?,key_hash=?,category_hash=?,"
                "encrypted=1,source=?,updated_at=?,expires_at=? WHERE id=?",
                (
                    _encrypt_text(safe_key), _encrypt_text(safe_category), _encrypt_text(safe_value),
                    _encrypt_text(metadata_json), _blind_index("key", safe_key),
                    _blind_index("category", safe_category), safe_source, _iso(now), expires_at, record_id,
                ),
            )
        else:
            conn.execute(
                "INSERT INTO memories(id,kind,key,category,value,metadata_json,source,created_at,updated_at,expires_at,"
                "key_hash,category_hash,encrypted) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    record_id, memory_kind.value, _encrypt_text(safe_key), _encrypt_text(safe_category),
                    _encrypt_text(safe_value), _encrypt_text(metadata_json), safe_source, created_at,
                    _iso(now), expires_at, _blind_index("key", safe_key), _blind_index("category", safe_category),
                ),
            )
        _enforce_size_limit(conn, memory_kind)
        row = conn.execute("SELECT * FROM memories WHERE id=?", (record_id,)).fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("Memory entry was evicted by the configured size limit.")
    return _row_to_record(row)


def get_memory(record_id: str) -> MemoryRecord | None:
    purge_expired()
    with _LOCK, _connection() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id=?", (str(record_id),)).fetchone()
    return _row_to_record(row) if row else None


def list_memories(
    kind: MemoryKind | str | None = None,
    *,
    category: str | None = None,
    limit: int = 100,
) -> list[MemoryRecord]:
    purge_expired()
    safe_limit = max(1, min(int(limit), sum(MAX_ENTRIES.values())))
    clauses: list[str] = []
    params: list[Any] = []
    if kind is not None:
        clauses.append("kind=?")
        params.append(_normalize_kind(kind).value)
    if category is not None:
        clauses.append("category_hash=?")
        params.append(_blind_index("category", str(category)))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(safe_limit)
    with _LOCK, _connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM memories{where} ORDER BY updated_at DESC LIMIT ?", params
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def delete_memory(record_id: str) -> bool:
    with _LOCK, _connection() as conn:
        cursor = conn.execute("DELETE FROM memories WHERE id=?", (str(record_id),))
        conn.commit()
        return cursor.rowcount > 0


def delete_category(category: str, kind: MemoryKind | str | None = None) -> int:
    query = "DELETE FROM memories WHERE category_hash=?"
    params: list[Any] = [_blind_index("category", str(category))]
    if kind is not None:
        query += " AND kind=?"
        params.append(_normalize_kind(kind).value)
    with _LOCK, _connection() as conn:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.rowcount


def clear_memory(kind: MemoryKind | str | None = None) -> int:
    query = "DELETE FROM memories"
    params: tuple[Any, ...] = ()
    if kind is not None:
        query += " WHERE kind=?"
        params = (_normalize_kind(kind).value,)
    with _LOCK, _connection() as conn:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.rowcount


def export_memory(path: str | Path) -> int:
    target = Path(path).expanduser().resolve()
    if target == MEMORY_DB_PATH.resolve():
        raise ValueError("Export path cannot overwrite the memory database.")
    target.parent.mkdir(parents=True, exist_ok=True)
    records = [
        asdict(record)
        for kind in MemoryKind
        for record in list_memories(kind, limit=MAX_ENTRIES[kind])
    ]
    payload = {"format": "misha-memory", "version": 1, "exported_at": _iso(_now()), "records": records}
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    return len(records)


def import_memory(path: str | Path) -> dict[str, int]:
    source_path = Path(path).expanduser().resolve()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != "misha-memory" or payload.get("version") != 1:
        raise ValueError("Unsupported Misha memory export.")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) > sum(MAX_ENTRIES.values()):
        raise ValueError("Memory import contains too many or invalid records.")
    imported = rejected = 0
    for item in records:
        try:
            if not isinstance(item, dict):
                raise ValueError("Invalid record")
            put_memory(
                item["kind"], item["key"], item["value"], category=item.get("category", ""),
                metadata=item.get("metadata", {}), source="import",
                replace=item["kind"] in {MemoryKind.WORKING.value, MemoryKind.LONG_TERM.value},
            )
            imported += 1
        except (KeyError, TypeError, ValueError):
            rejected += 1
    return {"imported": imported, "rejected": rejected}


def migrate_legacy_json() -> dict[str, int]:
    """One-time, read-only import. The legacy file is never active storage."""
    with _LOCK, _connection() as conn:
        done = conn.execute("SELECT value FROM schema_meta WHERE key='legacy_json_migrated'").fetchone()
        if done:
            return {"imported": 0, "rejected": 0}
    imported = rejected = 0
    if LEGACY_MEMORY_PATH.exists():
        try:
            data = json.loads(LEGACY_MEMORY_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Legacy memory is not an object")
            for category, entries in data.items():
                if not isinstance(entries, dict):
                    continue
                for key, entry in entries.items():
                    try:
                        value = entry.get("value") if isinstance(entry, dict) else entry
                        put_memory(MemoryKind.LONG_TERM, key, value, category=category, source="legacy")
                        imported += 1
                    except (TypeError, ValueError):
                        rejected += 1
        except (OSError, ValueError, json.JSONDecodeError):
            rejected += 1
    with _LOCK, _connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('legacy_json_migrated',?)",
            (_iso(_now()),),
        )
        conn.commit()
    return {"imported": imported, "rejected": rejected}


# Compatibility facade for current callers.
SESSION_ID = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def set_working_memory(key: str, value: str) -> None:
    put_memory(MemoryKind.WORKING, key, value, source="system")


def get_working_memory(key: str) -> str | None:
    records = [r for r in list_memories(MemoryKind.WORKING, limit=200) if r.key == key]
    return records[0].value if records else None


def get_all_working_memory() -> dict[str, str]:
    return {record.key: record.value for record in reversed(list_memories(MemoryKind.WORKING, limit=200))}


def save_episode(role: str, content: str, session_id: str | None = None) -> None:
    put_memory(
        MemoryKind.EPISODIC, role, content, category=session_id or SESSION_ID,
        source="system", replace=False,
    )


def get_recent_episodes(limit: int = 20) -> list[dict[str, str]]:
    records = list(reversed(list_memories(MemoryKind.EPISODIC, limit=limit)))
    return [
        {"role": r.key, "content": r.value, "at": r.created_at, "session_id": r.category}
        for r in records
    ]


def save_decision(topic: str, decision: str, rationale: str = "") -> None:
    put_memory(
        MemoryKind.DECISION, topic, decision, metadata={"rationale": rationale},
        source="system", replace=False,
    )


def get_recent_decisions(limit: int = 10) -> list[dict[str, str]]:
    return [
        {"topic": r.key, "decision": r.value, "rationale": str(r.metadata.get("rationale", "")), "at": r.created_at}
        for r in list_memories(MemoryKind.DECISION, limit=limit)
    ]


def get_memory_summary() -> str:
    lines: list[str] = []
    working = get_all_working_memory()
    if working:
        lines.extend(["=== Working Memory ===", *(f"  {key}: {value}" for key, value in working.items())])
    decisions = get_recent_decisions(5)
    if decisions:
        lines.extend(["=== Recent Decisions ===", *(f"  [{d['at'][:10]}] {d['topic']}: {d['decision']}" for d in decisions)])
    episodes = get_recent_episodes(10)
    if episodes:
        lines.append("=== Recent Conversation ===")
        lines.extend(f"  [{ep['role']}]: {ep['content'][:120].replace(chr(10), ' ')}" for ep in episodes)
    return "\n".join(lines) if lines else "Memory is empty."


def _get_conn():
    """Legacy remote adapter retained only for explicit migration tooling."""
    if psycopg2 is None:
        raise RuntimeError("PostgreSQL memory requires the remote extra: pip install '.[remote]'")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("PostgreSQL memory is disabled because DATABASE_URL is unset.")
    return psycopg2.connect(database_url)
