from datetime import timedelta
import unittest

from core.integrations.calendar import (
    CalendarEvent,
    CalendarService,
    parse_local_datetime,
)


class _CalendarProvider:
    def __init__(self):
        self.events = {}

    def list_calendars(self):
        return [{"id": "primary", "name": "Primary"}]

    def list_events(self, start, end):
        return list(self.events.values())

    def get_event(self, event_id):
        return self.events.get(event_id)

    def create_event(self, event):
        created = CalendarEvent(**{**event.__dict__, "event_id": "event-1"})
        self.events[created.event_id] = created
        return created

    def update_event(self, event):
        self.events[event.event_id] = event
        return event

    def delete_event(self, event_id):
        return self.events.pop(event_id, None) is not None


class CalendarIntegrationContractTests(unittest.TestCase):
    def event(self, **changes):
        start = parse_local_datetime("2030-06-10T09:00", "Europe/Istanbul")
        values = {
            "event_id": "",
            "calendar_id": "primary",
            "title": "Planning",
            "start": start,
            "end": start + timedelta(hours=1),
            "timezone_name": "Europe/Istanbul",
            "attendees": (),
        }
        values.update(changes)
        return CalendarEvent(**values)

    def test_timezone_dst_and_conflict_contract(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            parse_local_datetime("2026-03-29T02:30", "Europe/Berlin")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            parse_local_datetime("2026-10-25T02:30", "Europe/Berlin")
        provider = _CalendarProvider()
        service = CalendarService(provider)
        created = service.create(self.event(), mutation_approved=True)
        overlap = self.event(
            title="Overlap",
            start=created.start + timedelta(minutes=30),
            end=created.end + timedelta(minutes=30),
        )
        with self.assertRaisesRegex(ValueError, "conflicts"):
            service.create(overlap, mutation_approved=True)

    def test_create_update_delete_and_attendee_approval(self):
        provider = _CalendarProvider()
        service = CalendarService(provider)
        with self.assertRaises(PermissionError):
            service.create(self.event(), mutation_approved=False)
        invited = self.event(attendees=("owner@example.com",))
        with self.assertRaisesRegex(PermissionError, "separate"):
            service.create(invited, mutation_approved=True)
        created = service.create(
            invited, mutation_approved=True, attendee_invites_approved=True
        )
        changed = CalendarEvent(**{**created.__dict__, "title": "Updated"})
        self.assertEqual(
            service.update(changed, mutation_approved=True).title, "Updated"
        )
        with self.assertRaises(PermissionError):
            service.delete(created.event_id, mutation_approved=False)
        self.assertTrue(service.delete(created.event_id, mutation_approved=True))


if __name__ == "__main__":
    unittest.main()
