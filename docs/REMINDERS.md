# Reminder architecture

Reminder messages are encrypted in a private local SQLite store with a dedicated
credential-store key. The scheduler receives only an opaque `rem_…` identifier;
plaintext reminder content is never written into LaunchAgent plists, command lines,
or generated scripts.

Create accepts an IANA timezone and validates the local wall clock through a UTC
round trip. A nonexistent daylight-saving time is rejected. When a wall time occurs
twice, the caller must select `fold: 0` or `fold: 1`. Daily and weekly recurrence are
supported in the system timezone so the operating-system calendar scheduler follows
local DST changes safely.

List, status, edit, and delete are backed by the same durable store. Edit registers
the replacement first and leaves the original intact if replacement scheduling
fails. Delete removes the operating-system registration before marking the record
deleted. Create/edit/delete require runtime approval; list/status are read-only.

macOS uses a private LaunchAgent plist and `launchctl bootstrap`; Windows uses Task
Scheduler and Linux uses a user systemd timer. They invoke Misha with only
`--deliver-reminder <id>`, so reminders fire while the main UI is closed. The worker
decrypts the message, displays a platform notification, and records delivery time.
One-time reminders become `delivered`; recurring reminders remain `scheduled` with
an updated `last_delivered_at`.
