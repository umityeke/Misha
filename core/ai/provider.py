from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    system: str = ""
    temperature: float = 0.2
    json_mode: bool = False
    options: dict[str, Any] = field(default_factory=dict)


class ProviderErrorKind(str, Enum):
    OFFLINE = "offline"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    AUTH = "auth"
    REQUEST = "request"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class ProviderError(RuntimeError):
    def __init__(
        self,
        kind: ProviderErrorKind,
        user_message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(user_message)
        self.kind = kind
        self.user_message = user_message
        self.retryable = bool(retryable)
        self.status_code = status_code


class AIProvider(Protocol):
    name: str

    def generate(self, request: GenerationRequest) -> str:
        """Generate a text response or raise a descriptive provider error."""

    def healthcheck(self) -> tuple[bool, str]:
        """Return provider availability and a user-facing status message."""

    def unload(self) -> None:
        """Release model memory without deleting the model from disk."""
