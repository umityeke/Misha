from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SENSITIVE = re.compile(
    r"(?i)\b(password|parola|şifre|api[ _-]?key|token|otp|one[ -]?time|"
    r"credit[ -]?card|kredi kartı|iban|passport|pasaport|medical|sağlık)\b"
)
_BLOCKED_EXTENSIONS = {
    ".app", ".bat", ".cmd", ".com", ".exe", ".js", ".jse", ".lnk",
    ".msi", ".ps1", ".scr", ".vbs", ".wsf",
}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class MailMessage:
    message_id: str
    thread_id: str
    sender: str
    recipients: tuple[str, ...]
    subject: str
    body: str
    attachments: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if len(self.recipients) > 50 or any(not _EMAIL.fullmatch(item) for item in self.recipients):
            raise ValueError("Mail recipients must be bounded valid addresses.")
        if len(self.subject) > 998 or len(self.body.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Mail subject or body exceeds the safe limit.")


@dataclass(frozen=True)
class MailSubmission:
    accepted: bool
    receipt_id: str = ""


class MailProvider(Protocol):
    def inbox(self, limit: int) -> list[MailMessage]: ...
    def search(self, query: str, limit: int) -> list[MailMessage]: ...
    def thread(self, thread_id: str) -> list[MailMessage]: ...
    def create_draft(self, message: MailMessage) -> MailMessage: ...
    def send(self, message: MailMessage) -> MailSubmission: ...


def validate_attachments(paths: tuple[Path, ...], allowed_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    if len(paths) > 10:
        raise ValueError("At most ten attachments are allowed.")
    validated: list[Path] = []
    total = 0
    roots = tuple(root.resolve() for root in allowed_roots)
    for raw in paths:
        path = Path(raw)
        resolved = path.resolve()
        if (
            not path.is_file() or path.is_symlink()
            or not any(resolved.is_relative_to(root) for root in roots)
        ):
            raise ValueError("Attachment must be a regular file inside an allowed root.")
        if path.suffix.casefold() in _BLOCKED_EXTENSIONS:
            raise ValueError("Executable or script attachments are blocked.")
        total += path.stat().st_size
        if total > MAX_ATTACHMENT_BYTES:
            raise ValueError("Attachments exceed the 20 MiB total limit.")
        validated.append(resolved)
    return tuple(validated)


def sensitive_content_warning(message: MailMessage) -> str | None:
    return "Sensitive content detected; review before sending." if _SENSITIVE.search(
        f"{message.subject}\n{message.body}"
    ) else None


def submission_fingerprint(message: MailMessage) -> str:
    payload = "\0".join((*message.recipients, message.subject, message.body))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MailService:
    def __init__(self, provider: MailProvider, *, allowed_roots: tuple[Path, ...]) -> None:
        self.provider = provider
        self.allowed_roots = allowed_roots

    def inbox(self, limit: int = 20) -> list[MailMessage]:
        return self.provider.inbox(max(1, min(int(limit), 100)))

    def search(self, query: str, limit: int = 20) -> list[MailMessage]:
        normalized = " ".join(str(query).split())[:500]
        if not normalized:
            raise ValueError("Mail search query is required.")
        return self.provider.search(normalized, max(1, min(int(limit), 100)))

    def summarize(self, message: MailMessage) -> str:
        snippet = " ".join(message.body.split())[:500]
        return f"From {message.sender}; subject {message.subject}; {snippet}"

    def draft(self, message: MailMessage) -> MailMessage:
        attachments = validate_attachments(message.attachments, self.allowed_roots)
        return self.provider.create_draft(
            MailMessage(**{**message.__dict__, "attachments": attachments})
        )

    def reply_draft(self, original: MailMessage, body: str) -> MailMessage:
        if not original.thread_id or not _EMAIL.fullmatch(original.sender):
            raise ValueError("A valid original thread and sender are required.")
        reply = MailMessage(
            message_id="",
            thread_id=original.thread_id,
            sender="",
            recipients=(original.sender,),
            subject=original.subject if original.subject.lower().startswith("re:") else f"Re: {original.subject}",
            body=body,
        )
        return self.draft(reply)

    def send(
        self,
        message: MailMessage,
        *,
        approved_fingerprint: str,
        sensitive_content_approved: bool = False,
    ) -> MailSubmission:
        validated = MailMessage(
            **{**message.__dict__, "attachments": validate_attachments(message.attachments, self.allowed_roots)}
        )
        if approved_fingerprint != submission_fingerprint(validated):
            raise PermissionError("Mail recipient/content approval does not match the final message.")
        if sensitive_content_warning(validated) and not sensitive_content_approved:
            raise PermissionError("Sensitive mail content requires a separate approval.")
        result = self.provider.send(validated)
        if not result.accepted or not result.receipt_id.strip():
            return MailSubmission(False, "")
        return result
