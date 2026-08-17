from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


DEFAULT_BLOCKED_APPS = frozenset({
    "1password", "bitwarden", "dashlane", "enpass", "keepass", "keepassxc",
    "keychain access", "lastpass", "passwords", "proton pass", "secrets",
})
_CREDENTIAL_TITLE_RE = re.compile(
    r"(?i)\b(?:password|passkey|one[- ]time|verification code|two[- ]factor|2fa|"
    r"authenticator|credential|api key|access token|private key|seed phrase|"
    r"recovery phrase|wallet recovery|şifre|parola|doğrulama kodu|kimlik bilgisi)\b"
    r"|(?i:\b(?:private memory|memory manager|memory record|özel hafıza|"
    r"hafıza yöneticisi|hafıza kaydı|task recovery|interrupted task|"
    r"görev kurtarma|yarım görev)\b)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|"
    r"parola|şifre|secret|authorization)\s*[:=]\s*[^\s,;]+"
)
_PRIVATE_KEY_RE = re.compile(
    r"(?is)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_URL_CREDENTIAL_RE = re.compile(r"(?i)\b(https?://)[^\s/@:]+:[^\s/@]+@")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


@dataclass(frozen=True)
class ProtectedObservation:
    allowed: bool
    text: str = ""
    reason: str = ""


def normalize_denylist(values: list[str] | tuple[str, ...] | set[str] | None) -> tuple[str, ...]:
    normalized = []
    for value in values or ():
        item = " ".join(str(value).casefold().split()).strip()
        if item and len(item) <= 200 and item not in normalized:
            normalized.append(item)
    return tuple(normalized[:100])


def redact_observation(text: str) -> str:
    value = str(text)[:64_000]
    value = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", value)
    value = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    value = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", value)
    value = _CARD_RE.sub("[REDACTED PAYMENT DATA]", value)
    value = _EMAIL_RE.sub("[REDACTED EMAIL]", value)
    return value[:16_000]


def protect_observation(
    app_name: str,
    window_title: str,
    text: str,
    *,
    denylist: list[str] | tuple[str, ...] | set[str] | None = None,
) -> ProtectedObservation:
    app = " ".join(str(app_name).casefold().split())
    title = " ".join(str(window_title).casefold().split())
    haystack = f"{app}\n{title}\n{str(text)[:2_000].casefold()}"
    if any(blocked in app for blocked in DEFAULT_BLOCKED_APPS):
        return ProtectedObservation(False, reason="password_manager")
    if _CREDENTIAL_TITLE_RE.search(title):
        return ProtectedObservation(False, reason="credential_screen")
    for blocked in normalize_denylist(denylist):
        domain = urlsplit(blocked if "://" in blocked else f"https://{blocked}").hostname
        candidate = domain.casefold() if domain else blocked
        if blocked in haystack or candidate in haystack:
            return ProtectedObservation(False, reason="user_denylist")
    return ProtectedObservation(True, redact_observation(text))
