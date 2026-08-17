from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def health_payload() -> dict[str, str]:
    return {
        "service": "misha-cloud",
        "status": "ok",
        "intelligence": "local-only",
    }


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "MishaHealth/1.0"

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in {"/", "/health"}:
            self._reply(200, health_payload())
            return
        self._reply(404, {"status": "not_found"})

    def log_message(self, format: str, *args) -> None:
        print(f"[MishaCloud] {self.address_string()} {format % args}")


def create_server(host: str = "0.0.0.0", port: int | None = None) -> ThreadingHTTPServer:
    selected_port = int(os.getenv("PORT", "8080")) if port is None else int(port)
    return ThreadingHTTPServer((host, selected_port), HealthHandler)


def main() -> None:
    server = create_server()
    print(f"[MishaCloud] health service listening on {server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
