"""
HTTP client for the Space Agent (see `agent/` at the repo root).

This is the transport layer bench_client.py uses instead of SSH: the
control plane calls the Agent's REST API, and the Agent — already running
on the target Space Server — executes the command locally.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class AgentError(Exception):
    def __init__(self, message: str, stdout: str = "", stderr: str = "", code: int = 1):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.code = code


def call(
    server,
    argv: list[str],
    *,
    cwd: str | None = None,
    timeout_s: float = 300,
) -> dict[str, Any]:
    """POST /exec on `server`'s Space Agent. Returns {ok, code, stdout, stderr}."""
    endpoint = (server.agent_endpoint or "").strip().rstrip("/")
    if not endpoint:
        raise AgentError(f"Space Server {server.name} has no agent_endpoint configured")
    try:
        token = server.get_password("agent_token")
    except Exception:
        token = None
    if not token:
        raise AgentError(f"Space Server {server.name} has no agent_token configured")

    body = json.dumps(
        {
            "argv": argv,
            "container": server.backend_container,
            "cwd": cwd,
            "timeout_s": timeout_s,
        }
    ).encode()

    req = urllib.request.Request(
        f"{endpoint}/exec",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        # A little slack over the command's own timeout for network/agent overhead.
        with urllib.request.urlopen(req, timeout=timeout_s + 15) as res:
            result = json.loads(res.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("error")
        except Exception:
            detail = e.reason
        raise AgentError(f"Space Agent error ({e.code}): {detail}") from e
    except urllib.error.URLError as e:
        raise AgentError(f"Could not reach Space Agent at {endpoint}: {e.reason}") from e
    except TimeoutError as e:
        raise AgentError("Space Agent request timed out", code=124) from e

    if not result.get("ok"):
        raise AgentError(
            (result.get("stderr") or result.get("stdout") or "Command failed")[:500],
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            code=result.get("code", 1),
        )
    return result


def ping(server) -> bool:
    endpoint = (server.agent_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return False
    try:
        with urllib.request.urlopen(f"{endpoint}/ping", timeout=5) as res:
            return json.loads(res.read()).get("ok", False)
    except Exception:
        return False
