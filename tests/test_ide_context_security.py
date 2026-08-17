from collections import deque
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest

from core.ide_context import (
    ContextRequestHandler,
    ContextServer,
    MAX_BODY_BYTES,
    RATE_LIMIT_REQUESTS,
    _write_session_file,
    current_ide_context,
    stop_context_server,
)


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeServer:
    context_token = "test-token-abcdefghijklmnopqrstuvwxyz012345"

    def __init__(self, allowed=True):
        self.allowed = allowed

    def allow_request(self):
        return self.allowed


def _run_handler(method="POST", payload=None, *, token=None, length=None, allowed=True):
    data = payload if payload is not None else {
        "file_path": "/tmp/example.py",
        "language": "python",
        "cursor_line": 4,
        "selection": "print('safe')",
    }
    body = json.dumps(data).encode("utf-8")
    handler = object.__new__(ContextRequestHandler)
    handler.path = "/"
    handler.server = _FakeServer(allowed=allowed)
    handler.headers = _Headers({"Content-Length": str(length or len(body))})
    if token is not None:
        handler.headers["Authorization"] = f"Bearer {token}"
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    handler.request_version = "HTTP/1.1"
    handler.command = method
    handler.responses = []
    handler.sent_headers = {}
    handler.send_response = lambda status, *args: handler.responses.append(status)
    handler.send_header = lambda key, value: handler.sent_headers.__setitem__(key, value)
    handler.end_headers = lambda: None
    getattr(handler, f"do_{method}")()
    return handler.responses[-1], handler.sent_headers, handler.wfile.getvalue()


class IDEContextSecurityTests(unittest.TestCase):
    token = _FakeServer.context_token

    def test_session_file_is_private_and_lifecycle_removes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "session.json"
            _write_session_file(token_path, self.token, 47384)
            session = json.loads(token_path.read_text(encoding="utf-8"))
            self.assertEqual(session["token"], self.token)
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

            fake_server = SimpleNamespace(
                shutdown=lambda: None,
                server_close=lambda: None,
                server_thread=None,
                token_path=token_path,
                context_token=self.token,
            )
            stop_context_server(fake_server)
            self.assertFalse(token_path.exists())

    def test_auth_is_required_and_cors_is_not_open(self):
        status, _, _ = _run_handler(token=None)
        self.assertEqual(status, 401)
        status, headers, _ = _run_handler(token=self.token)
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_only_post_and_bounded_valid_schema_are_accepted(self):
        status, _, _ = _run_handler(method="GET", token=self.token)
        self.assertEqual(status, 405)
        status, _, _ = _run_handler(payload={"selection": "x"}, token=self.token)
        self.assertEqual(status, 400)
        status, _, _ = _run_handler(
            token=self.token, length=MAX_BODY_BYTES + 1
        )
        self.assertEqual(status, 413)

    def test_secrets_are_redacted_and_context_is_untrusted_data(self):
        payload = {
            "file_path": "/tmp/example.py",
            "language": "python",
            "cursor_line": 4,
            "selection": "API_KEY=super-secret-value",
        }
        status, _, _ = _run_handler(payload=payload, token=self.token)
        self.assertEqual(status, 200)
        context = current_ide_context.get_context_string()
        self.assertIn("UNTRUSTED IDE CONTEXT", context)
        self.assertIn("[REDACTED]", context)
        self.assertNotIn("super-secret-value", context)

    def test_rate_limit_fails_closed(self):
        server = object.__new__(ContextServer)
        now = time.monotonic()
        server.request_times = deque([now] * RATE_LIMIT_REQUESTS)
        server.rate_lock = threading.Lock()
        self.assertFalse(server.allow_request())
        status, _, _ = _run_handler(token=self.token, allowed=False)
        self.assertEqual(status, 429)


if __name__ == "__main__":
    unittest.main()
