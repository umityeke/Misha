from __future__ import annotations

import json
import platform
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from core.integrations.mail import _EMAIL, _SENSITIVE, validate_attachments


_OSASCRIPT = "/usr/bin/osascript"
_READ_ACTIONS = {"mail_inbox", "mail_search", "calendar_list", "calendar_events"}
_MAIL_ACTIONS = {"mail_inbox", "mail_search", "mail_draft", "mail_reply_draft", "mail_send"}
_CALENDAR_ACTIONS = {
    "calendar_list", "calendar_events", "calendar_create", "calendar_update", "calendar_delete",
}
_ALLOWED_ACTIONS = _READ_ACTIONS | _MAIL_ACTIONS | _CALENDAR_ACTIONS


_MAIL_READ_SCRIPT = r'''
function text(value, limit) {
  const normalized = String(value || "").replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ").trim();
  return normalized.slice(0, limit);
}
function run(argv) {
  const action = argv[0];
  const limit = Math.max(1, Math.min(Number(argv[1]) || 20, 100));
  const query = String(argv[2] || "").toLocaleLowerCase();
  const Mail = Application("Mail");
  const source = Mail.inbox.messages();
  const result = [];
  for (let i = 0; i < source.length && result.length < limit; i += 1) {
    const message = source[i];
    const subject = text(message.subject(), 998);
    const sender = text(message.sender(), 320);
    const body = text(message.content(), 1200);
    if (action === "mail_search" &&
        !(`${subject}\n${sender}\n${body}`.toLocaleLowerCase().includes(query))) continue;
    result.push({
      id: text(message.id(), 200),
      message_id: text(message.messageId(), 998),
      sender: sender,
      subject: subject,
      received_at: String(message.dateReceived()),
      unread: Boolean(message.readStatus() === false),
      preview: body.slice(0, 500)
    });
  }
  return JSON.stringify(result);
}
'''


_MAIL_WRITE_SCRIPT = r'''
function run(argv) {
  const action = argv[0];
  const recipient = argv[1];
  const subject = argv[2];
  const body = argv[3];
  const attachmentPaths = JSON.parse(argv[4] || "[]");
  const originalId = argv[5];
  const Mail = Application("Mail");
  if (action === "mail_reply_draft") {
    const numericId = Number(originalId);
    if (!Number.isSafeInteger(numericId)) throw new Error("Original message ID is invalid");
    const matches = Mail.inbox.messages.whose({id: numericId})();
    if (matches.length !== 1) throw new Error("Original message ID must match exactly one inbox message");
    const reply = Mail.reply(matches[0], {openingWindow: true});
    reply.content.set(body + "\n\n" + String(reply.content()));
    for (const attachmentPath of attachmentPaths) {
      reply.content.paragraphs.last.attachments.push(Mail.Attachment({fileName: Path(attachmentPath)}));
    }
    Mail.save(reply);
    return JSON.stringify({id: String(reply.id()), action: action, original_id: originalId});
  }
  const message = Mail.OutgoingMessage({subject: subject, content: body, visible: action === "mail_draft"});
  Mail.outgoingMessages.push(message);
  message.toRecipients.push(Mail.ToRecipient({address: recipient}));
  for (const attachmentPath of attachmentPaths) {
    message.content.paragraphs.last.attachments.push(
      Mail.Attachment({fileName: Path(attachmentPath)})
    );
  }
  const localId = String(message.id());
  if (action === "mail_send") message.send();
  else Mail.save(message);
  return JSON.stringify({id: localId, action: action});
}
'''


_CALENDAR_SCRIPT = r'''
function clean(value, limit) {
  return String(value || "").replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ").trim().slice(0, limit);
}
function run(argv) {
  const action = argv[0];
  const Calendar = Application("Calendar");
  const calendars = Calendar.calendars();
  if (action === "calendar_list") {
    return JSON.stringify(calendars.map(cal => ({id: String(cal.id()), name: clean(cal.name(), 200)})));
  }
  const start = new Date(argv[1]);
  const end = new Date(argv[2]);
  if (action === "calendar_events") {
    const result = [];
    const limit = Math.max(1, Math.min(Number(argv[3]) || 20, 100));
    for (const cal of calendars) {
      const events = cal.events.whose({startDate: {_greaterThanEquals: start, _lessThan: end}})();
      for (const event of events) {
        if (result.length >= limit) break;
        result.push({
          id: String(event.uid()), calendar_id: String(cal.id()),
          calendar: clean(cal.name(), 200), title: clean(event.summary(), 998),
          start: new Date(event.startDate()).toISOString(),
          end: new Date(event.endDate()).toISOString(),
          description: clean(event.description(), 1000)
        });
      }
      if (result.length >= limit) break;
    }
    result.sort((a, b) => a.start.localeCompare(b.start));
    return JSON.stringify(result);
  }
  if (action === "calendar_delete") {
    const eventId = argv[3];
    const matches = [];
    for (const cal of calendars) {
      const events = cal.events.whose({uid: eventId})();
      for (const event of events) matches.push(event);
    }
    if (matches.length !== 1) throw new Error("Event ID must match exactly one local event");
    Calendar.delete(matches[0]);
    return JSON.stringify({id: eventId, deleted: true});
  }
  const calendarName = argv[3];
  const title = argv[4];
  const description = argv[5];
  const matches = calendars.filter(cal => String(cal.name()) === calendarName || String(cal.id()) === calendarName);
  if (matches.length !== 1) throw new Error("Calendar target must match exactly one local calendar");
  if (action === "calendar_update") {
    const eventId = argv[6];
    const events = matches[0].events.whose({uid: eventId})();
    if (events.length !== 1) throw new Error("Event ID must match exactly one event in the selected calendar");
    events[0].summary.set(title);
    events[0].startDate.set(start);
    events[0].endDate.set(end);
    events[0].description.set(description);
    return JSON.stringify({id: eventId, calendar: String(matches[0].name()), title: title, updated: true});
  }
  const event = Calendar.Event({summary: title, startDate: start, endDate: end, description: description});
  matches[0].events.push(event);
  return JSON.stringify({id: String(event.uid()), calendar: String(matches[0].name()), title: title});
}
'''


def _run_script(script: str, args: list[str], *, timeout: int = 30) -> Any:
    if platform.system() != "Darwin" or not Path(_OSASCRIPT).is_file():
        raise RuntimeError("Local Mail and Calendar control is available only on macOS.")
    result = subprocess.run(
        [_OSASCRIPT, "-l", "JavaScript", "-e", script, "--", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = " ".join(result.stderr.split())[:500]
        raise RuntimeError(
            "macOS denied or failed the local app operation"
            + (f": {detail}" if detail else ".")
        )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("The local app returned an invalid response.") from exc


def _bounded_text(value: object, *, field: str, limit: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if "\x00" in text or (required and not text) or len(text) > limit:
        qualifier = f"1–{limit}" if required else f"at most {limit}"
        raise ValueError(f"{field} must contain {qualifier} safe characters.")
    return text


def _iso_datetime(value: object, *, field: str) -> str:
    text = _bounded_text(value, field=field, limit=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 datetime with a timezone.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone offset.")
    return parsed.isoformat()


def _render_rows(title: str, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    if not rows:
        return f"{title}: no matching items."
    lines = [f"{title}: {len(rows)} item(s)"]
    for row in rows:
        parts = [f"{field}={row.get(field, '')}" for field in fields]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _mail_read(params: dict[str, Any], action: str) -> str:
    limit = max(1, min(int(params.get("limit", 20)), 100))
    query = ""
    if action == "mail_search":
        query = _bounded_text(params.get("query"), field="query", limit=500)
    rows = _run_script(_MAIL_READ_SCRIPT, [action, str(limit), query])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("The local Mail app returned an invalid message list.")
    return _render_rows(
        "Local Mail", rows,
        ("id", "sender", "subject", "received_at", "unread", "preview"),
    )


def _mail_write(params: dict[str, Any], action: str) -> str:
    original_id = ""
    receiver = ""
    if action == "mail_reply_draft":
        original_id = _bounded_text(
            params.get("original_message_id"), field="original_message_id", limit=30
        )
        if not original_id.isascii() or not original_id.isdigit():
            raise ValueError("original_message_id must be a numeric local Mail ID.")
    else:
        receiver = _bounded_text(params.get("receiver"), field="receiver", limit=320)
        if not _EMAIL.fullmatch(receiver):
            raise ValueError("receiver must be one valid email address.")
    subject = _bounded_text(
        params.get("subject"), field="subject", limit=998,
        required=action not in {"mail_reply_draft"},
    )
    body = _bounded_text(params.get("body"), field="body", limit=200_000, required=False)
    if action == "mail_reply_draft" and not body:
        raise ValueError("body is required for a reply draft.")
    if action != "mail_reply_draft" and not subject and not body:
        raise ValueError("subject or body is required.")
    raw_attachments = params.get("attachments", [])
    if not isinstance(raw_attachments, list) or any(not isinstance(item, str) for item in raw_attachments):
        raise ValueError("attachments must be a list of file paths.")
    roots = (Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads")
    attachments = validate_attachments(tuple(Path(item) for item in raw_attachments), roots)
    if action == "mail_send" and _SENSITIVE.search(f"{subject}\n{body}") and not bool(
        params.get("sensitive_content_approved", False)
    ):
        raise PermissionError("Sensitive mail content requires a separate explicit approval.")
    result = _run_script(
        _MAIL_WRITE_SCRIPT,
        [
            action, receiver, subject, body,
            json.dumps([str(path) for path in attachments]), original_id,
        ],
    )
    if not isinstance(result, dict) or not str(result.get("id", "")).strip():
        raise RuntimeError("Mail did not return a local message identifier.")
    if action == "mail_reply_draft":
        return (
            f"Local Mail reply draft created and opened; id={result['id']}; "
            f"original_message_id={original_id}."
        )
    if action == "mail_draft":
        return f"Local Mail draft created and opened; id={result['id']}; recipient={receiver}."
    return (
        f"Local Mail accepted the send command; id={result['id']}; recipient={receiver}; "
        "remote delivery is unverified."
    )


def _calendar(params: dict[str, Any], action: str) -> str:
    if action == "calendar_list":
        rows = _run_script(_CALENDAR_SCRIPT, [action])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("The local Calendar app returned an invalid calendar list.")
        return _render_rows("Local calendars", rows, ("id", "name"))
    if action == "calendar_delete":
        event_id = _bounded_text(params.get("event_id"), field="event_id", limit=500)
        result = _run_script(_CALENDAR_SCRIPT, [action, "", "", event_id])
        if not isinstance(result, dict) or result.get("deleted") is not True:
            raise RuntimeError("Calendar did not confirm local event deletion.")
        return f"Local Calendar event deleted; id={event_id}."
    start = _iso_datetime(params.get("start"), field="start")
    end = _iso_datetime(params.get("end"), field="end")
    if datetime.fromisoformat(end) <= datetime.fromisoformat(start):
        raise ValueError("end must be after start.")
    if action == "calendar_events":
        limit = max(1, min(int(params.get("limit", 20)), 100))
        rows = _run_script(_CALENDAR_SCRIPT, [action, start, end, str(limit)])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("The local Calendar app returned an invalid event list.")
        return _render_rows(
            "Local calendar events", rows,
            ("id", "calendar", "title", "start", "end", "description"),
        )
    calendar_name = _bounded_text(
        params.get("calendar_name"), field="calendar_name", limit=200
    )
    title = _bounded_text(params.get("title"), field="title", limit=998)
    description = _bounded_text(
        params.get("description", ""), field="description", limit=20_000, required=False
    )
    event_id = ""
    if action == "calendar_update":
        event_id = _bounded_text(params.get("event_id"), field="event_id", limit=500)
    result = _run_script(
        _CALENDAR_SCRIPT,
        [action, start, end, calendar_name, title, description, event_id],
    )
    if not isinstance(result, dict) or not str(result.get("id", "")).strip():
        raise RuntimeError("Calendar did not return a local event identifier.")
    verb = "updated" if action == "calendar_update" else "created"
    return (
        f"Local Calendar event {verb}; id={result['id']}; "
        f"calendar={result.get('calendar', calendar_name)}; title={title}."
    )


def personal_apps(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).strip().casefold()
    if action not in _ALLOWED_ACTIONS:
        return f"Unknown local personal-app action: '{action}'."
    try:
        if action in _MAIL_ACTIONS:
            result = _mail_read(params, action) if action in _READ_ACTIONS else _mail_write(params, action)
        else:
            result = _calendar(params, action)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        return f"Personal app operation failed: {exc}"
    if player:
        player.write_log(f"[personal-apps] {action}: {result[:120]}")
    return result
