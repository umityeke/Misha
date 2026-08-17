from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from core.credential_store import get_secret, set_secret


GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
MICROSOFT_AUTHORIZATION_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

GOOGLE_CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)
GOOGLE_MAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
)
MICROSOFT_CALENDAR_SCOPES = ("offline_access", "Calendars.ReadWrite")
MICROSOFT_MAIL_SCOPES = ("offline_access", "Mail.Read", "Mail.ReadWrite", "Mail.Send")


@dataclass(frozen=True)
class OAuthProvider:
    name: str
    client_id: str
    authorization_url: str
    token_url: str
    scopes: tuple[str, ...]
    redirect_uri: str

    def __post_init__(self) -> None:
        if self.name not in {"google", "microsoft"} or not self.client_id.strip():
            raise ValueError("OAuth provider and client ID are required.")
        expected_hosts = {
            "google": {"accounts.google.com", "oauth2.googleapis.com"},
            "microsoft": {"login.microsoftonline.com"},
        }[self.name]
        for endpoint in (self.authorization_url, self.token_url):
            parsed = urlsplit(endpoint)
            if parsed.scheme != "https" or parsed.hostname not in expected_hosts:
                raise ValueError("OAuth endpoint is outside the provider allowlist.")
        redirect = urlsplit(self.redirect_uri)
        if (
            redirect.scheme != "http"
            or redirect.hostname not in {"127.0.0.1", "localhost"}
            or redirect.port is None
            or not 1024 <= redirect.port <= 65535
            or redirect.path != "/oauth/callback"
        ):
            raise ValueError("OAuth redirect must use a bounded loopback callback.")
        if not self.scopes or len(self.scopes) > 12 or any(not item.strip() for item in self.scopes):
            raise ValueError("OAuth scopes are missing or too broad in count.")


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    refresh_token: str
    token_type: str
    expires_at: float
    scopes: tuple[str, ...]

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 60


class OAuthFlow:
    """One-shot OAuth Authorization Code + PKCE flow with OS-store tokens."""

    def __init__(
        self,
        provider: OAuthProvider,
        credential_name: str,
        *,
        http: Any = requests,
    ) -> None:
        self.provider = provider
        self.credential_name = credential_name
        self.http = http
        self._state = ""
        self._verifier = ""
        self._expires_at = 0.0

    @staticmethod
    def _challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def begin(self) -> str:
        self._state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(64)
        self._expires_at = time.monotonic() + 600
        parameters = {
            "client_id": self.provider.client_id,
            "redirect_uri": self.provider.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.provider.scopes),
            "state": self._state,
            "code_challenge": self._challenge(self._verifier),
            "code_challenge_method": "S256",
        }
        if self.provider.name == "google":
            parameters.update({"access_type": "offline", "prompt": "consent"})
        return f"{self.provider.authorization_url}?{urlencode(parameters)}"

    def complete(self, code: str, state: str) -> OAuthToken:
        if (
            not self._state
            or not secrets.compare_digest(str(state), self._state)
            or time.monotonic() > self._expires_at
        ):
            self._clear_pending()
            raise PermissionError("OAuth callback state is invalid or expired.")
        verifier = self._verifier
        self._clear_pending()
        if not str(code).strip() or len(str(code)) > 4096:
            raise ValueError("OAuth authorization code is invalid.")
        response = self.http.post(
            self.provider.token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": self.provider.client_id,
                "code": str(code),
                "redirect_uri": self.provider.redirect_uri,
                "code_verifier": verifier,
            },
            timeout=15,
        )
        token = self._parse_response(response, fallback_refresh="")
        self._store(token)
        return token

    def _clear_pending(self) -> None:
        self._state = ""
        self._verifier = ""
        self._expires_at = 0.0

    def _parse_response(self, response: Any, *, fallback_refresh: str) -> OAuthToken:
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"OAuth token exchange failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
            access = str(payload["access_token"])
            refresh = str(payload.get("refresh_token") or fallback_refresh)
            expires_in = int(payload.get("expires_in", 3600))
            token_type = str(payload.get("token_type", "Bearer"))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("OAuth provider returned an invalid token response.") from exc
        if not access or token_type.casefold() != "bearer" or not 60 <= expires_in <= 86_400:
            raise RuntimeError("OAuth provider returned unsafe token metadata.")
        returned_scopes = tuple(str(payload.get("scope", "")).split()) or self.provider.scopes
        if not set(returned_scopes).issubset(set(self.provider.scopes)):
            raise RuntimeError("OAuth provider returned scopes outside the request.")
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            token_type="Bearer",
            expires_at=time.time() + expires_in,
            scopes=returned_scopes,
        )

    def _store(self, token: OAuthToken) -> None:
        payload = json.dumps({
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "token_type": token.token_type,
            "expires_at": token.expires_at,
            "scopes": list(token.scopes),
        }, separators=(",", ":"), sort_keys=True)
        set_secret(self.credential_name, payload)

    def load(self) -> OAuthToken | None:
        raw = get_secret(self.credential_name)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            token = OAuthToken(
                access_token=str(payload["access_token"]),
                refresh_token=str(payload.get("refresh_token", "")),
                token_type=str(payload["token_type"]),
                expires_at=float(payload["expires_at"]),
                scopes=tuple(str(item) for item in payload["scopes"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored OAuth credential is invalid.") from exc
        if (
            not token.access_token
            or token.token_type != "Bearer"
            or not set(token.scopes).issubset(set(self.provider.scopes))
        ):
            raise RuntimeError("Stored OAuth credential violates the provider contract.")
        return token

    def refresh(self) -> OAuthToken:
        current = self.load()
        if current is None or not current.refresh_token:
            raise RuntimeError("OAuth refresh token is unavailable; reconnect the account.")
        response = self.http.post(
            self.provider.token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": self.provider.client_id,
                "refresh_token": current.refresh_token,
            },
            timeout=15,
        )
        token = self._parse_response(response, fallback_refresh=current.refresh_token)
        self._store(token)
        return token
