# Space Agent

A minimal, dependency-free HTTP service that runs **on** each Space Server
and executes bench/docker commands on the control plane's behalf —
replacing per-command SSH. Modeled on how Frappe Cloud's own Agent works:
the control plane (`space_cloud`) never SSHes into a server; it calls this
Agent's REST API instead, and the Agent — already running on that server —
runs the command locally.

## Why this exists

Before this, `space_cloud/services/bench_client.py` SSHed into the target
server for every single bench/docker operation (see git history — its
docstring called this "Phase 1"). That's replaced by:

```
space_cloud (Frappe worker) → HTTP → Space Agent (this) → docker exec → bench container
```

## API

Two real endpoints, both deliberately narrow:

- `GET /ping` — health check, no auth.
- `POST /exec` — `{"argv": ["bench", "--site", "foo", "migrate"], "container"?: str, "cwd"?: str, "timeout_s"?: number}`
  → `{"ok": bool, "code": int, "stdout": str, "stderr": str}`.
  Requires `Authorization: Bearer <SPACE_AGENT_TOKEN>`. `argv[0]` must be
  one of `bench`, `docker`, `bash`, `du`, `ls` — bench_client.py already
  builds every argv itself (site/package names are regex-validated before
  they ever reach this service), so this is defense in depth, not the
  primary safety boundary. Non-`docker` commands run via `docker exec` into
  the bench container, which has **no host filesystem access** — it can't
  touch `/etc/nginx` or reach the real host nginx process, which is why SSL
  provisioning is a separate endpoint instead of an `/exec` one-liner.
- `POST /ssl` — `{"domain": "foo.zatgo.online"}` → `{"ok": true, "domain": str}`.
  Same auth. Validates the domain against `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.zatgo\.online$`,
  writes a fixed nginx vhost template (HTTP-only, for the ACME challenge),
  reloads nginx, runs `certbot certonly --webroot`, writes the final vhost
  with the real SSL block, reloads nginx again. Idempotent — skips issuance
  if `/etc/letsencrypt/live/<domain>` already exists. Needs real host
  access (see Deploy below), unlike `/exec`.

## Deploy (current single-server setup)

Runs as its own container on the **same Docker network as the bench
backend container** (the actual network name varies by droplet — check
`docker network ls` / `docker inspect frappe_docker-backend-1`, don't
assume it matches this doc), with the host's Docker socket mounted so it
can `docker exec` into the bench container. It does **not** publish a
port to the host or the internet — it's only reachable from sibling
containers on that network (e.g. `frappe_docker-backend-1`, where
`space`/`space_cloud` actually run).

`/ssl` additionally needs real host access `/exec` doesn't: bind mounts
for `/etc/nginx`, `/etc/letsencrypt`, a shared `/var/www/certbot` ACME
webroot, and the host's nginx pidfile, plus `--pid=host` so it can send
`SIGHUP` directly to the host's real nginx master process (nginx's reload
signal only reaches a process in the same PID namespace as the sender).
This is a real privilege increase, but a marginal one given the container
already holds the Docker socket (itself sufficient for a docker-breakout
to host root).

The pidfile must be read directly (`/host-run/nginx.pid` below) rather
than found by scanning `/proc` for a process matching `nginx: master
process`: with `--pid=host` the shared namespace also exposes *other
containers'* processes — `frappe_docker-frontend-1` runs its own internal
nginx — so a scan can silently match the wrong one instead of the real
host nginx. Confirmed live during development: the scan-based version
picked the frontend container's nginx, which then correctly rejected the
signal as a permission error, since it belongs to a different container.

```bash
docker build -t space-agent:latest .

docker run -d --name space-agent \
  --network frappe_docker_default \
  --pid=host \
  --restart unless-stopped \
  --memory=192m --memory-swap=192m --cpus=0.25 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /etc/nginx:/etc/nginx \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  -v /run/nginx.pid:/host-run/nginx.pid:ro \
  -e SPACE_AGENT_TOKEN="$(openssl rand -hex 32)" \
  -e SPACE_AGENT_CONTAINER=frappe_docker-backend-1 \
  space-agent:latest
```

The `--memory`/`--cpus` limits matter: this droplet is a single-vCPU,
2 GB box already running two Frappe sites, two Next.js services, and the
whole docker-compose bench — nothing here runs with unbounded resources
(see `space-web.service` / `space-admin-web.service`'s own
`MemoryMax`/`CPUQuota`), so the Agent shouldn't either.

The same token must be stored on the `Space Server` doctype's
`agent_token` field so `space_cloud` can authenticate — see
`space_cloud/services/agent_client.py`.

## Multi-server future

Nothing here assumes single-server. Each `Space Server` row carries its
own `agent_endpoint` + `agent_token`; a server elsewhere just needs this
same container running with Docker exposed to it (or run outside Docker
entirely — `server.py` has zero Docker-specific code beyond invoking the
`docker` CLI, so it would work unmodified on a bare-metal bench host too).
