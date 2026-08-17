from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from itertools import islice


_SAFE_DETAIL_KEYS = {
    "error_type", "priority", "reason", "result_status", "verification",
}
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _safe_text(value, limit: int) -> str:
    return " ".join(_CONTROL_RE.sub(" ", str(value)).split())[:limit]


def format_audit_events(events: Iterable[Mapping], limit: int = 200) -> str:
    """Render an allowlisted audit summary without exposing private detail fields."""
    try:
        safe_limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        safe_limit = 200
    lines = []
    for event in islice(events, safe_limit):
        timestamp = _safe_text(event.get("timestamp", ""), 25)
        category = _safe_text(event.get("category", "unknown"), 60)
        action = _safe_text(event.get("action", "unknown"), 80)
        status = _safe_text(event.get("status", "unknown"), 30).upper()
        tool = _safe_text(event.get("tool", ""), 60)
        header = f"{timestamp}  [{status}]  {category} / {action}"
        if tool:
            header += f"  tool={tool}"
        lines.append(header[:300])
        details = event.get("details")
        if isinstance(details, Mapping):
            safe_details = []
            for key in sorted(_SAFE_DETAIL_KEYS):
                if key in details:
                    safe_details.append(
                        f"{key}={_safe_text(details[key], 120)}"
                    )
            if safe_details:
                lines.append("    " + " · ".join(safe_details)[:500])
    return "\n".join(lines) if lines else "No local security events yet."
