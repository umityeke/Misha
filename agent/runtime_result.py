from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from agent.verifier import VerificationResult


class ResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    UNVERIFIED = "unverified"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: ResultStatus
    output: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    attempt: int = 1
    verification: VerificationResult | None = None
    retryable: bool | None = None
    retry_category: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status is ResultStatus.SUCCEEDED


@dataclass(frozen=True)
class ExecutionResult:
    status: ResultStatus
    message: str
    step_results: tuple[ToolResult, ...] = field(default_factory=tuple)
    request_id: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status is ResultStatus.SUCCEEDED

    def __str__(self) -> str:
        return self.message
