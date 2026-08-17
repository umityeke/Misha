from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


LEARNING_DB_PATH = Path.home() / ".misha" / "learning.db"
MAX_RULE_LENGTH = 600
_LOCK = threading.RLock()
_SENSITIVE_RE = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|parola|şifre|secret)\s*[:=]"
)


def _connect() -> sqlite3.Connection:
    LEARNING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LEARNING_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learned_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'global',
            source TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(rule, scope)
        )
        """
    )
    conn.commit()
    try:
        os.chmod(LEARNING_DB_PATH, 0o600)
    except OSError:
        pass
    return conn


def _validate_rule(rule: str) -> str:
    normalized = " ".join(str(rule).split()).strip()
    if not normalized:
        raise ValueError("Learning rule cannot be empty.")
    if len(normalized) > MAX_RULE_LENGTH:
        raise ValueError(f"Learning rule exceeds {MAX_RULE_LENGTH} characters.")
    if _SENSITIVE_RE.search(normalized):
        raise ValueError("Secrets and credentials cannot be stored as learning rules.")
    return normalized


def add_rule(rule: str, scope: str = "global", source: str = "user") -> str:
    normalized = _validate_rule(rule)
    normalized_scope = " ".join(str(scope).split()).strip() or "global"
    if len(normalized_scope) > 120:
        raise ValueError("Learning scope is too long.")
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO learned_rules (rule, scope, source, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(rule, scope) DO UPDATE SET
                status='active', source=excluded.source, updated_at=excluded.updated_at
            """,
            (normalized, normalized_scope, source, now, now),
        )
        conn.commit()
    return f"Learned rule for {normalized_scope}: {normalized}"


def list_rules(scope: str | None = None, limit: int = 100) -> list[dict]:
    safe_limit = max(1, min(int(limit), 200))
    query = (
        "SELECT id, rule, scope, source, created_at, updated_at "
        "FROM learned_rules WHERE status='active'"
    )
    params: list[object] = []
    if scope:
        query += " AND (scope='global' OR scope=?)"
        params.append(scope)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(safe_limit)
    with _LOCK, _connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def format_rules_for_prompt(scope: str | None = None, limit: int = 40) -> str:
    rules = list_rules(scope=scope, limit=limit)
    if not rules:
        return ""
    lines = ["[USER-TAUGHT OPERATING RULES — follow unless unsafe or superseded]"]
    for item in reversed(rules):
        lines.append(f"- ({item['scope']}) {item['rule']}")
    return "\n".join(lines)
