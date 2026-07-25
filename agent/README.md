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

Single real endpoint, deliberately narrow:

- `GET /ping` — health check, no auth.
- `POST /exec` — `{"argv": ["bench", "--site", "foo", "migrate"], "container"?: str, "cwd"?: str, "timeout_s"?: number}`
  → `{"ok": bool, "code": int, "stdout": str, "stderr": str}`.
  Requires `Authorization: Bearer <SPACE_AGENT_TOKEN>`. `argv[0]` must be
  one of `bench`, `docker`, `bash`, `du`, `ls` — bench_client.py already
  builds every argv itself (site/package names are regex-validated before
  they ever reach this service), so this is defense in depth, not the
  primary safety boundary.

## Deploy (current single-server setup)

Runs as its own container on the **same Docker network as the bench
backend container** (`frappe_docker_frappe_network`), with the host's
Docker socket mounted so it can `docker exec` into the bench container.
It does **not** publish a port to the host or the internet — it's only
reachable from sibling containers on that network (e.g.
`frappe_docker-backend-1`, where `space`/`space_cloud` actually run).

```bash
docker build -t space-agent:latest .

docker run -d --name space-agent \
  --network frappe_docker_frappe_network \
  --restart unless-stopped \
  --memory=128m --memory-swap=128m --cpus=0.25 \
  -v /var/run/docker.sock:/var/run/docker.sock \
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
