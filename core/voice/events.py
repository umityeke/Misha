from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class VoiceEvent:
    kind: str
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("Voice event kind cannot be empty.")
        if not self.session_id.strip():
            raise ValueError("Voice event session_id cannot be empty.")
