import json
import os
import re
import sqlite3
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse
try:
    import psycopg2
    from psycopg2.extras import DictCursor
except ImportError:  # Remote configuration is optional and disabled by default.
    psycopg2 = None
    DictCursor = None
from typing import Optional
from core.credential_store import get_secret, migrate_dotenv_secret

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()

env_path = BASE_DIR / ".env"
REMOTE_CONFIG_ENABLED = os.getenv("MISHA_REMOTE_CONFIG_ENABLED", "0").strip().lower() in {
    "1", "true", "yes", "on"
}
DATABASE_URL = os.getenv("DATABASE_URL") if REMOTE_CONFIG_ENABLED else None
_DATA_DIR_OVERRIDE = os.getenv("MISHA_DATA_DIR", "").strip()
if _DATA_DIR_OVERRIDE and Path(_DATA_DIR_OVERRIDE).is_absolute():
    LOCAL_CONFIG_PATH = Path(_DATA_DIR_OVERRIDE) / "config.db"
else:
    LOCAL_CONFIG_PATH = Path.home() / ".misha" / "config.db"
_LOCAL_LOCK = threading.RLock()
_FORBIDDEN_CONFIG_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|parola|şifre|secret|database[_-]?url)"
)


def initialize_secure_credentials() -> bool:
    """Migrate legacy desktop credentials and load remote config only on opt-in."""
    global DATABASE_URL
    migrated = migrate_dotenv_secret(env_path, "DATABASE_URL", "database-url")
    DATABASE_URL = get_secret("database-url") if REMOTE_CONFIG_ENABLED else None
    return migrated


def _init_local_config() -> None:
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(LOCAL_CONFIG_PATH.parent, 0o700)
    except OSError:
        pass
    with sqlite3.connect(LOCAL_CONFIG_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_config "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "DELETE FROM app_config WHERE "
            "lower(key) LIKE '%api_key%' OR lower(key) LIKE '%api-key%' OR "
            "lower(key) LIKE '%access_token%' OR lower(key) LIKE '%refresh_token%' OR "
            "lower(key) LIKE '%password%' OR lower(key) LIKE '%secret%' OR "
            "lower(key) IN ('database_url','database-url')"
        )
    try:
        os.chmod(LOCAL_CONFIG_PATH, 0o600)
    except OSError:
        pass


def _set_local(key: str, value: str) -> None:
    with _LOCAL_LOCK:
        _init_local_config()
        with sqlite3.connect(LOCAL_CONFIG_PATH) as conn:
            conn.execute(
                "INSERT INTO app_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=CURRENT_TIMESTAMP",
                (key, value),
            )


def _get_local(key: str) -> Optional[str]:
    with _LOCAL_LOCK:
        _init_local_config()
        with sqlite3.connect(LOCAL_CONFIG_PATH) as conn:
            row = conn.execute(
                "SELECT value FROM app_config WHERE key = ?", (key,)
            ).fetchone()
    return row[0] if row else None

def _get_conn():
    if not DATABASE_URL or not REMOTE_CONFIG_ENABLED or psycopg2 is None:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute(
            "DELETE FROM app_config WHERE "
            "lower(key) LIKE '%api_key%' OR lower(key) LIKE '%api-key%' OR "
            "lower(key) LIKE '%access_token%' OR lower(key) LIKE '%refresh_token%' OR "
            "lower(key) LIKE '%password%' OR lower(key) LIKE '%secret%' OR "
            "lower(key) IN ('database_url','database-url')"
        )
        conn.commit()
        cur.close()
        return conn
    except Exception as e:
        print(f"❌ DB Connection Failed: {e}")
        return None

def set_config(key: str, value: str) -> bool:
    key = str(key).strip()
    value = str(value)
    if not key:
        return False
    if _FORBIDDEN_CONFIG_KEY.search(key):
        raise ValueError("Credentials cannot be stored in application configuration.")
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO app_config (key, value) VALUES (%s, %s) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (key, value)
            )
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"❌ Error setting remote config for {key}: {e}")
        finally:
            conn.close()
    _set_local(key, value)
    return True

def get_config(key: str) -> Optional[str]:
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=DictCursor)
            cur.execute("SELECT value FROM app_config WHERE key = %s", (key,))
            row = cur.fetchone()
            cur.close()
            if row:
                value = row["value"]
                _set_local(key, value)
                return value
        except Exception as e:
            print(f"❌ Error getting remote config for {key}: {e}")
        finally:
            conn.close()
    return _get_local(key)


def save_proactive_denylist(
    values: list[str] | tuple[str, ...] | set[str],
) -> tuple[str, ...]:
    """Validate and persist the local proactive-observation denylist."""
    from core.observation_privacy import normalize_denylist

    normalized = normalize_denylist(values)
    set_config("proactive_denylist", json.dumps(normalized, ensure_ascii=False))
    return normalized


def get_proactive_denylist() -> tuple[str, ...]:
    """Return a fail-closed, bounded denylist from local configuration."""
    from core.observation_privacy import normalize_denylist

    raw = get_config("proactive_denylist")
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(values, list):
        return ()
    return normalize_denylist(values)


def save_proactive_settings(settings):
    """Persist validated, non-secret proactive notification preferences."""
    from core.proactive_policy import ProactiveSettings

    validated = ProactiveSettings.validated(
        quiet_hours_enabled=settings.quiet_hours_enabled,
        quiet_start=settings.quiet_start,
        quiet_end=settings.quiet_end,
        daily_limit=settings.daily_limit,
        minimum_priority=settings.minimum_priority,
    )
    payload = {
        "quiet_hours_enabled": validated.quiet_hours_enabled,
        "quiet_start": validated.quiet_start,
        "quiet_end": validated.quiet_end,
        "daily_limit": validated.daily_limit,
        "minimum_priority": validated.minimum_priority,
    }
    set_config("proactive_settings", json.dumps(payload, ensure_ascii=False))
    return validated


def get_proactive_settings():
    """Load proactive preferences and fail safely to privacy-friendly defaults."""
    from core.proactive_policy import ProactiveSettings

    raw = get_config("proactive_settings")
    try:
        payload = json.loads(raw) if raw else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return ProactiveSettings.validated(**{
        key: payload[key]
        for key in (
            "quiet_hours_enabled", "quiet_start", "quiet_end",
            "daily_limit", "minimum_priority",
        )
        if key in payload
    })


def proactive_budget_available(day: str, daily_limit: int) -> bool:
    stored_day = get_config("proactive_budget_day") or ""
    if stored_day != day:
        return True
    try:
        count = int(get_config("proactive_budget_count") or "0")
    except (TypeError, ValueError):
        count = 0
    try:
        limit = int(daily_limit)
    except (TypeError, ValueError):
        limit = 6
    return count < max(1, min(limit, 50))


def record_proactive_notification(day: str) -> int:
    stored_day = get_config("proactive_budget_day") or ""
    try:
        count = int(get_config("proactive_budget_count") or "0")
    except (TypeError, ValueError):
        count = 0
    count = count + 1 if stored_day == day else 1
    set_config("proactive_budget_day", day)
    set_config("proactive_budget_count", str(count))
    return count

def config_exists() -> bool:
    return is_configured()

def is_configured() -> bool:
    provider = (get_config("ai_provider") or "ollama").strip().lower()
    if provider == "ollama":
        return bool((get_config("local_model") or "qwen3-coder:30b").strip())
    return False


def save_local_ai_config(
    model: str = "qwen3-coder:30b",
    base_url: str = "http://127.0.0.1:11434",
    fallback_models: list[str] | tuple[str, ...] | None = None,
    context_length: int = 8192,
) -> None:
    model = model.strip()
    base_url = base_url.strip().rstrip("/")
    if not model:
        raise ValueError("Local model name cannot be empty.")
    if model.casefold().endswith("-cloud") or ":cloud" in model.casefold():
        raise ValueError("Cloud model aliases are not allowed in local-only mode.")
    parsed_url = urlparse(base_url)
    if (
        parsed_url.scheme != "http"
        or parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise ValueError("Ollama must use a local-only address by default.")
    fallbacks = []
    for fallback in fallback_models or ():
        name = str(fallback).strip()
        if not name or len(name) > 128:
            raise ValueError("Fallback model names must be 1-128 characters.")
        if name.casefold().endswith("-cloud") or ":cloud" in name.casefold():
            raise ValueError("Cloud fallback models are not allowed in local-only mode.")
        if name != model and name not in fallbacks:
            fallbacks.append(name)
    try:
        context_length = int(context_length)
    except (TypeError, ValueError) as exc:
        raise ValueError("Context length must be an integer.") from exc
    if not 2048 <= context_length <= 32768:
        raise ValueError("Context length must be between 2048 and 32768.")
    set_config("ai_provider", "ollama")
    set_config("local_model", model)
    set_config("local_model_fallbacks", json.dumps(fallbacks))
    set_config("ollama_base_url", base_url)
    set_config("local_context_length", str(context_length))


def save_local_voice_config(
    whisper_cli_path: str,
    whisper_model_path: str,
) -> None:
    cli = Path(whisper_cli_path).expanduser().resolve()
    model = Path(whisper_model_path).expanduser().resolve()
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ValueError("whisper-cli must be an existing executable file.")
    if not model.is_file() or model.suffix.lower() != ".bin":
        raise ValueError("Whisper model must be an existing .bin file.")
    set_config("whisper_cli_path", str(cli))
    set_config("whisper_model_path", str(model))
