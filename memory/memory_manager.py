from __future__ import annotations

from typing import Optional

from core.memory_service import (
    MemoryKind,
    delete_memory,
    list_memories,
    migrate_legacy_json,
    put_memory,
)

MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2_200
_CATEGORIES = ("identity", "preferences", "projects", "relationships", "wishes", "notes")


def _empty_memory() -> dict:
    return {category: {} for category in _CATEGORIES}


def load_memory() -> dict:
    migrate_legacy_json()
    memory = _empty_memory()
    for record in reversed(list_memories(MemoryKind.LONG_TERM, limit=500)):
        category = record.category if record.category in memory else "notes"
        memory[category][record.key] = {
            "id": record.id,
            "value": record.value,
            "updated": record.updated_at[:10],
        }
    return memory


def _truncate_value(value: str) -> str:
    return value[:MAX_VALUE_LENGTH].rstrip() + "…" if len(value) > MAX_VALUE_LENGTH else value


def _iter_updates(updates: dict, category: str = "notes"):
    for key, value in updates.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, dict) and "value" not in value:
            next_category = key if key in _CATEGORIES else category
            yield from _iter_updates(value, next_category)
            continue
        raw_value = value.get("value") if isinstance(value, dict) else value
        if raw_value is None:
            continue
        yield category, str(key), _truncate_value(str(raw_value))


def update_memory(memory_update: dict, *, source: str = "model") -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    for category, key, value in _iter_updates(memory_update):
        put_memory(
            MemoryKind.LONG_TERM,
            key,
            value,
            category=category,
            source=source,
        )
    return load_memory()


def save_memory(memory: dict) -> None:
    """Compatibility writer; entries are upserted without destructive replacement."""
    if isinstance(memory, dict):
        update_memory(memory, source="user")


def format_memory_for_prompt(memory: Optional[dict]) -> str:
    if not memory:
        return ""
    lines: list[str] = []
    identity = memory.get("identity", {})
    identity_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in identity_fields:
        entry = identity.get(field)
        value = entry.get("value") if isinstance(entry, dict) else entry
        if value:
            lines.append(f"{field.title()}: {value}")
    for key, entry in identity.items():
        if key in identity_fields:
            continue
        value = entry.get("value") if isinstance(entry, dict) else entry
        if value:
            lines.append(f"{key.replace('_', ' ').title()}: {value}")

    labels = {
        "preferences": "Preferences:",
        "projects": "Active Projects / Goals:",
        "relationships": "People in their life:",
        "wishes": "Wishes / Plans / Wants:",
        "notes": "Other notes:",
    }
    limits = {"preferences": 15, "projects": 8, "relationships": 10, "wishes": 8, "notes": 8}
    for category, label in labels.items():
        entries = memory.get(category, {})
        if not entries:
            continue
        lines.extend(["", label])
        for key, entry in list(entries.items())[:limits[category]]:
            value = entry.get("value") if isinstance(entry, dict) else entry
            if value:
                lines.append(f"  - {key.replace('_', ' ').title()}: {value}")
    if not lines:
        return ""
    result = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n" + "\n".join(lines)
    return (result[:1997] + "…" if len(result) > 2_000 else result) + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    safe_category = category if category in _CATEGORIES else "notes"
    record = put_memory(
        MemoryKind.LONG_TERM, key, _truncate_value(str(value)),
        category=safe_category, source="user",
    )
    return f"Remembered: {record.category}/{record.key} = {record.value}"


def forget(key: str, category: str = "notes") -> str:
    for record in list_memories(MemoryKind.LONG_TERM, category=category, limit=500):
        if record.key == key:
            delete_memory(record.id)
            return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget
