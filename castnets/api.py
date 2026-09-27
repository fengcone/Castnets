import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .contract import openapi
from .models import DomainError


def make_server(service, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass  # Don't log questions or branch data.

        def send_json(self, status, payload):
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def body(self, required, optional=()):
            if self.headers.get("Transfer-Encoding"):
                raise DomainError("Chunked request bodies are unsupported")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise DomainError("Invalid Content-Length") from None
            if length < 0 or length > 16384:
                raise DomainError("Body must be at most 16384 bytes", "body_too_large", 413)
            if length and self.headers.get_content_type() != "application/json":
                raise DomainError("Content-Type must be application/json", "unsupported_media_type", 415)
            if not length:
                value = {}
            else:
                raw = self.rfile.read(length)
                try:
                    value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeError):
                    raise DomainError("Malformed JSON") from None
            if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
                raise DomainError("Unexpected or missing request fields")
            return value

        def dispatch(self):
            try:
                path = urlsplit(self.path).path
                parts = path.strip("/").split("/")
                if self.command == "GET":
                    if path == "/health":
                        return self.send_json(200, {"status": "ok", "mode": "mock"})
                    if path == "/openapi.json":
                        return self.send_json(200, openapi())
                    if path in ("/v1/podcasts", "/v1/episodes", "/v1/branches"):
                        return self.send_json(200, service.store.all(parts[1]))
                    if len(parts) == 3 and parts[:2] in (["v1", "podcasts"], ["v1", "episodes"], ["v1", "branches"]):
                        return self.send_json(200, service.store.get(parts[1], parts[2]))
                    if len(parts) == 4 and parts[:2] == ["v1", "podcasts"] and parts[3] == "episodes":
                        podcast = service.store.get("podcasts", parts[2])
                        return self.send_json(200, [episode for episode in service.store.all("episodes")
                                                    if episode["feed_url"] == podcast["feed_url"]])
                    if len(parts) == 4 and parts[:2] == ["v1", "episodes"] and parts[3] == "content":
                        return self.send_json(200, service.store.get("content", parts[2]))
                if self.command == "POST":
                    if path == "/v1/branches":
                        body = self.body(("episode_id", "anchor_ms", "question"), ("resume_offset_ms",))
                        return self.send_json(201, service.create_branch(**body))
                    if len(parts) == 4 and parts[:2] == ["v1", "branches"]:
                        if parts[3] == "turns":
                            return self.send_json(201, service.add_turn(parts[2], **self.body(("question",))))
                        if parts[3] == "resume":
                            self.body(())
                            return self.send_json(200, service.resume(parts[2]))
                raise DomainError("Route not found", "not_found", 404)
            except DomainError as exc:
                self.send_json(exc.status, {"error": {"code": exc.code, "message": str(exc)}})
            except TimeoutError:
                self.send_json(408, {"error": {"code": "request_timeout", "message": "Request timed out"}})
            except Exception:
                logging.exception("Local API request failed")
                self.send_json(500, {"error": {"code": "internal_error", "message": "Internal server error"}})

        do_GET = dispatch
        do_POST = dispatch

    # Deliberately loopback-only; no auth/TLS, not a deployable production server.
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
