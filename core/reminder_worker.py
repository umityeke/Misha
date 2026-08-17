from __future__ import annotations

from datetime import datetime, timezone

from core.notifications import deliver_notification
from core.reminder_store import get_reminder, mark_delivered


def _notify(message: str) -> bool:
    return deliver_notification("Misha Reminder", message).delivered


def deliver_reminder(reminder_id: str) -> int:
    item = get_reminder(reminder_id)
    if item is None or item["status"] != "scheduled":
        return 2
    if not _notify(item["message"]):
        return 1
    mark_delivered(reminder_id, datetime.now(timezone.utc).isoformat())
    return 0
