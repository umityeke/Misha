from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core.credential_store import get_or_create_secret


_LOCK = threading.RLock()
_CIPHER: Fernet | None = None
_TX_ID = re.compile(r"tx_[0-9a-f]{16}")


def _data_path() -> Path:
    override = os.getenv("MISHA_DATA_DIR", "").strip()
    base = Path(override) if override and Path(override).is_absolute() else Path.home() / ".misha"
    return base / "file_transactions.db"


def _cipher() -> Fernet:
    global _CIPHER
    if _CIPHER is None:
        key = get_or_create_secret(
            "file-transaction-encryption-key",
            lambda: Fernet.generate_key().decode("ascii"),
        )
        _CIPHER = Fernet(key.encode("ascii"))
    return _CIPHER


def _encrypt(value: str) -> str:
    return "enc:v1:" + _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    if not str(value).startswith("enc:v1:"):
        raise RuntimeError("Unencrypted rollback snapshot was rejected.")
    try:
        return _cipher().decrypt(str(value)[7:].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Rollback snapshot authentication failed.") from exc


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db = path or _data_path()
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
        "CREATE TABLE IF NOT EXISTS file_transactions ("
        "tx_id TEXT PRIMARY KEY,path_cipher TEXT NOT NULL,before_cipher TEXT NOT NULL,"
        "existed_before INTEGER NOT NULL,after_sha256 TEXT NOT NULL,status TEXT NOT NULL,"
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(file_transactions)")}
    if "operation" not in columns:
        conn.execute(
            "ALTER TABLE file_transactions ADD COLUMN operation TEXT NOT NULL DEFAULT 'text_edit'"
        )
    if "secondary_cipher" not in columns:
        conn.execute(
            "ALTER TABLE file_transactions ADD COLUMN secondary_cipher TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()
    try:
        os.chmod(db, 0o600)
    except OSError:
        pass
    return conn


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _contains_symlink(path: Path, roots: list[Path]) -> bool:
    """Reject a target when any existing component below its allowed root is a link."""
    absolute = Path(os.path.abspath(path))
    for root in roots:
        root_absolute = root.resolve()
        try:
            relative = absolute.relative_to(root_absolute)
        except ValueError:
            continue
        current = root_absolute
        if current.is_symlink():
            return True
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False
    return True


def apply_text_edit(path: Path, content: str, *, db_path: Path | None = None) -> str:
    target = Path(path)
    before = target.read_bytes() if target.exists() else b""
    after = str(content).encode("utf-8")
    tx_id = f"tx_{uuid.uuid4().hex[:16]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO file_transactions(tx_id,path_cipher,before_cipher,existed_before,"
            "after_sha256,status) VALUES(?,?,?,?,?,'prepared')",
            (
                tx_id, _encrypt(str(target.resolve())),
                _encrypt(before.decode("utf-8", errors="strict")),
                1 if target.exists() else 0, _hash_bytes(after),
            ),
        )
        conn.commit()
        try:
            _atomic_write(target, after)
        except Exception:
            conn.execute("UPDATE file_transactions SET status='failed' WHERE tx_id=?", (tx_id,))
            conn.commit()
            raise
        else:
            conn.execute("UPDATE file_transactions SET status='applied' WHERE tx_id=?", (tx_id,))
            conn.commit()
    return tx_id


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_symlink():
        raise ValueError("Transactional paths cannot be symlinks.")
    if path.is_file():
        digest.update(b"file\0")
        digest.update(path.read_bytes())
        return digest.hexdigest()
    if not path.is_dir():
        raise ValueError("Transactional path is missing.")
    digest.update(b"directory\0")
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink():
            raise ValueError("Transactional directory cannot contain symlinks.")
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        if item.is_file():
            digest.update(item.read_bytes())
    return digest.hexdigest()


def apply_path_operation(
    operation: str,
    source: Path,
    destination: Path | None = None,
    *,
    db_path: Path | None = None,
) -> str:
    operation = str(operation).strip().casefold()
    if operation not in {"create_folder", "copy", "move", "rename"}:
        raise ValueError("Unsupported path transaction operation.")
    source = Path(source)
    destination = Path(destination) if destination is not None else None
    if operation == "create_folder":
        if source.exists() or destination is not None:
            raise ValueError("Folder transaction target must not already exist.")
        result_path = source
    else:
        if not source.exists() or destination is None or destination.exists():
            raise ValueError("Path transaction source/destination state is invalid.")
        destination_path = destination
        result_path = destination_path
    tx_id = f"tx_{uuid.uuid4().hex[:16]}"
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO file_transactions(tx_id,path_cipher,before_cipher,existed_before,"
            "after_sha256,status,operation,secondary_cipher) "
            "VALUES(?,?,?,?,?,'prepared',?,?)",
            (
                tx_id, _encrypt(str(source.resolve())), _encrypt(""),
                1 if source.exists() else 0, "pending", operation,
                _encrypt(str(destination.resolve())) if destination is not None else "",
            ),
        )
        conn.commit()
        try:
            if operation == "create_folder":
                source.mkdir(parents=True, exist_ok=False)
            elif operation == "copy":
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, destination_path)
                else:
                    shutil.copy2(source, destination_path)
            elif operation == "move":
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination_path))
            else:
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination_path)
            after_hash = _tree_hash(result_path)
        except Exception:
            conn.execute("UPDATE file_transactions SET status='failed' WHERE tx_id=?", (tx_id,))
            conn.commit()
            raise
        conn.execute(
            "UPDATE file_transactions SET status='applied',after_sha256=? WHERE tx_id=?",
            (after_hash, tx_id),
        )
        conn.commit()
    return tx_id


def rollback_text_edit(
    tx_id: str,
    *,
    allowed_roots: list[Path],
    db_path: Path | None = None,
) -> str:
    if not _TX_ID.fullmatch(str(tx_id)):
        return "Invalid transaction ID."
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM file_transactions WHERE tx_id=?", (tx_id,)
        ).fetchone()
        if row is None:
            return "Transaction not found."
        if row["status"] != "applied":
            return f"Transaction is already {row['status']}."
        target = Path(_decrypt(row["path_cipher"]))
        resolved = target.resolve()
        if not any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in allowed_roots
        ) or _contains_symlink(target, allowed_roots):
            return "Rollback target is outside the allowed roots."
        operation = str(row["operation"] or "text_edit")
        if operation == "text_edit":
            if not target.is_file() or _hash_bytes(target.read_bytes()) != row["after_sha256"]:
                return "Rollback blocked: the file changed after the transaction."
            before = _decrypt(row["before_cipher"]).encode("utf-8")
            if row["existed_before"]:
                _atomic_write(target, before)
            else:
                target.unlink()
        else:
            secondary = (
                Path(_decrypt(row["secondary_cipher"])) if row["secondary_cipher"] else None
            )
            current = target if operation == "create_folder" else secondary
            if current is None:
                return "Rollback blocked: transaction destination is missing."
            current_resolved = current.resolve()
            if not any(
                current_resolved == root.resolve()
                or current_resolved.is_relative_to(root.resolve())
                for root in allowed_roots
            ) or _contains_symlink(current, allowed_roots):
                return "Rollback target is outside the allowed roots."
            try:
                unchanged = current.exists() and _tree_hash(current) == row["after_sha256"]
            except (OSError, ValueError):
                unchanged = False
            if not unchanged:
                return "Rollback blocked: the path changed after the transaction."
            if operation in {"create_folder", "copy"}:
                if current.is_dir():
                    shutil.rmtree(current)
                else:
                    current.unlink()
            elif operation in {"move", "rename"}:
                if target.exists():
                    return "Rollback blocked: the original path is occupied."
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current), str(target))
            else:
                return "Rollback blocked: unknown transaction operation."
        conn.execute("UPDATE file_transactions SET status='rolled_back' WHERE tx_id=?", (tx_id,))
        conn.commit()
    return f"Transaction {tx_id} rolled back safely."


def transaction_status(tx_id: str, *, db_path: Path | None = None) -> str | None:
    if not _TX_ID.fullmatch(str(tx_id)):
        return None
    with _LOCK, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM file_transactions WHERE tx_id=?", (tx_id,)
        ).fetchone()
    return str(row[0]) if row else None
