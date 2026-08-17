from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


PRIORITY_LEVELS = {"low": 0, "normal": 1, "critical": 2}


def normalize_priority(value: str) -> str:
    priority = str(value).strip().casefold()
    return priority if priority in PRIORITY_LEVELS else "normal"


def normalize_clock(value: str, default: str) -> str:
    try:
        parsed = datetime.strptime(str(value).strip(), "%H:%M")
    except (TypeError, ValueError):
        return default
    return parsed.strftime("%H:%M")


def normalize_enabled(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(frozen=True)
class ProactiveSettings:
    quiet_hours_enabled: bool = True
    quiet_start: str = "22:00"
    quiet_end: str = "08:00"
    daily_limit: int = 6
    minimum_priority: str = "normal"

    @classmethod
    def validated(
        cls,
        *,
        quiet_hours_enabled: bool = True,
        quiet_start: str = "22:00",
        quiet_end: str = "08:00",
        daily_limit: int = 6,
        minimum_priority: str = "normal",
    ) -> "ProactiveSettings":
        try:
            limit = int(daily_limit)
        except (TypeError, ValueError):
            limit = 6
        return cls(
            quiet_hours_enabled=normalize_enabled(quiet_hours_enabled),
            quiet_start=normalize_clock(quiet_start, "22:00"),
            quiet_end=normalize_clock(quiet_end, "08:00"),
            daily_limit=max(1, min(limit, 50)),
            minimum_priority=normalize_priority(minimum_priority),
        )

    def is_quiet_time(self, moment: datetime) -> bool:
        if not self.quiet_hours_enabled:
            return False
        start = time.fromisoformat(self.quiet_start)
        end = time.fromisoformat(self.quiet_end)
        current = moment.time().replace(second=0, microsecond=0)
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def permits_priority(self, priority: str) -> bool:
        normalized = normalize_priority(priority)
        return PRIORITY_LEVELS[normalized] >= PRIORITY_LEVELS[self.minimum_priority]
