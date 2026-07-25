"""
Bench command client for the shared Frappe bench.

Runs locally (in-process `subprocess`) when this worker already lives
inside the bench container; otherwise calls the target Space Server's
Space Agent over HTTP (see `agent/` and `services/agent_client.py`) —
no SSH. Every function below keeps its original signature; only the
transport underneath changed.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Any

import frappe

from space_cloud.services import agent_client

PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
SITE_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,250}[a-z0-9])?$")


class BenchError(Exception):
	def __init__(self, message: str, stdout: str = "", stderr: str = "", code: int = 1):
		super().__init__(message)
		self.stdout = stdout
		self.stderr = stderr
		self.code = code


def _assert_site(site: str) -> str:
	s = (site or "").strip().lower()
	if not SITE_RE.match(s):
		raise BenchError(f"Invalid site name: {site}")
	return s


def _assert_pkg(pkg: str) -> str:
	p = (pkg or "").strip()
	if not PACKAGE_RE.match(p):
		raise BenchError(f"Invalid package: {pkg}")
	return p


def get_server(server_name: str | None = None) -> Any:
	if server_name:
		return frappe.get_doc("Space Server", server_name)
	name = frappe.db.get_value("Space Server", {"is_default": 1, "status": "Active"}, "name")
	if not name:
		name = frappe.db.get_value("Space Server", {"status": "Active"}, "name")
	if not name:
		frappe.throw("No active Space Server configured")
	return frappe.get_doc("Space Server", name)


def _in_bench_container() -> bool:
	"""True when this process already runs inside the Frappe bench container."""
	if os.environ.get("SPACE_BENCH_INPROCESS") == "1":
		return True
	# frappe_docker backend has bench but typically no docker CLI
	if os.path.isdir("/home/frappe/frappe-bench/sites") and not os.path.exists("/usr/bin/docker"):
		try:
			r = subprocess.run(["which", "bench"], capture_output=True, text=True, timeout=3)
			return r.returncode == 0
		except Exception:
			return False
	return False


def run_on_bench(
	server_name: str | None,
	argv: list[str],
	*,
	timeout_s: int = 3600,
) -> dict[str, Any]:
	server = get_server(server_name)
	for a in argv:
		if not isinstance(a, str) or "\0" in a:
			raise BenchError("Invalid argv token")

	# Control plane site lives on the same bench → run bench/du/ls commands
	# in-process. Docker commands still need the Agent: the bench container
	# itself normally has no docker CLI/socket access.
	if argv[0] != "docker" and _in_bench_container():
		return _run(list(argv), timeout_s, cwd="/home/frappe/frappe-bench")

	try:
		return agent_client.call(server, list(argv), cwd="/home/frappe/frappe-bench", timeout_s=timeout_s)
	except agent_client.AgentError as e:
		raise BenchError(str(e), stdout=e.stdout, stderr=e.stderr, code=e.code) from e


def _run(cmd: list[str], timeout_s: int, cwd: str | None = None) -> dict[str, Any]:
	try:
		p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd)
	except subprocess.TimeoutExpired as e:
		raise BenchError("Command timed out", stdout=e.stdout or "", stderr=e.stderr or "", code=124) from e
	ok = p.returncode == 0
	result = {
		"ok": ok,
		"code": p.returncode,
		"stdout": p.stdout or "",
		"stderr": p.stderr or "",
		"command": " ".join(shlex.quote(c) for c in cmd),
	}
	if not ok:
		raise BenchError(
			(p.stderr or p.stdout or "Command failed")[:500],
			stdout=p.stdout or "",
			stderr=p.stderr or "",
			code=p.returncode,
		)
	return result


def test_server_connection(server_name: str) -> dict[str, Any]:
	r = run_on_bench(server_name, ["bench", "--version"], timeout_s=30)
	return {"ok": True, "version": (r["stdout"] or "").strip()[:200]}


def restart_backend(server_name: str) -> dict[str, Any]:
	server = get_server(server_name)
	container = server.backend_container
	return run_on_bench(server_name, ["docker", "restart", container], timeout_s=120)


def list_sites(server_name: str | None = None) -> list[str]:
	r = run_on_bench(server_name, ["ls", "-1", "sites"], timeout_s=30)
	noise = {
		"apps",
		"assets",
		"common_site_config.json",
		"apps.txt",
		"apps.json",
		"currentsite.txt",
	}
	out = []
	for line in (r["stdout"] or "").splitlines():
		name = line.strip()
		if name and name not in noise and not name.endswith((".json", ".txt")) and SITE_RE.match(name):
			out.append(name)
	return out


def list_bench_apps(server_name: str | None = None) -> list[str]:
	r = run_on_bench(server_name, ["ls", "-1", "apps"], timeout_s=30)
	return [l.strip() for l in (r["stdout"] or "").splitlines() if l.strip() and PACKAGE_RE.match(l.strip())]


def _resolve_db_root_password(explicit: str | None = None) -> str:
	if explicit:
		return explicit
	for key in ("MYSQL_ROOT_PASSWORD", "MARIADB_ROOT_PASSWORD", "DO_DB_ROOT_PASSWORD"):
		val = (os.environ.get(key) or "").strip()
		if val:
			return val
	try:
		# Prefer Space Settings encrypted password when workers lack compose env
		settings = frappe.get_single("Space Settings")
		try:
			pwd = settings.get_password("db_root_password")
			if pwd:
				return pwd
		except Exception:
			pass
	except Exception:
		pass
	try:
		# common_site_config / site_config via connected site
		pwd = (frappe.conf.get("db_root_password") or "").strip()
		if pwd:
			return pwd
	except Exception:
		pass
	raise BenchError(
		"DB root password not configured. Set MYSQL_ROOT_PASSWORD on workers "
		"or Space Settings.db_root_password / common_site_config db_root_password."
	)


def new_site(
	server_name: str | None,
	site: str,
	admin_password: str,
	*,
	install_erpnext: bool = True,
	db_root_password: str | None = None,
) -> dict[str, Any]:
	site = _assert_site(site)
	if not admin_password or len(admin_password) < 8:
		raise BenchError("Admin password must be at least 8 characters")
	db_root = _resolve_db_root_password(db_root_password)
	args = [
		"bench",
		"new-site",
		site,
		"--mariadb-user-host-login-scope=%",
		"--db-root-password",
		db_root,
		"--admin-password",
		admin_password,
	]
	if install_erpnext:
		args += ["--install-app", "erpnext"]
	return run_on_bench(server_name, args, timeout_s=60 * 60)


def install_app(server_name: str | None, site: str, pkg: str) -> dict[str, Any]:
	return run_on_bench(
		server_name,
		["bench", "--site", _assert_site(site), "install-app", _assert_pkg(pkg)],
		timeout_s=30 * 60,
	)


def uninstall_app(server_name: str | None, site: str, pkg: str) -> dict[str, Any]:
	return run_on_bench(
		server_name,
		["bench", "--site", _assert_site(site), "uninstall-app", _assert_pkg(pkg), "--yes"],
		timeout_s=30 * 60,
	)


def clear_cache(server_name: str | None, site: str) -> dict[str, Any]:
	return run_on_bench(
		server_name,
		["bench", "--site", _assert_site(site), "clear-cache"],
		timeout_s=120,
	)


def migrate_site(server_name: str | None, site: str) -> dict[str, Any]:
	return run_on_bench(
		server_name,
		["bench", "--site", _assert_site(site), "migrate"],
		timeout_s=60 * 60,
	)


def set_maintenance(server_name: str | None, site: str, on: bool) -> dict[str, Any]:
	val = "on" if on else "off"
	return run_on_bench(
		server_name,
		["bench", "--site", _assert_site(site), "set-maintenance-mode", val],
		timeout_s=60,
	)


def drop_site(server_name: str | None, site: str, db_root_password: str | None = None) -> dict[str, Any]:
	site = _assert_site(site)
	db_root = _resolve_db_root_password(db_root_password)
	args = ["bench", "drop-site", site, "--force", "--no-backup", "--db-root-password", db_root]
	return run_on_bench(server_name, args, timeout_s=30 * 60)


def list_apps_on_site(server_name: str | None, site: str) -> list[str]:
	r = run_on_bench(server_name, ["bench", "--site", _assert_site(site), "list-apps"], timeout_s=60)
	apps = []
	for line in (r["stdout"] or "").splitlines():
		trimmed = line.strip()
		if not trimmed or trimmed.lower().startswith("app") or set(trimmed) <= {"-"}:
			continue
		pkg = trimmed.split()[0]
		if PACKAGE_RE.match(pkg):
			apps.append(pkg)
	return list(dict.fromkeys(apps))


def get_site_disk_mb(server_name: str | None, site: str) -> int:
	r = run_on_bench(server_name, ["du", "-sm", f"sites/{_assert_site(site)}"], timeout_s=30)
	first = (r["stdout"] or "").strip().split()[0] if r["stdout"] else "0"
	try:
		return max(0, int(first))
	except ValueError:
		return 0


def get_backend_mem(server_name: str | None = None) -> dict[str, Any]:
	server = get_server(server_name)
	container = server.backend_container
	r = run_on_bench(
		server_name,
		["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}", container],
		timeout_s=20,
	)
	raw = (r["stdout"] or "").strip()
	cpu_raw, _, mem_raw = raw.partition("|")
	parts = [p.strip() for p in mem_raw.split("/")]
	cpu_percent = None
	try:
		cpu_percent = float(cpu_raw.strip().rstrip("%"))
	except (TypeError, ValueError):
		pass
	return {
		"raw": mem_raw,
		"used": parts[0] if parts else "",
		"limit": parts[1] if len(parts) > 1 else "",
		"cpu_percent": cpu_percent,
	}


def backup_site(server_name: str | None, site: str, *, with_files: bool = True) -> dict[str, Any]:
	"""Run bench backup for a site. Returns stdout/stderr from bench."""
	site = _assert_site(site)
	args = ["bench", "--site", site, "backup"]
	if with_files:
		args.append("--with-files")
	return run_on_bench(server_name, args, timeout_s=60 * 60)


def restore_site(
	server_name: str | None,
	site: str,
	sql_file: str,
	*,
	force: bool = True,
) -> dict[str, Any]:
	"""Restore a site from a SQL dump path inside the bench container."""
	site = _assert_site(site)
	sql_file = (sql_file or "").strip()
	if not sql_file or ".." in sql_file or sql_file.startswith("/"):
		# allow absolute under sites/ only via relative path
		if not sql_file.startswith("sites/") and "/private/" not in sql_file:
			raise BenchError("Invalid restore path")
	args = ["bench", "--site", site, "restore", sql_file]
	if force:
		args.append("--force")
	return run_on_bench(server_name, args, timeout_s=60 * 60)


def get_backend_stats(server_name: str | None = None) -> dict[str, Any]:
	"""Collect CPU/RAM/disk/queue/worker hints for monitoring snapshots."""
	stats: dict[str, Any] = {"bench_status": "unknown", "scheduler_status": "unknown"}
	try:
		ver = test_server_connection(server_name)
		stats["bench_status"] = "ok"
		stats["bench_version"] = ver.get("version")
	except Exception as e:
		stats["bench_status"] = "error"
		stats["bench_error"] = str(e)[:200]

	mem = get_backend_mem(server_name)
	stats["memory"] = mem
	if mem.get("cpu_percent") is not None:
		stats["cpu_percent"] = mem["cpu_percent"]

	try:
		r = run_on_bench(server_name, ["du", "-sm", "sites"], timeout_s=60)
		first = (r["stdout"] or "").strip().split()[0] if r["stdout"] else "0"
		stats["disk_used_mb"] = int(first)
	except Exception:
		stats["disk_used_mb"] = 0

	try:
		# queue length via redis-cli if available (best-effort)
		r = run_on_bench(
			server_name,
			["bash", "-lc", "redis-cli -n 1 LLEN rq:queue:default 2>/dev/null || echo 0"],
			timeout_s=15,
		)
		stats["queue_length"] = int((r["stdout"] or "0").strip().splitlines()[-1] or 0)
	except Exception:
		stats["queue_length"] = 0

	try:
		r = run_on_bench(
			server_name,
			["bash", "-lc", "ps aux | grep -E 'frappe|worker|schedule' | grep -v grep | wc -l"],
			timeout_s=15,
		)
		stats["workers"] = int((r["stdout"] or "0").strip().splitlines()[-1] or 0)
		stats["scheduler_status"] = "ok" if stats["workers"] > 0 else "unknown"
	except Exception:
		stats["workers"] = 0

	try:
		# redis ping
		r = run_on_bench(server_name, ["bash", "-lc", "redis-cli ping 2>/dev/null || echo FAIL"], timeout_s=10)
		stats["redis_ok"] = "PONG" in (r["stdout"] or "")
	except Exception:
		stats["redis_ok"] = False

	return stats


def get_app(
	server_name: str | None,
	repo: str,
	*,
	branch: str | None = "main",
	app_name: str | None = None,
) -> dict[str, Any]:
	"""bench get-app from git repository."""
	repo = (repo or "").strip()
	if not repo or any(c in repo for c in (";", "|", "&", "`", "\n")):
		raise BenchError("Invalid repository URL")
	args = ["bench", "get-app"]
	if branch:
		args += ["--branch", branch.strip()]
	args.append(repo)
	if app_name:
		args.append(_assert_pkg(app_name))
	return run_on_bench(server_name, args, timeout_s=60 * 60)


def build_assets(server_name: str | None, app: str | None = None) -> dict[str, Any]:
	args = ["bench", "build"]
	if app:
		args += ["--app", _assert_pkg(app)]
	return run_on_bench(server_name, args, timeout_s=60 * 60)


def restart_bench(server_name: str | None) -> dict[str, Any]:
	"""Best-effort bench restart (may be no-op in docker workers)."""
	try:
		return run_on_bench(server_name, ["bench", "restart"], timeout_s=120)
	except BenchError as e:
		# docker compose often has no supervisor; treat soft-fail
		return {"stdout": "", "stderr": str(e), "code": 0, "soft_fail": True}


def verify_checksum(path: str, expected_sha256: str) -> bool:
	import hashlib

	expected = (expected_sha256 or "").strip().lower()
	if not expected:
		return True
	h = hashlib.sha256()
	with open(path, "rb") as fh:
		for chunk in iter(lambda: fh.read(1024 * 1024), b""):
			h.update(chunk)
	return h.hexdigest() == expected


def get_app_versions_json(server_name: str | None, site: str) -> dict[str, str]:
	"""Parse bench list-apps into package→version map when available."""
	r = run_on_bench(server_name, ["bench", "--site", _assert_site(site), "list-apps"], timeout_s=60)
	versions: dict[str, str] = {}
	for line in (r["stdout"] or "").splitlines():
		parts = line.strip().split()
		if len(parts) >= 1 and PACKAGE_RE.match(parts[0]):
			versions[parts[0]] = parts[1] if len(parts) > 1 else ""
	return versions


def git_head(server_name: str | None, app_package: str) -> str:
	pkg = _assert_pkg(app_package)
	r = run_on_bench(
		server_name,
		["bash", "-lc", f"cd apps/{pkg} && git rev-parse --short HEAD 2>/dev/null || true"],
		timeout_s=30,
	)
	return (r["stdout"] or "").strip().splitlines()[-1] if r.get("stdout") else ""



def docker_ps(server_name: str | None = None) -> list[dict[str, Any]]:
	"""List docker containers (best-effort)."""
	r = run_on_bench(
		server_name,
		["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"],
		timeout_s=30,
	)
	rows = []
	for line in (r.get("stdout") or "").splitlines():
		parts = line.split("\t")
		if len(parts) >= 4:
			rows.append({"id": parts[0], "name": parts[1], "status": parts[2], "image": parts[3]})
	return rows


def docker_images(server_name: str | None = None) -> list[dict[str, Any]]:
	r = run_on_bench(
		server_name,
		["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}"],
		timeout_s=30,
	)
	rows = []
	for line in (r.get("stdout") or "").splitlines():
		parts = line.split("\t")
		if len(parts) >= 3:
			rows.append({"image": parts[0], "id": parts[1], "size": parts[2]})
	return rows


def docker_volumes(server_name: str | None = None) -> list[str]:
	r = run_on_bench(server_name, ["docker", "volume", "ls", "-q"], timeout_s=30)
	return [ln.strip() for ln in (r.get("stdout") or "").splitlines() if ln.strip()]


def docker_networks(server_name: str | None = None) -> list[str]:
	r = run_on_bench(server_name, ["docker", "network", "ls", "--format", "{{.Name}}"], timeout_s=30)
	return [ln.strip() for ln in (r.get("stdout") or "").splitlines() if ln.strip()]


def docker_restart(server_name: str | None, container: str) -> dict[str, Any]:
	name = (container or "").strip()
	if not name or any(c in name for c in (";", "|", "&", "`", " ", "\n")):
		raise BenchError("Invalid container name")
	return run_on_bench(server_name, ["docker", "restart", name], timeout_s=120)


def docker_logs(server_name: str | None, container: str, tail: int = 100) -> str:
	name = (container or "").strip()
	if not name or any(c in name for c in (";", "|", "&", "`", " ", "\n")):
		raise BenchError("Invalid container name")
	n = max(1, min(int(tail or 100), 2000))
	r = run_on_bench(server_name, ["docker", "logs", "--tail", str(n), name], timeout_s=60)
	return (r.get("stdout") or "")[:50000]


def docker_cleanup(server_name: str | None = None) -> dict[str, Any]:
	"""Prune unused images/containers — safe best-effort."""
	return run_on_bench(server_name, ["docker", "system", "prune", "-f"], timeout_s=300)


def scale_workers_note(server_name: str | None = None) -> dict[str, Any]:
	"""Document-only worker scaling stub for compose-based benches."""
	stats = get_backend_stats(server_name)
	return {
		"workers": stats.get("workers"),
		"note": "Worker scale requires compose replica change; use Space Maintenance Window for controlled restart.",
		"soft": True,
	}
