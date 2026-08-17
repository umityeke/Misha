from __future__ import annotations


def enforce_pyautogui_safety(module) -> None:
    """Apply the non-optional emergency-corner stop before every UI action."""
    if module is None:
        raise RuntimeError("PyAutoGUI is unavailable on this system.")
    module.FAILSAFE = True
    module.PAUSE = max(0.05, float(getattr(module, "PAUSE", 0.0) or 0.0))


def safe_window_title(value: str) -> str:
    title = " ".join(str(value).split())
    if not title or len(title) > 100:
        raise ValueError("Window title must contain 1–100 characters.")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._()-" for ch in title):
        raise ValueError("Window title contains unsupported characters.")
    return title
