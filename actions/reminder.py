from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.reminder_store import (
    REMINDER_ID, create_reminder_record, get_reminder, list_reminders,
    mark_deleted, mark_failed, set_scheduled,
)

REPEAT_RULES = {"none", "daily", "weekly"}


def _get_os() -> str:
    return {"Darwin": "mac", "Windows": "windows", "Linux": "linux"}.get(platform.system(), "unsupported")


def _local_zone_name() -> str:
    configured = os.getenv("TZ", "").strip()
    if configured:
        try:
            ZoneInfo(configured)
            return configured
        except ZoneInfoNotFoundError:
            pass
    tzinfo = datetime.now().astimezone().tzinfo
    key = getattr(tzinfo, "key", "")
    if key:
        return str(key)
    try:
        text = str(Path("/etc/localtime").resolve())
        if "zoneinfo/" in text:
            candidate = text.split("zoneinfo/", 1)[1]
            ZoneInfo(candidate)
            return candidate
    except (OSError, ZoneInfoNotFoundError):
        pass
    return "UTC"


def _parse_target(date_text: str, time_text: str, zone_name: str, fold: int | None) -> datetime:
    try:
        naive = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
        zone = ZoneInfo(zone_name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Use a valid YYYY-MM-DD date, HH:MM time, and IANA timezone.") from exc
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)

    def roundtrips(value: datetime) -> bool:
        return value.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive

    valid_first, valid_second = roundtrips(first), roundtrips(second)
    if not valid_first and not valid_second:
        raise ValueError("That local time does not exist because of a daylight-saving transition.")
    ambiguous = valid_first and valid_second and first.utcoffset() != second.utcoffset()
    if ambiguous and fold not in {0, 1}:
        raise ValueError("That time occurs twice because of daylight saving; specify fold 0 or 1.")
    return naive.replace(tzinfo=zone, fold=int(fold or 0))


def _launch_agents_dir() -> Path:
    path = Path.home() / "Library" / "LaunchAgents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _worker_argv(reminder_id: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--deliver-reminder", reminder_id]
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    return [sys.executable, str(main_path), "--deliver-reminder", reminder_id]


def _schedule_mac(target: datetime, reminder_id: str, repeat_rule: str) -> str:
    local_target = target.astimezone(ZoneInfo(_local_zone_name()))
    label = f"com.misha.reminder.{reminder_id}"
    plist_path = _launch_agents_dir() / f"{label}.plist"
    interval: dict[str, int] = {"Hour": local_target.hour, "Minute": local_target.minute}
    if repeat_rule == "none":
        interval.update({"Year": local_target.year, "Month": local_target.month, "Day": local_target.day})
    elif repeat_rule == "weekly":
        interval["Weekday"] = (local_target.weekday() + 1) % 7
    payload = {
        "Label": label, "ProgramArguments": _worker_argv(reminder_id),
        "StartCalendarInterval": interval, "RunAtLoad": False,
        "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null",
    }
    temporary = plist_path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, plist_path)
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        plist_path.unlink(missing_ok=True)
        return ""
    return label


def _schedule_windows(target: datetime, reminder_id: str, repeat_rule: str) -> str:
    task = f"MishaReminder_{reminder_id}"
    local = target.astimezone()
    schedule = {"none": "ONCE", "daily": "DAILY", "weekly": "WEEKLY"}[repeat_rule]
    args = [
        "schtasks", "/Create", "/TN", task, "/SC", schedule,
        "/ST", local.strftime("%H:%M"), "/TR", subprocess.list2cmdline(_worker_argv(reminder_id)), "/F",
    ]
    if repeat_rule == "none":
        args.extend(["/SD", local.strftime("%m/%d/%Y")])
    result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    return task if result.returncode == 0 else ""


def _schedule_linux(target: datetime, reminder_id: str, repeat_rule: str) -> str:
    if not shutil.which("systemd-run"):
        return ""
    local = target.astimezone()
    calendar = local.strftime("%Y-%m-%d %H:%M:00")
    if repeat_rule == "daily":
        calendar = f"*-*-* {local:%H:%M}:00"
    elif repeat_rule == "weekly":
        calendar = f"{local:%a} *-*-* {local:%H:%M}:00"
    unit = f"misha-{reminder_id}"
    result = subprocess.run(
        ["systemd-run", "--user", f"--on-calendar={calendar}", f"--unit={unit}", "--", *_worker_argv(reminder_id)],
        capture_output=True, text=True, timeout=15,
    )
    return unit if result.returncode == 0 else ""


def _schedule(target: datetime, reminder_id: str, repeat_rule: str) -> str:
    scheduler = {"mac": _schedule_mac, "windows": _schedule_windows, "linux": _schedule_linux}.get(_get_os())
    return scheduler(target, reminder_id, repeat_rule) if scheduler else ""


def _unschedule(item: dict) -> bool:
    scheduler_id = str(item.get("scheduler_id", ""))
    if not scheduler_id:
        return True
    os_name = _get_os()
    if os_name == "mac":
        plist = _launch_agents_dir() / f"{scheduler_id}.plist"
        result = subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)],
            capture_output=True, text=True, timeout=10,
        )
        plist.unlink(missing_ok=True)
        return result.returncode == 0 or "No such process" in (result.stderr or "")
    if os_name == "windows":
        result = subprocess.run(["schtasks", "/Delete", "/TN", scheduler_id, "/F"], capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    if os_name == "linux":
        subprocess.run(["systemctl", "--user", "stop", f"{scheduler_id}.timer"], capture_output=True, timeout=10)
        subprocess.run(["systemctl", "--user", "reset-failed", f"{scheduler_id}.timer"], capture_output=True, timeout=10)
        return True
    return False


def scheduler_registered(item: dict) -> bool:
    """Independently query the native scheduler for an exact opaque reminder ID."""
    scheduler_id = str(item.get("scheduler_id", ""))
    reminder_id = str(item.get("reminder_id", ""))
    if not REMINDER_ID.fullmatch(reminder_id) or not scheduler_id:
        return False
    try:
        os_name = _get_os()
        if os_name == "mac":
            expected = f"com.misha.reminder.{reminder_id}"
            plist = Path.home() / "Library" / "LaunchAgents" / f"{expected}.plist"
            if scheduler_id != expected or not plist.is_file():
                return False
            result = subprocess.run(
                ["launchctl", "print", f"gui/{os.getuid()}/{expected}"],
                capture_output=True, text=True, timeout=10,
            )
        elif os_name == "windows":
            expected = f"MishaReminder_{reminder_id}"
            if scheduler_id != expected:
                return False
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", expected, "/FO", "LIST"],
                capture_output=True, text=True, timeout=15,
            )
        elif os_name == "linux":
            expected = f"misha-{reminder_id}"
            if scheduler_id != expected:
                return False
            result = subprocess.run(
                ["systemctl", "--user", "is-active", f"{expected}.timer"],
                capture_output=True, text=True, timeout=10,
            )
        else:
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _create(params: dict) -> str:
    date_text = str(params.get("date", "")).strip()
    time_text = str(params.get("time", "")).strip()
    message = " ".join(str(params.get("message", "Reminder")).split())[:300]
    zone_name = str(params.get("timezone", "")).strip() or _local_zone_name()
    repeat_rule = str(params.get("repeat", "none")).strip().casefold() or "none"
    fold = params.get("fold")
    if repeat_rule not in REPEAT_RULES:
        return "Invalid repeat rule; use none, daily, or weekly."
    if repeat_rule != "none" and zone_name != _local_zone_name():
        return "Recurring reminders must currently use the system timezone for DST-safe delivery."
    try:
        target = _parse_target(date_text, time_text, zone_name, fold)
    except ValueError as exc:
        return f"Invalid reminder time: {exc}"
    if target.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        return "That time has already passed — I can't set a reminder in the past."
    reminder_id = create_reminder_record(
        message=message, local_iso=target.isoformat(), utc_iso=target.astimezone(timezone.utc).isoformat(),
        timezone=zone_name, fold=target.fold, repeat_rule=repeat_rule,
    )
    scheduler_id = _schedule(target, reminder_id, repeat_rule)
    if not scheduler_id:
        mark_failed(reminder_id)
        return "I couldn't register the reminder with the system scheduler."
    set_scheduled(reminder_id, scheduler_id)
    return f"Reminder scheduled: {reminder_id} at {target.isoformat()} ({repeat_rule})."


def _list(params: dict) -> str:
    items = list_reminders(include_terminal=bool(params.get("include_terminal", False)))
    if not items:
        return "No reminders found."
    lines = ["Reminders:"]
    for item in items:
        lines.append(
            f"- {item['reminder_id']} | {item['status']} | {item['local_iso']} "
            f"[{item['timezone']}, {item['repeat_rule']}] | {item['message'][:120]}"
        )
    return "\n".join(lines)


def _delete(reminder_id: str) -> str:
    if not REMINDER_ID.fullmatch(reminder_id):
        return "Invalid reminder ID."
    item = get_reminder(reminder_id)
    if item is None:
        return "Reminder not found."
    if not _unschedule(item):
        return "Could not remove the reminder from the system scheduler."
    mark_deleted(reminder_id)
    return f"Reminder deleted: {reminder_id}."


def reminder(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "create")).strip().casefold() or "create"
    try:
        if action == "create":
            result = _create(params)
        elif action == "list":
            result = _list(params)
        elif action == "delete":
            result = _delete(str(params.get("reminder_id", "")))
        elif action == "status":
            item = get_reminder(str(params.get("reminder_id", "")))
            result = f"Reminder status: {item['status']}; last delivered: {item['last_delivered_at'] or 'never'}." if item else "Reminder not found."
        elif action == "edit":
            old_id = str(params.get("reminder_id", ""))
            old = get_reminder(old_id)
            if old is None:
                return "Reminder not found."
            old_local = datetime.fromisoformat(old["local_iso"])
            merged = dict(params)
            merged.update({
                "date": params.get("date") or old_local.strftime("%Y-%m-%d"),
                "time": params.get("time") or old_local.strftime("%H:%M"),
                "message": params.get("message") or old["message"],
                "timezone": params.get("timezone") or old["timezone"],
                "repeat": params.get("repeat") or old["repeat_rule"],
                "fold": params.get("fold", old["fold"]),
            })
            created = _create(merged)
            if not created.startswith("Reminder scheduled"):
                return f"Reminder edit failed; original is unchanged. {created}"
            new_id = created.split("Reminder scheduled: ", 1)[1].split()[0]
            if not _unschedule(old):
                new_item = get_reminder(new_id)
                if new_item is not None:
                    _unschedule(new_item)
                    mark_deleted(new_id)
                return "Reminder edit failed; original scheduler entry is unchanged."
            mark_deleted(old_id)
            result = f"Reminder replaced ({old_id}). {created}"
        else:
            result = f"Unknown reminder action: '{action}'"
    except (OSError, RuntimeError, ValueError) as exc:
        result = f"Reminder error: {exc}"
    if player:
        player.write_log(f"[Reminder] {action}: {result[:80]}")
    return result
