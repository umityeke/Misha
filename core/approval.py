from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from core.action_policy import approval_prompt


def _audit_approval(action: str, status: str, tool_name: str, **details) -> None:
    try:
        from core.audit_logger import AuditEvent, log_event

        log_event(AuditEvent(
            category="approval",
            action=action,
            status=status,
            tool=str(tool_name)[:120],
            details=details,
        ))
    except Exception:
        pass


class ApprovalError(PermissionError):
    pass


def _scope_fingerprint(tool_name: str, parameters: dict) -> str:
    payload = json.dumps(
        {"tool": tool_name, "parameters": parameters},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ApprovalGrant:
    token: str
    tool_name: str
    scope_fingerprint: str
    expires_at: float


class ApprovalManager:
    """Issues in-memory, single-use grants bound to one exact tool call."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(1.0, min(float(ttl_seconds), 300.0))
        self.clock = clock
        self._grants: dict[str, ApprovalGrant] = {}
        self._lock = threading.RLock()

    def request(
        self,
        tool_name: str,
        parameters: dict,
        reason: str,
        approve: Callable[[str], bool] | None,
    ) -> ApprovalGrant | None:
        if approve is None:
            _audit_approval(
                "request", "blocked", tool_name,
                reason="approval_callback_missing",
            )
            return None
        _audit_approval("request", "presented", tool_name, reason=reason)
        try:
            approved = bool(approve(approval_prompt(tool_name, parameters, reason)))
        except Exception as exc:
            _audit_approval(
                "request", "failed", tool_name,
                reason="approval_ui_failure", error_type=type(exc).__name__,
            )
            raise
        if not approved:
            _audit_approval("request", "rejected", tool_name, reason=reason)
            return None
        grant = ApprovalGrant(
            token=secrets.token_urlsafe(24),
            tool_name=tool_name,
            scope_fingerprint=_scope_fingerprint(tool_name, parameters),
            expires_at=self.clock() + self.ttl_seconds,
        )
        with self._lock:
            self._grants[grant.token] = grant
        _audit_approval("request", "approved", tool_name, reason=reason)
        return grant

    def consume(self, token: str, tool_name: str, parameters: dict) -> None:
        with self._lock:
            grant = self._grants.pop(token, None)
        if grant is None:
            _audit_approval(
                "consume", "rejected", tool_name,
                reason="missing_invalid_or_used",
            )
            raise ApprovalError("Approval is missing, invalid, or already used.")
        if self.clock() > grant.expires_at:
            _audit_approval("consume", "expired", tool_name, reason="ttl_expired")
            raise ApprovalError("Approval expired before the action started.")
        expected = _scope_fingerprint(tool_name, parameters)
        if grant.tool_name != tool_name or grant.scope_fingerprint != expected:
            _audit_approval(
                "consume", "rejected", tool_name, reason="scope_mismatch"
            )
            raise ApprovalError("Approval scope does not match this action.")
        _audit_approval("consume", "consumed", tool_name, reason="single_use")

    def revoke_all(self) -> int:
        with self._lock:
            count = len(self._grants)
            self._grants.clear()
        _audit_approval("revoke", "completed", "all", reason="task_finished")
        return count
