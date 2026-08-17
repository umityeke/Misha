from __future__ import annotations

import platform
import re
import subprocess
import time

from core.outbound_guard import finish, reserve
from core.ui_automation import enforce_pyautogui_safety

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    pyautogui = None
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    pyperclip = None
    _PYPERCLIP = False


SUPPORTED_PLATFORMS = {
    "whatsapp": {"aliases": {"whatsapp", "wp", "wapp"}, "app": "WhatsApp"},
    "telegram": {"aliases": {"telegram", "tg"}, "app": "Telegram"},
    "signal": {"aliases": {"signal"}, "app": "Signal"},
    "discord": {"aliases": {"discord"}, "app": "Discord"},
}


def _get_os() -> str:
    return {"Darwin": "mac", "Windows": "windows", "Linux": "linux"}.get(platform.system(), "unsupported")


def _require_ui() -> None:
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI is unavailable; desktop messaging is disabled.")
    enforce_pyautogui_safety(pyautogui)


def _platform(value: str) -> tuple[str, str]:
    key = str(value).strip().casefold()
    for canonical, spec in SUPPORTED_PLATFORMS.items():
        if key in spec["aliases"]:
            return canonical, str(spec["app"])
    raise ValueError("Unsupported messaging platform. Supported: WhatsApp, Telegram, Signal, Discord.")


def _receiver(value: str) -> str:
    raw = str(value)
    if any(ord(char) < 32 for char in raw):
        raise ValueError("Recipient contains control characters.")
    normalized = " ".join(raw.split())
    if not 1 <= len(normalized) <= 100:
        raise ValueError("Recipient must contain 1–100 characters.")
    return normalized


def _message(value: str) -> str:
    text = str(value).strip()
    if not 1 <= len(text) <= 4_000:
        raise ValueError("Message must contain 1–4,000 characters.")
    if "\x00" in text:
        raise ValueError("Message contains an invalid NUL character.")
    return text


def _paste(text: str) -> None:
    _require_ui()
    modifier = "command" if _get_os() == "mac" else "ctrl"
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey(modifier, "v")
    else:
        pyautogui.write(text, interval=0.03)


def _open_app(app_name: str) -> bool:
    _require_ui()
    os_name = _get_os()
    if os_name == "mac":
        result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=10)
        time.sleep(2.0)
        return result.returncode == 0
    if os_name == "windows":
        pyautogui.press("win")
        time.sleep(0.5)
        pyautogui.write(app_name, interval=0.05)
        pyautogui.press("enter")
        time.sleep(2.0)
        return True
    if os_name == "linux":
        executable = app_name.casefold()
        try:
            subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.0)
            return True
        except OSError:
            return False
    return False


def _active_recipient_matches(app_name: str, receiver: str) -> bool:
    if _get_os() != "mac":
        # No semantic Accessibility verifier is implemented on Windows/Linux yet.
        return False
    from core.macos_observe import get_active_window_text

    observed = get_active_window_text()
    if not observed or f"Aktif Uygulama: {app_name}".casefold() not in observed.casefold():
        return False
    escaped = re.escape(receiver)
    return bool(re.search(rf"Title:\s*['\"]{escaped}['\"]", observed, re.IGNORECASE))


def _select_exact_recipient(platform_name: str, app_name: str, receiver: str) -> bool:
    _require_ui()
    if not _open_app(app_name):
        return False
    modifier = "command" if _get_os() == "mac" else "ctrl"
    search_key = "k" if platform_name in {"whatsapp", "telegram", "discord"} else "f"
    pyautogui.hotkey(modifier, search_key)
    time.sleep(0.4)
    pyautogui.hotkey(modifier, "a")
    pyautogui.press("delete")
    _paste(receiver)
    time.sleep(0.8)
    pyautogui.press("enter")
    time.sleep(0.8)
    return _active_recipient_matches(app_name, receiver)


def _preview(platform_name: str, receiver: str, message: str) -> str:
    excerpt = message[:240] + ("…" if len(message) > 240 else "")
    return (
        "Message preview (not sent):\n"
        f"Platform: {platform_name}\nRecipient: {receiver}\nContent: {excerpt}"
    )


def send_message(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "send")).strip().casefold() or "send"
    try:
        platform_name, app_name = _platform(str(params.get("platform", "")))
        receiver = _receiver(str(params.get("receiver", "")))
        message = _message(str(params.get("message_text", "")))
    except ValueError as exc:
        return f"Message blocked: {exc}"
    if action == "preview":
        return _preview(platform_name, receiver, message)
    if action != "send":
        return f"Unknown messaging action: '{action}'"

    allowed, fingerprint = reserve(
        platform_name, receiver, message,
        allow_duplicate=bool(params.get("allow_duplicate", False)),
    )
    if not allowed:
        return "Duplicate message blocked: the same message was attempted in the last five minutes."
    try:
        if not _select_exact_recipient(platform_name, app_name, receiver):
            finish(fingerprint, "blocked")
            return "Message blocked: active app and exact recipient header could not be verified."
        _paste(message)
        time.sleep(0.2)
        if not _active_recipient_matches(app_name, receiver):
            finish(fingerprint, "blocked")
            return "Message blocked: recipient changed before submission."
        pyautogui.press("enter")
        finish(fingerprint, "sent_unverified")
        result = (
            f"Message send attempted to {receiver} via {app_name}; exact recipient was verified "
            "before submission, but remote delivery is unverified."
        )
    except Exception as exc:
        finish(fingerprint, "failed")
        result = f"Could not send message: {exc}"
    if player:
        player.write_log(f"[msg] {platform_name} → {receiver}: {result[:80]}")
    return result
