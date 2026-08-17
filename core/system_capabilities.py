from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    backend: str
    detail: str


def capability_matrix(system: str | None = None, *, pyautogui_available: bool = False) -> dict[str, Capability]:
    os_name = system or platform.system()

    def binary(*names: str) -> str:
        return next((name for name in names if shutil.which(name)), "")

    if os_name == "Darwin":
        return {
            "app_open": Capability("app_open", bool(binary("open")), "open", "allowlisted argv"),
            "window_control": Capability("window_control", pyautogui_available, "pyautogui", "Accessibility required"),
            "volume": Capability("volume", bool(binary("osascript")), "osascript", "system volume"),
            "brightness": Capability("brightness", pyautogui_available, "pyautogui", "keyboard/Accessibility"),
            "media": Capability("media", pyautogui_available, "pyautogui", "focused application"),
            "screenshot": Capability("screenshot", pyautogui_available, "pyautogui", "Desktop/Pictures only"),
            "power": Capability("power", bool(binary("osascript")), "osascript", "approval + confirmation"),
        }
    if os_name == "Windows":
        return {
            name: Capability(name, pyautogui_available, "pyautogui", "interactive desktop required")
            for name in ("app_open", "window_control", "volume", "brightness", "media", "screenshot", "power")
        }
    if os_name == "Linux":
        return {
            "app_open": Capability("app_open", bool(binary("xdg-open", "gtk-launch")), "xdg", "desktop session"),
            "window_control": Capability("window_control", pyautogui_available or bool(binary("wmctrl")), "wmctrl/pyautogui", "desktop session"),
            "volume": Capability("volume", bool(binary("pactl")), "pactl", "PulseAudio/PipeWire"),
            "brightness": Capability("brightness", bool(binary("brightnessctl")), "brightnessctl", "no shell fallback"),
            "media": Capability("media", pyautogui_available, "pyautogui", "focused application"),
            "screenshot": Capability("screenshot", pyautogui_available, "pyautogui", "Desktop/Pictures only"),
            "power": Capability("power", bool(binary("systemctl")), "systemctl", "approval + confirmation"),
        }
    return {
        name: Capability(name, False, "none", f"unsupported platform: {os_name}")
        for name in ("app_open", "window_control", "volume", "brightness", "media", "screenshot", "power")
    }


def format_capabilities(system: str | None = None, *, pyautogui_available: bool = False) -> str:
    matrix = capability_matrix(system, pyautogui_available=pyautogui_available)
    lines = [f"System capabilities ({system or platform.system()}):"]
    for item in matrix.values():
        status = "available" if item.available else "unavailable"
        lines.append(f"- {item.name}: {status} [{item.backend}] — {item.detail}")
    return "\n".join(lines)
