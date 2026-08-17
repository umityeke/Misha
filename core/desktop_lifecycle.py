from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path


LAUNCH_AGENT_LABEL = "com.umityeke.misha"


def launch_agent_path(home: Path | None = None) -> Path:
    base = Path(home) if home is not None else Path.home()
    return base / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def launch_command() -> list[str]:
    """Return an absolute, shell-free command for the current installation."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    return [str(Path(sys.executable).resolve()), str((Path(__file__).parent.parent / "main.py").resolve())]


def set_launch_at_login(
    enabled: bool,
    *,
    home: Path | None = None,
    command: list[str] | None = None,
) -> bool:
    """Install or remove Misha's user-scoped macOS LaunchAgent."""
    if sys.platform != "darwin":
        return False
    target = launch_agent_path(home)
    if not enabled:
        target.unlink(missing_ok=True)
        return False

    args = [str(value) for value in (command or launch_command()) if str(value).strip()]
    if not args or not all(Path(value).is_absolute() for value in args[:1]):
        raise ValueError("Launch command must start with an absolute executable path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
    }
    temporary = target.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    return True


def launch_at_login_enabled(home: Path | None = None) -> bool:
    return sys.platform == "darwin" and launch_agent_path(home).is_file()
