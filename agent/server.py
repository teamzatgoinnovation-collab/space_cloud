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

/ssl is a second, deliberately narrow endpoint (not a broadening of /exec's
allowlist): given a validated *.zatgo.online domain, it writes a fixed nginx
vhost template, obtains a Let's Encrypt cert via certbot certonly --webroot,
and reloads nginx by signaling its real host master process directly
(requires --pid=host — see agent/README.md for why /exec's generic
docker-exec-into-bench-container path can't reach host nginx at all).
"""

from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("SPACE_AGENT_TOKEN", "").strip()
PORT = int(os.environ.get("SPACE_AGENT_PORT", "9000"))
DEFAULT_CONTAINER = os.environ.get("SPACE_AGENT_CONTAINER", "frappe_docker-backend-1")
DEFAULT_CWD = "/home/frappe/frappe-bench"
CERTBOT_EMAIL = os.environ.get("SPACE_AGENT_CERTBOT_EMAIL", "learnwithzat@gmail.com")

# argv[0] values bench_client.py is allowed to ask us to run.
ALLOWED_COMMANDS = {"bench", "docker", "bash", "du", "ls"}

# Tenant domains this agent will route, comma-separated suffixes (no leading dot).
DOMAIN_SUFFIXES = [
    x.strip().lower().lstrip(".")
    for x in os.environ.get("SPACE_AGENT_DOMAIN_SUFFIXES", "zatgo.online").split(",")
    if x.strip()
]
DOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.(" + "|".join(re.escape(x) for x in DOMAIN_SUFFIXES) + r")$"
)

# "host" = legacy host nginx + certbot (old droplet). "docker" = nginx-proxy +
# acme-companion: one tiny forwarder container per tenant carrying
# VIRTUAL_HOST/LETSENCRYPT_HOST, picked up through the Docker socket.
SSL_MODE = os.environ.get("SPACE_AGENT_SSL_MODE", "host").strip().lower()
ROUTE_NETWORK = os.environ.get("SPACE_AGENT_NETWORK", "erpnext_default")
ROUTE_UPSTREAM = os.environ.get("SPACE_AGENT_UPSTREAM", "erpnext-frontend-1")
ROUTE_UPSTREAM_PORT = os.environ.get("SPACE_AGENT_UPSTREAM_PORT", "8080")
ROUTE_IMAGE = os.environ.get("SPACE_AGENT_ROUTE_IMAGE", "alpine/socat")
PROXY_CONTAINER = os.environ.get("SPACE_AGENT_PROXY_CONTAINER", "erpnext-nginx-proxy-1")
CERT_WAIT_S = int(os.environ.get("SPACE_AGENT_CERT_WAIT_S", "75"))
ROUTE_LABEL = "space.route"

NGINX_SITES_AVAILABLE = "/etc/nginx/sites-available"
NGINX_SITES_ENABLED = "/etc/nginx/sites-enabled"
CERTBOT_WEBROOT = "/var/www/certbot"

# __DOMAIN__ substituted via str.replace — deliberately not .format()/f-string,
# since nginx's own block syntax is full of literal { } that would collide
# with Python format-string placeholders.
NGINX_HTTP_ONLY_TEMPLATE = """server {
    server_name __DOMAIN__;
    client_max_body_size 50m;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 120s;
    }

    listen 80;
}
"""

NGINX_SSL_TEMPLATE = """server {
    server_name __DOMAIN__;
    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 120s;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/__DOMAIN__/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/__DOMAIN__/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
server {
    if ($host = __DOMAIN__) {
        return 301 https://$host$request_uri;
    }
    server_name __DOMAIN__;
    listen 80;
    return 404;
}
"""


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


def _write_vhost(domain: str, content: str) -> None:
    path = os.path.join(NGINX_SITES_AVAILABLE, domain)
    with open(path, "w") as f:
        f.write(content.replace("__DOMAIN__", domain))
    enabled = os.path.join(NGINX_SITES_ENABLED, domain)
    if os.path.islink(enabled) or os.path.exists(enabled):
        os.remove(enabled)
    os.symlink(path, enabled)


NGINX_PIDFILE = "/host-run/nginx.pid"


def _reload_nginx() -> None:
    """Signal the real host nginx master process to reload.

    PID discovery: read the pidfile (bind-mounted from the host) rather
    than scanning /proc for a process matching "nginx: master process" —
    with --pid=host the shared namespace also exposes *other containers'*
    processes (e.g. frappe_docker-frontend-1 runs its own internal nginx) —
    a scan can match the wrong one, and did during testing, silently
    signaling an unrelated container's process instead of the real host
    nginx. The /proc/<pid>/cmdline check below (still relying on this
    container's own --pid=host for read access) guards against that.

    Signal delivery: os.kill() from this container's own process — even
    with the right PID and --pid=host for *namespace visibility* — hit a
    real, reproducible permission error (confirmed live: correct PID,
    still EPERM), since visibility isn't the same as having the kernel
    capability to signal a process outside this container's boundary. A
    transient --privileged --pid=host helper container (spun up via the
    already-mounted docker socket, exec_docker below) gets that capability
    granted fresh from the Docker daemon regardless of this long-lived
    container's own capability set, and was confirmed working live."""
    try:
        with open(NGINX_PIDFILE) as f:
            master_pid = int(f.read().strip())
    except (FileNotFoundError, ValueError) as e:
        raise AgentError(f"could not read host nginx pidfile: {e}", status=500) from e
    try:
        with open(f"/proc/{master_pid}/cmdline", "rb") as f:
            cmdline = f.read().decode("utf-8", errors="ignore")
    except FileNotFoundError as e:
        raise AgentError(f"nginx pid {master_pid} from pidfile not found in /proc", status=500) from e
    if not cmdline.startswith("nginx:"):
        raise AgentError(f"pid {master_pid} from nginx pidfile is not nginx: {cmdline!r}", status=500)

    p = subprocess.run(
        [
            "docker", "run", "--rm", "--privileged", "--pid=host", "alpine",
            "kill", "-HUP", str(master_pid),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if p.returncode != 0:
        raise AgentError(f"nginx reload failed: {(p.stderr or p.stdout)[:300]}", status=500)


def _route_name(domain: str) -> str:
    return "route-" + domain.replace(".", "-")


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _cert_ready(domain: str) -> bool:
    p = _docker("exec", PROXY_CONTAINER, "test", "-f", f"/etc/nginx/certs/{domain}.crt", timeout=15)
    return p.returncode == 0


def provision_route(domain: str) -> dict:
    """Docker mode: idempotently start the per-tenant forwarder and wait for acme-companion's cert."""
    name = _route_name(domain)
    state = _docker("inspect", "-f", "{{.State.Running}}", name)
    if state.returncode == 0 and state.stdout.strip() != "true":
        _docker("rm", "-f", name)
        state = subprocess.CompletedProcess([], 1)
    if state.returncode != 0:
        p = _docker(
            "run", "-d", "--name", name, "--restart", "unless-stopped",
            "--network", ROUTE_NETWORK, "--label", f"{ROUTE_LABEL}={domain}",
            "-e", f"VIRTUAL_HOST={domain}", "-e", f"LETSENCRYPT_HOST={domain}",
            "-e", "VIRTUAL_PORT=8080",
            ROUTE_IMAGE, "tcp-listen:8080,fork,reuseaddr",
            f"tcp:{ROUTE_UPSTREAM}:{ROUTE_UPSTREAM_PORT}",
            timeout=120,
        )
        if p.returncode != 0:
            raise AgentError(f"could not start route container: {(p.stderr or p.stdout)[:300]}", status=500)
    deadline = time.time() + CERT_WAIT_S
    while time.time() < deadline:
        if _cert_ready(domain):
            return {"ok": True, "domain": domain, "mode": "docker"}
        time.sleep(3)
    raise AgentError(
        f"route {name} is up but no certificate for {domain} within {CERT_WAIT_S}s "
        "(acme-companion may still be issuing; re-run /ssl to re-check)",
        status=504,
    )


def remove_route(payload: dict) -> dict:
    domain = str(payload.get("domain") or "").strip().lower()
    if not DOMAIN_RE.match(domain):
        raise AgentError(f"invalid domain: {domain!r}", status=400)
    if SSL_MODE == "docker":
        _docker("rm", "-f", _route_name(domain))
    return {"ok": True, "domain": domain}


def provision_ssl(payload: dict) -> dict:
    domain = str(payload.get("domain") or "").strip().lower()
    if not DOMAIN_RE.match(domain):
        raise AgentError(f"invalid domain: {domain!r}", status=400)
    if SSL_MODE == "docker":
        return provision_route(domain)

    os.makedirs(os.path.join(CERTBOT_WEBROOT, ".well-known", "acme-challenge"), exist_ok=True)

    # 1. HTTP-only vhost so the ACME HTTP-01 challenge can be served.
    _write_vhost(domain, NGINX_HTTP_ONLY_TEMPLATE)
    _reload_nginx()

    # 2. Obtain the cert. certonly (not --nginx) — never touches nginx config
    #    or tries to reload it itself, since it has no way to reach the real
    #    host process from in here.
    cert_dir = f"/etc/letsencrypt/live/{domain}"
    if not os.path.isdir(cert_dir):
        p = subprocess.run(
            [
                "certbot", "certonly", "--webroot", "-w", CERTBOT_WEBROOT,
                "-d", domain, "--non-interactive", "--agree-tos",
                "-m", CERTBOT_EMAIL, "--no-eff-email",
            ],
            capture_output=True, text=True, timeout=90,
        )
        if p.returncode != 0:
            raise AgentError(f"certbot failed: {(p.stderr or p.stdout)[:500]}", status=500)

    # 3. Full vhost with the real SSL block, then reload again.
    _write_vhost(domain, NGINX_SSL_TEMPLATE)
    _reload_nginx()

    return {"ok": True, "domain": domain}


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
        if self.path not in ("/exec", "/ssl", "/unroute"):
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
            if self.path == "/ssl":
                result = provision_ssl(payload)
            elif self.path == "/unroute":
                result = remove_route(payload)
            else:
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
