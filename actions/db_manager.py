from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from actions.developer_tools import _workspace_path, selected_workspace


_READ_PREFIXES = ("SELECT", "EXPLAIN", "WITH")
_MUTATION_PREFIXES = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")


def _statement(value: object, *, read_only: bool) -> str:
    statement = str(value or "").strip()
    if not statement or "\x00" in statement or len(statement) > 32_000:
        raise ValueError("SQL statement must contain 1-32000 safe characters.")
    normalized = statement.lstrip().upper()
    prefixes = _READ_PREFIXES if read_only else _MUTATION_PREFIXES
    if not normalized.startswith(prefixes):
        raise ValueError("SQL operation is outside the allowlisted statement class.")
    if normalized.startswith("WITH") and not read_only:
        raise ValueError("Mutation CTEs are not supported.")
    return statement


def _database(parameters: dict) -> Path:
    workspace = selected_workspace(str(parameters.get("workspace", "")))
    path = _workspace_path(workspace, str(parameters.get("db_path", "")), must_exist=True)
    if path.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("Database must use a .db, .sqlite, or .sqlite3 extension.")
    return path


def read_query(path: Path, query: str) -> list[list[object]]:
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=3) as connection:
        connection.execute("PRAGMA query_only=ON")
        cursor = connection.execute(_statement(query, read_only=True))
        rows = cursor.fetchmany(101)
    if len(rows) > 100:
        raise ValueError("Database query exceeds the 100-row result limit.")
    return [list(row) for row in rows]


def _schema(path: Path) -> list[list[object]]:
    return read_query(
        path,
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE type IN ('table','index','view') ORDER BY type, name",
    )


def _execute_verified(path: Path, query: str, verify_query: str, expected: object) -> int:
    mutation = _statement(query, read_only=False)
    verification = _statement(verify_query, read_only=True)
    connection = sqlite3.connect(path, timeout=3)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(mutation)
        actual = [list(row) for row in connection.execute(verification).fetchmany(101)]
        if len(actual) > 100 or actual != expected:
            connection.rollback()
            raise ValueError("Database mutation verification failed; transaction rolled back.")
        changes = max(0, int(cursor.rowcount))
        connection.commit()
        return changes
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def db_manager(parameters: dict | None = None, player=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "query")).strip().casefold()
    try:
        path = _database(params)
        if player:
            player.write_log(f"SYS: DB Action: {action} on {path.name}")
        if action == "schema":
            return "Database result: " + json.dumps(_schema(path), ensure_ascii=False)
        if action == "query":
            rows = read_query(path, str(params.get("query", "")))
            return "Database result: " + json.dumps(rows, ensure_ascii=False)
        if action == "execute":
            verify_query = str(params.get("verify_query", "")).strip()
            expected_text = str(params.get("expected_json", "")).strip()
            if not verify_query or not expected_text:
                return "Database mutation blocked: verify_query and expected_json are required."
            expected = json.loads(expected_text)
            if not isinstance(expected, list):
                return "Database mutation blocked: expected_json must be a JSON row array."
            changes = _execute_verified(
                path, str(params.get("query", "")), verify_query, expected
            )
            return f"Database mutation committed and verified: changes={changes}."
        return f"Unknown db action: {action}"
    except (OSError, sqlite3.Error, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return f"Database error: {exc}"
