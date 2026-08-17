from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationReceipt:
    delivered: bool
    channel: str


def _bounded(value: str, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def deliver_notification(
    title: str,
    message: str,
    *,
    priority: str = "normal",
    os_name: str | None = None,
) -> NotificationReceipt:
    """Deliver through a native local channel without interpolating user text."""
    safe_title = _bounded(title, 80)
    safe_message = _bounded(message, 500)
    if not safe_title or not safe_message:
        return NotificationReceipt(False, "invalid")
    system = os_name or platform.system()
    urgency = "critical" if str(priority).casefold() == "critical" else "normal"
    try:
        if system == "Darwin" and shutil.which("osascript"):
            script = (
                "on run argv\n"
                "display notification (item 2 of argv) with title (item 1 of argv)\n"
                "end run"
            )
            completed = subprocess.run(
                ["osascript", "-e", script, safe_title, safe_message],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return NotificationReceipt(completed.returncode == 0, "macos_notification")
        if system == "Linux" and shutil.which("notify-send"):
            completed = subprocess.run(
                [
                    "notify-send", f"--urgency={urgency}", "--expire-time=15000",
                    safe_title, safe_message,
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return NotificationReceipt(completed.returncode == 0, "freedesktop_notification")
        if system == "Windows" and shutil.which("powershell"):
            # Text enters as argv. CreateTextNode keeps markup characters inert.
            script = (
                "param($Title,$Message);"
                "$xml=New-Object Windows.Data.Xml.Dom.XmlDocument;"
                "$xml.LoadXml('<toast><visual><binding template=\"ToastGeneric\">' +"
                "'<text></text><text></text></binding></visual></toast>');"
                "$nodes=$xml.GetElementsByTagName('text');"
                "$nodes.Item(0).AppendChild($xml.CreateTextNode($Title))|Out-Null;"
                "$nodes.Item(1).AppendChild($xml.CreateTextNode($Message))|Out-Null;"
                "$toast=[Windows.UI.Notifications.ToastNotification]::new($xml);"
                "[Windows.UI.Notifications.ToastNotificationManager]::"
                "CreateToastNotifier('Misha').Show($toast)"
            )
            completed = subprocess.run(
                [
                    "powershell", "-NoProfile", "-NonInteractive", "-Command", script,
                    safe_title, safe_message,
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
            return NotificationReceipt(completed.returncode == 0, "windows_toast")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return NotificationReceipt(False, "unavailable")
