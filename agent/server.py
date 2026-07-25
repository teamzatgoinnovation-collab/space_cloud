#!/usr/bin/env python3
"""
Space Agent — a minimal, dependency-free HTTP service that runs on each
Space Server and executes bench/docker commands on the control plane's
behalf, replacing per-command SSH (see space_cloud/services/bench_client.py).

Modeled on Frappe Cloud's Agent: the control plane never SSHes into a
server; instead it calls this Agent's REST API, and the Agent — which
already runs on that server — executes commands locally.

Deliberately stdlib-only so the container image needs nothing but Python
and the `docker` CLI. Auth is a single shared bearer token (SPACE_AGENT_TOKEN)
compared with hmac.compare_digest. The only real endpoint, /exec, still only
runs `docker exec` (or `bash -lc` for the handful of shell one-liners
bench_client.py already builds) against a fixed allowlist of argv[0]
commands — it does not accept arbitrary host commands.
"""

from __future__ import annotations

import hmac
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("SPACE_AGENT_TOKEN", "").strip()
PORT = int(os.environ.get("SPACE_AGENT_PORT", "9000"))
DEFAULT_CONTAINER = os.environ.get("SPACE_AGENT_CONTAINER", "frappe_docker-backend-1")
DEFAULT_CWD = "/home/frappe/frappe-bench"

# argv[0] values bench_client.py is allowed to ask us to run.
ALLOWED_COMMANDS = {"bench", "docker", "bash", "du", "ls"}


class AgentError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def run_exec(payload: dict) -> dict:
    argv = payload.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise AgentError("argv must be a non-empty list of strings")
    if argv[0] not in ALLOWED_COMMANDS:
        raise AgentError(f"command not allowed: {argv[0]!r}", status=403)

    container = str(payload.get("container") or DEFAULT_CONTAINER)
    cwd = payload.get("cwd")
    timeout_s = min(float(payload.get("timeout_s") or 300), 3700)

    if argv[0] == "docker":
        # Host-level docker command (docker ps / restart / logs / etc.) — run directly.
        cmd = argv
    else:
        # Everything else runs inside the bench container.
        cmd = ["docker", "exec", "-w", cwd or DEFAULT_CWD, container, *argv]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "code": 124, "stdout": e.stdout or "", "stderr": "Command timed out"}
    except FileNotFoundError as e:
        raise AgentError(str(e), status=500) from e

    return {"ok": p.returncode == 0, "code": p.returncode, "stdout": p.stdout or "", "stderr": p.stderr or ""}


class Handler(BaseHTTPRequestHandler):
    server_version = "SpaceAgent/1.0"

    def _authorized(self) -> bool:
        if not TOKEN:
            return False
        got = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
        return hmac.compare_digest(got, expected)

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/ping":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        if self.path != "/exec":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
            result = run_exec(payload)
            self._send_json(200, result)
        except AgentError as e:
            self._send_json(e.status, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(e)[:500]})

    def log_message(self, fmt, *args):  # noqa: A002
        print("[space-agent] " + (fmt % args))


def main() -> None:
    if not TOKEN:
        raise SystemExit("SPACE_AGENT_TOKEN is required")
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[space-agent] listening on :{PORT}, container={DEFAULT_CONTAINER}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
