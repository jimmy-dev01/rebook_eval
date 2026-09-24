"""HTTP boundary for the eight airline tools.

Purpose: an agent process must not be able to read `fixture.json`,
`task.json`, or `policy.md` directly — only through the tool calls it
chooses to make. Running the grader and the agent as two Python objects in
one process (as `rebook.env.session.Session` does today) enforces that only
by convention: nothing stops new code from importing `World` or
`load_private_task` directly. Putting this server in its own **container**,
with only this file and `rebook/` on its image, makes the boundary a real
filesystem/process fence: `rebook-sample-package/` and `rebook/grader/`
never ship to whatever image runs the agent (see `docker/Dockerfile.agent`
vs `docker/Dockerfile.evaluator`, and `docker-compose.yml`).

This module adds no new privacy logic. Every response still goes through
`Session.step`, which already calls `assert_no_leakage` (`rebook/privacy.py`)
before returning. The server is the transport; the boundary is the same one
already tested in `tests/test_privacy.py`. `tests/test_server.py` exercises
this file in-process (no Docker needed) to prove the HTTP layer itself adds
no new leak (e.g. a stack trace on a bad request).

Endpoints:
    POST /reset            -> {"session_id": str, "observation": {...}}
    POST /step              {"session_id": str, "action": {...}}
                           -> the tool result (or {"error": ...})
    GET  /healthz          -> {"ok": true}

Run standalone with: python -m rebook.server [--host H] [--port P]
"""
from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from rebook.env.session import Session
from rebook.paths import CLIENT

_LOCK = threading.Lock()
_SESSIONS: dict[str, Session] = {}


def _new_session() -> tuple[str, Session]:
    session = Session.reset(CLIENT)
    session_id = uuid.uuid4().hex
    with _LOCK:
        _SESSIONS[session_id] = session
    return session_id, session


def _get_session(session_id: str) -> Optional[Session]:
    with _LOCK:
        return _SESSIONS.get(session_id)


class EvaluatorHandler(BaseHTTPRequestHandler):
    server_version = "RB01Evaluator/1"

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self):  # noqa: N802 - http.server naming
        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": f"unknown path {self.path}"})

    def do_POST(self):  # noqa: N802 - http.server naming
        try:
            if self.path == "/reset":
                session_id, session = _new_session()
                self._send_json(
                    200,
                    {"session_id": session_id, "observation": session.observation()},
                )
                return
            if self.path == "/step":
                body = self._read_json()
                session = _get_session(body.get("session_id", ""))
                if session is None:
                    self._send_json(404, {"error": "unknown session_id; call /reset first"})
                    return
                result = session.step(body.get("action") or {})
                self._send_json(200, {"result": result})
                return
            self._send_json(404, {"error": f"unknown path {self.path}"})
        except Exception as exc:  # noqa: BLE001
            # Deliberately generic: never echo exception context that might
            # carry fixture contents (e.g. a KeyError repr of a private dict).
            self._send_json(400, {"error": f"bad request: {type(exc).__name__}"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # quiet by default; rely on the caller's own logging if needed


def serve(host: str = "0.0.0.0", port: int = 8000) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), EvaluatorHandler)
    return httpd


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="RB01 evaluator HTTP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    httpd = serve(args.host, args.port)
    print(f"rebook evaluator listening on {args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
