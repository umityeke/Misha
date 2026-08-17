from __future__ import annotations

import re
from dataclasses import dataclass


_TRANSIENT = re.compile(
    r"(?i)(?:temporar(?:y|ily)|timed?\s*out|timeout|connection\s+(?:reset|refused|aborted)|"
    r"service\s+unavailable|try\s+again|rate\s*limit|too\s+many\s+requests|"
    r"resource\s+busy|database\s+is\s+locked|file\s+is\s+locked|eagain)"
)
_PERMANENT = re.compile(
    r"(?i)(?:permission\s+denied|not\s+authorized|unauthorized|forbidden|invalid|"
    r"validation|unsupported|does\s+not\s+exist|not\s+found|approval|required|rejected)"
)


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    category: str


def classify_retry(error: BaseException | str) -> RetryDecision:
    """Classify retry safety without sending error details to a model."""
    if isinstance(error, (TimeoutError, ConnectionError)):
        return RetryDecision(True, "transient_io")
    message = " ".join(str(error).split())[:500]
    if _PERMANENT.search(message):
        return RetryDecision(False, "permanent")
    if _TRANSIENT.search(message):
        return RetryDecision(True, "transient")
    return RetryDecision(False, "unknown")


def exponential_backoff(attempt: int, *, base_seconds: float = 0.25) -> float:
    bounded_attempt = max(1, min(int(attempt), 4))
    return min(2.0, max(0.0, float(base_seconds)) * (2 ** (bounded_attempt - 1)))
