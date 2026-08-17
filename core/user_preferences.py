from __future__ import annotations

import re


_ADDRESS = re.compile(r"^[^\x00-\x1f\x7f]{1,30}$")


def preferred_address() -> str:
    try:
        from memory.config_manager import get_config

        value = " ".join(str(get_config("preferred_address") or "").split())
    except Exception:
        return ""
    return value if _ADDRESS.fullmatch(value) else ""


def personalize_address(text: str, address: str | None = None) -> str:
    """Replace legacy fixed honorifics at the user-visible output boundary."""
    rendered = str(text)
    selected = preferred_address() if address is None else " ".join(str(address).split())
    if selected and not _ADDRESS.fullmatch(selected):
        selected = ""
    rendered = re.sub(r"\bsir\b", selected, rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"\s+([,.;:!?])", r"\1", rendered)
    rendered = re.sub(r"([,;:])\s*([.!?])", r"\2", rendered)
    rendered = re.sub(r"^[,;:]\s*", "", rendered)
    rendered = re.sub(r" {2,}", " ", rendered)
    return rendered.strip()
