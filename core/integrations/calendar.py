from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    timezone_name: str
    attendees: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not self.calendar_id.strip() or not self.title.strip():
            raise ValueError("Calendar and event title are required.")
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise ValueError("Calendar event times must be aware and end after start.")
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Calendar event timezone is invalid.") from exc
        if len(self.attendees) > 100 or any("@" not in item for item in self.attendees):
            raise ValueError("Calendar attendees must be bounded email addresses.")


class CalendarProvider(Protocol):
    def list_calendars(self) -> list[dict[str, str]]: ...
    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...
    def get_event(self, event_id: str) -> CalendarEvent | None: ...
    def create_event(self, event: CalendarEvent) -> CalendarEvent: ...
    def update_event(self, event: CalendarEvent) -> CalendarEvent: ...
    def delete_event(self, event_id: str) -> bool: ...


def parse_local_datetime(value: str, timezone_name: str, *, fold: int | None = None) -> datetime:
    try:
        naive = datetime.fromisoformat(value)
        if naive.tzinfo is not None:
            raise ValueError
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Use an ISO local datetime and valid IANA timezone.") from exc
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)

    def valid(candidate: datetime) -> bool:
        return candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive

    valid_first, valid_second = valid(first), valid(second)
    if not valid_first and not valid_second:
        raise ValueError("Calendar time does not exist because of daylight saving.")
    ambiguous = valid_first and valid_second and first.utcoffset() != second.utcoffset()
    if ambiguous and fold not in {0, 1}:
        raise ValueError("Calendar time is ambiguous; specify fold 0 or 1.")
    return naive.replace(tzinfo=zone, fold=int(fold or 0))


def event_conflicts(candidate: CalendarEvent, existing: list[CalendarEvent]) -> list[CalendarEvent]:
    return [
        event for event in existing
        if event.event_id != candidate.event_id
        and candidate.start.astimezone(timezone.utc) < event.end.astimezone(timezone.utc)
        and candidate.end.astimezone(timezone.utc) > event.start.astimezone(timezone.utc)
    ]


class CalendarService:
    def __init__(self, provider: CalendarProvider) -> None:
        self.provider = provider

    def list_calendars(self) -> list[dict[str, str]]:
        return self.provider.list_calendars()

    def get_event(self, event_id: str) -> CalendarEvent | None:
        return self.provider.get_event(event_id)

    def conflicts(self, event: CalendarEvent) -> list[CalendarEvent]:
        return event_conflicts(event, self.provider.list_events(event.start, event.end))

    def create(
        self,
        event: CalendarEvent,
        *,
        mutation_approved: bool,
        attendee_invites_approved: bool = False,
        allow_conflict: bool = False,
    ) -> CalendarEvent:
        if not mutation_approved:
            raise PermissionError("Calendar creation requires exact owner approval.")
        if event.attendees and not attendee_invites_approved:
            raise PermissionError("Inviting attendees requires a separate owner approval.")
        if self.conflicts(event) and not allow_conflict:
            raise ValueError("Calendar event conflicts with an existing event.")
        return self.provider.create_event(event)

    def update(
        self,
        event: CalendarEvent,
        *,
        mutation_approved: bool,
        attendee_invites_approved: bool = False,
        allow_conflict: bool = False,
    ) -> CalendarEvent:
        if not event.event_id:
            raise ValueError("Calendar event ID is required for update.")
        if not mutation_approved:
            raise PermissionError("Calendar update requires exact owner approval.")
        current = self.provider.get_event(event.event_id)
        if current is None:
            raise ValueError("Calendar event was not found.")
        newly_invited = set(event.attendees) - set(current.attendees)
        if newly_invited and not attendee_invites_approved:
            raise PermissionError("New attendee invitations require a separate owner approval.")
        if self.conflicts(event) and not allow_conflict:
            raise ValueError("Calendar event conflicts with an existing event.")
        return self.provider.update_event(event)

    def delete(self, event_id: str, *, mutation_approved: bool) -> bool:
        if not mutation_approved:
            raise PermissionError("Calendar deletion requires exact owner approval.")
        if self.provider.get_event(event_id) is None:
            return False
        return self.provider.delete_event(event_id)

    def move(self, event_id: str, start: datetime, end: datetime) -> CalendarEvent:
        current = self.provider.get_event(event_id)
        if current is None:
            raise ValueError("Calendar event was not found.")
        return replace(current, start=start, end=end)
