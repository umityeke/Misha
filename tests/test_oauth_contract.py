import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from core.integrations.oauth import (
    GOOGLE_AUTHORIZATION_URL,
    GOOGLE_CALENDAR_SCOPES,
    GOOGLE_TOKEN_URL,
    OAuthFlow,
    OAuthProvider,
)


class OAuthContractTests(unittest.TestCase):
    def provider(self):
        return OAuthProvider(
            name="google",
            client_id="owner-created-client-id",
            authorization_url=GOOGLE_AUTHORIZATION_URL,
            token_url=GOOGLE_TOKEN_URL,
            scopes=GOOGLE_CALENDAR_SCOPES,
            redirect_uri="http://127.0.0.1:8765/oauth/callback",
        )

    def test_pkce_authorization_is_one_shot_and_loopback_only(self):
        flow = OAuthFlow(self.provider(), "oauth-google-calendar")
        url = flow.begin()
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:8765/oauth/callback"])
        self.assertNotIn("client_secret", query)
        self.assertGreaterEqual(len(query["state"][0]), 32)
        with patch.object(flow.http, "post") as post, self.assertRaises(PermissionError):
            flow.complete("code", "wrong-state")
        post.assert_not_called()

    def test_exchange_stores_tokens_only_in_os_credential_store(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "access_token": "access-value",
            "refresh_token": "refresh-value",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
        }
        http = Mock()
        http.post.return_value = response
        flow = OAuthFlow(self.provider(), "oauth-google-calendar", http=http)
        url = flow.begin()
        state = parse_qs(urlsplit(url).query)["state"][0]
        with patch("core.integrations.oauth.set_secret") as store:
            token = flow.complete("authorization-code", state)
        self.assertEqual(token.refresh_token, "refresh-value")
        store.assert_called_once()
        stored = json.loads(store.call_args.args[1])
        self.assertEqual(stored["access_token"], "access-value")
        self.assertNotIn("authorization-code", store.call_args.args[1])
        request_data = http.post.call_args.kwargs["data"]
        self.assertIn("code_verifier", request_data)
        self.assertNotIn("client_secret", request_data)

    def test_refresh_preserves_refresh_token_and_rejects_scope_escalation(self):
        stored = json.dumps({
            "access_token": "old",
            "refresh_token": "refresh",
            "token_type": "Bearer",
            "expires_at": 1,
            "scopes": list(GOOGLE_CALENDAR_SCOPES),
        })
        response = Mock(status_code=200)
        response.json.return_value = {
            "access_token": "new",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
        }
        http = Mock()
        http.post.return_value = response
        flow = OAuthFlow(self.provider(), "oauth-google-calendar", http=http)
        with patch("core.integrations.oauth.get_secret", return_value=stored), patch(
            "core.integrations.oauth.set_secret"
        ) as store:
            refreshed = flow.refresh()
        self.assertEqual(refreshed.refresh_token, "refresh")
        self.assertIn('"refresh_token":"refresh"', store.call_args.args[1])
        response.json.return_value["scope"] = "admin.everything"
        with patch("core.integrations.oauth.get_secret", return_value=stored), self.assertRaisesRegex(
            RuntimeError, "outside"
        ):
            flow.refresh()

    def test_provider_endpoints_and_redirect_are_allowlisted(self):
        with self.assertRaisesRegex(ValueError, "allowlist"):
            OAuthProvider(
                name="google", client_id="id",
                authorization_url="https://attacker.example/auth",
                token_url=GOOGLE_TOKEN_URL,
                scopes=GOOGLE_CALENDAR_SCOPES,
                redirect_uri="http://127.0.0.1:8765/oauth/callback",
            )
        with self.assertRaisesRegex(ValueError, "loopback"):
            OAuthProvider(
                name="google", client_id="id",
                authorization_url=GOOGLE_AUTHORIZATION_URL,
                token_url=GOOGLE_TOKEN_URL,
                scopes=GOOGLE_CALENDAR_SCOPES,
                redirect_uri="https://public.example/oauth/callback",
            )


if __name__ == "__main__":
    unittest.main()
