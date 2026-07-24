"""Infrastructure ops — HA heartbeat, alerts, capacity, docker/workers (best-effort)."""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, now_datetime, today

from space_cloud.services import bench_client
from space.services import notifications


def heartbeat_all():
	"""Refresh server/cluster/node heartbeats from live metrics when possible."""
	now = now_datetime()
	for name in frappe.get_all("Space Server", filters={"status": ("in", ["Active", "Maintenance"])}, pluck="name"):
		try:
			stats = bench_client.get_backend_stats(name)
			updates = {"last_heartbeat": now, "health": "Healthy" if stats.get("redis_ok") else "Degraded"}
			if frappe.db.has_column("Space Server", "cpu_used_percent") and stats.get("cpu_percent") is not None:
				updates["cpu_used_percent"] = stats.get("cpu_percent")
			if stats.get("ram_used_mb") is not None:
				updates["ram_used_mb"] = stats.get("ram_used_mb")
			if stats.get("disk_used_mb") is not None:
				updates["disk_used_mb"] = stats.get("disk_used_mb")
			if frappe.db.has_column("Space Server", "load_avg") and stats.get("load_avg") is not None:
				updates["load_avg"] = stats.get("load_avg")
			frappe.db.set_value("Space Server", name, updates, update_modified=False)
			# metric snapshot extension
			frappe.get_doc(
				{
					"doctype": "Space Metric Snapshot",
					"server": name,
					"captured_at": now,
					"cpu_percent": stats.get("cpu_percent") or 0,
					"ram_used_mb": stats.get("ram_used_mb") or 0,
					"disk_used_mb": stats.get("disk_used_mb") or 0,
					"redis_ok": 1 if stats.get("redis_ok") else 0,
					"workers": stats.get("workers") or 0,
					"queue_length": stats.get("queue_length") or 0,
					"raw_json": json.dumps(stats, default=str)[:50000],
				}
			).insert(ignore_permissions=True)
		except Exception:
			frappe.db.set_value(
				"Space Server",
				name,
				{"last_heartbeat": now, "health": "Unknown"},
				update_modified=False,
			)
			frappe.log_error(title=f"Space heartbeat failed: {name}")

	if frappe.db.exists("DocType", "Space Cluster"):
		for cname in frappe.get_all("Space Cluster", pluck="name"):
			servers = frappe.get_all("Space Server", filters={"cluster": cname}, fields=["health", "active_sites"])
			sites = sum(int(s.active_sites or 0) for s in servers)
			healths = {s.health for s in servers}
			if "Critical" in healths:
				health = "Critical"
			elif "Degraded" in healths:
				health = "Degraded"
			elif servers:
				health = "Healthy"
			else:
				health = "Unknown"
			frappe.db.set_value(
				"Space Cluster",
				cname,
				{"active_sites": sites, "health": health, "last_heartbeat": now, "load_score": float(sites)},
				update_modified=False,
			)

	if frappe.db.exists("DocType", "Space Node"):
		for nname in frappe.get_all("Space Node", filters={"server": ("is", "set")}, fields=["name", "server"]):
			if not nname.server:
				continue
			row = frappe.db.get_value(
				"Space Server",
				nname.server,
				["health", "cpu_used_percent", "ram_used_mb", "disk_used_mb", "active_sites", "load_avg", "io_wait_percent"],
				as_dict=True,
			)
			if not row:
				continue
			frappe.db.set_value(
				"Space Node",
				nname.name,
				{
					"health": row.health,
					"cpu_used_percent": row.cpu_used_percent,
					"ram_used_mb": row.ram_used_mb,
					"disk_used_mb": row.disk_used_mb,
					"active_sites": row.active_sites,
					"load_avg": row.get("load_avg"),
					"io_wait_percent": row.get("io_wait_percent"),
					"last_heartbeat": now,
				},
				update_modified=False,
			)
	frappe.db.commit()


def evaluate_alerts():
	"""Evaluate Space Alert Rules against current server metrics."""
	if not frappe.db.exists("DocType", "Space Alert Rule"):
		return
	now = now_datetime()
	for name in frappe.get_all("Space Alert Rule", filters={"is_active": 1}, pluck="name"):
		rule = frappe.get_doc("Space Alert Rule", name)
		targets = []
		if rule.target_server:
			targets = [rule.target_server]
		elif rule.scope == "Cluster" and rule.target_cluster:
			targets = frappe.get_all("Space Server", filters={"cluster": rule.target_cluster}, pluck="name")
		else:
			targets = frappe.get_all("Space Server", filters={"status": "Active"}, pluck="name")

		for server in targets:
			value = _metric_value(server, rule.metric)
			if value is None:
				continue
			if not _compare(value, rule.operator or ">", float(rule.threshold or 0)):
				continue
			# cooldown
			cooldown = int(rule.cooldown_minutes or 30)
			recent = frappe.get_all(
				"Space Alert",
				filters={
					"rule": rule.name,
					"server": server,
					"status": ("in", ["Open", "Acknowledged"]),
					"modified": (">", add_days(today(), -1)),
				},
				limit_page_length=1,
			)
			if recent:
				continue
			alert = frappe.get_doc(
				{
					"doctype": "Space Alert",
					"title": f"{rule.metric} {rule.operator} {rule.threshold} on {server}",
					"rule": rule.name,
					"severity": rule.severity or "Warning",
					"status": "Open",
					"metric": rule.metric,
					"value": value,
					"threshold": rule.threshold,
					"server": server,
					"cluster": rule.target_cluster,
					"message": f"{rule.metric}={value} crossed {rule.operator}{rule.threshold}",
					"opened_at": now,
				}
			).insert(ignore_permissions=True)
			notifications.notify(
				title=alert.title,
				event_type="generic",
				message=alert.message,
				ref_doctype="Space Alert",
				ref_name=alert.name,
			)
	frappe.db.commit()


def _metric_value(server: str, metric: str) -> float | None:
	row = frappe.db.get_value(
		"Space Server",
		server,
		["cpu_used_percent", "disk_used_mb", "disk_mb", "ram_used_mb", "ram_mb", "health"],
		as_dict=True,
	)
	if not row:
		return None
	m = (metric or "").strip()
	if m == "CPU":
		return float(row.cpu_used_percent or 0)
	if m == "Disk":
		return 100.0 * float(row.disk_used_mb or 0) / max(float(row.disk_mb or 1), 1)
	if m == "Health":
		return {"Healthy": 0, "Unknown": 1, "Degraded": 2, "Critical": 3}.get(row.health or "Unknown", 1)
	if m == "Redis":
		try:
			stats = bench_client.get_backend_stats(server)
			return 1.0 if stats.get("redis_ok") else 0.0
		except Exception:
			return 0.0
	if m == "Workers":
		try:
			stats = bench_client.get_backend_stats(server)
			return float(stats.get("workers") or 0)
		except Exception:
			return None
	if m == "DB":
		try:
			stats = bench_client.get_backend_stats(server)
			return float(stats.get("mariadb_size_mb") or 0)
		except Exception:
			return None
	if m == "SSL":
		exp = frappe.db.get_value("Space Server", server, "ssl_expires_on")
		if not exp:
			return None
		from frappe.utils import date_diff, getdate

		return float(date_diff(getdate(exp), today()))
	if m == "Backup":
		failed = frappe.db.count("Space Backup", {"status": "Failed", "modified": (">", add_days(today(), -1))})
		return float(failed)
	if m == "Deployment":
		failed = frappe.db.count("Space Deployment Job", {"status": "Failed", "modified": (">", add_days(today(), -1))})
		return float(failed)
	if m == "Queue":
		try:
			stats = bench_client.get_backend_stats(server)
			return float(stats.get("queue_length") or 0)
		except Exception:
			return None
	return None


def _compare(value: float, op: str, threshold: float) -> bool:
	if op == ">":
		return value > threshold
	if op == ">=":
		return value >= threshold
	if op == "<":
		return value < threshold
	if op == "<=":
		return value <= threshold
	if op == "==":
		return value == threshold
	return False


def forecast_capacity(horizon_days: int = 30):
	"""Simple linear forecast from active_sites growth."""
	if not frappe.db.exists("DocType", "Space Capacity Forecast"):
		return []
	out = []
	day = today()
	for server in frappe.get_all("Space Server", fields=["name", "active_sites", "max_sites", "ram_mb", "ram_used_mb", "disk_mb", "disk_used_mb", "cpu_used_percent", "cluster"]):
		growth = max(1, int((server.active_sites or 0) * 0.05 * (horizon_days / 30)))
		predicted_sites = int(server.active_sites or 0) + growth
		ram_ratio = (server.ram_used_mb or 0) / max(server.active_sites or 1, 1)
		disk_ratio = (server.disk_used_mb or 0) / max(server.active_sites or 1, 1)
		pred_ram = int(ram_ratio * predicted_sites)
		pred_disk = int(disk_ratio * predicted_sites)
		rec = "OK"
		if predicted_sites >= (server.max_sites or 50) * 0.85:
			rec = "Scale out: approaching max sites"
		elif pred_ram >= (server.ram_mb or 1) * 0.85:
			rec = "Add RAM or migrate sites"
		elif pred_disk >= (server.disk_mb or 1) * 0.85:
			rec = "Expand disk or purge backups"
		doc = frappe.get_doc(
			{
				"doctype": "Space Capacity Forecast",
				"forecast_date": day,
				"server": server.name,
				"cluster": server.cluster if hasattr(server, "cluster") else None,
				"predicted_sites": predicted_sites,
				"predicted_ram_mb": pred_ram,
				"predicted_disk_mb": pred_disk,
				"predicted_cpu_percent": float(server.cpu_used_percent or 0) * (1 + growth / max(server.active_sites or 1, 1)),
				"recommendation": rec,
				"horizon_days": horizon_days,
			}
		).insert(ignore_permissions=True)
		out.append(doc.name)
	frappe.db.commit()
	return out


def safe_failover_stub(primary_server: str) -> dict:
	"""Mark primary degraded and promote replica metadata only — no destructive cutover."""
	if not frappe.db.exists("Space Server", primary_server):
		frappe.throw("Server not found")
	replicas = frappe.get_all(
		"Space Server",
		filters={"replica_of": primary_server, "status": "Active"},
		fields=["name", "health"],
		order_by="weight desc",
	)
	if not replicas:
		return {"ok": False, "reason": "No replica configured"}
	target = replicas[0].name
	frappe.db.set_value("Space Server", primary_server, {"health": "Degraded", "ha_role": "Primary"})
	frappe.db.set_value("Space Server", target, {"health": "Healthy", "ha_role": "Replica"})
	notifications.notify(
		title=f"Failover stub: prefer {target}",
		event_type="generic",
		message=f"Primary {primary_server} marked degraded; replica {target} noted (manual cutover required).",
		ref_doctype="Space Server",
		ref_name=target,
	)
	frappe.db.commit()
	return {"ok": True, "primary": primary_server, "preferred_replica": target, "cutover": "manual"}


def auto_heal():
	"""Best-effort: restart soft-fail on Critical servers with Active sites."""
	for name in frappe.get_all("Space Server", filters={"health": "Critical", "status": "Active"}, pluck="name"):
		try:
			bench_client.restart_bench(name)
			notifications.notify(
				title=f"Auto-heal attempted: {name}",
				event_type="generic",
				message="bench restart (best-effort)",
				ref_doctype="Space Server",
				ref_name=name,
			)
		except Exception:
			frappe.log_error(title=f"Auto-heal failed: {name}")
	frappe.db.commit()


def query_observability_logs(q: str | None = None, server: str | None = None, limit: int = 50) -> list[dict]:
	if not frappe.db.exists("DocType", "Space Observability Log"):
		return []
	filters = {}
	if server:
		filters["server"] = server
	rows = frappe.get_all(
		"Space Observability Log",
		filters=filters,
		fields=["name", "source", "level", "server", "site", "message", "trace_id", "captured_at"],
		order_by="captured_at desc",
		limit_page_length=min(int(limit or 50), 200),
	)
	if q:
		ql = q.lower()
		rows = [r for r in rows if ql in (r.message or "").lower() or ql in (r.trace_id or "")]
	return rows


def ingest_log(source: str, message: str, level: str = "INFO", server: str | None = None, site: str | None = None, trace_id: str | None = None):
	if not frappe.db.exists("DocType", "Space Observability Log"):
		return None
	doc = frappe.get_doc(
		{
			"doctype": "Space Observability Log",
			"source": source,
			"level": level,
			"server": server,
			"site": site,
			"message": (message or "")[:1000],
			"trace_id": trace_id,
			"captured_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def rotate_secret(name: str, new_value: str) -> dict:
	doc = frappe.get_doc("Space Secret", name)
	doc.secret_value = new_value
	doc.rotated_at = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "name": name, "rotated_at": str(doc.rotated_at)}


def list_docker_overview(server: str | None = None) -> dict:
	"""Additive docker introspection via bench_client helpers when available."""
	out = {"containers": [], "images": [], "volumes": [], "networks": []}
	try:
		if hasattr(bench_client, "docker_ps"):
			out["containers"] = bench_client.docker_ps(server)
		if hasattr(bench_client, "docker_images"):
			out["images"] = bench_client.docker_images(server)
		if hasattr(bench_client, "docker_volumes"):
			out["volumes"] = bench_client.docker_volumes(server)
		if hasattr(bench_client, "docker_networks"):
			out["networks"] = bench_client.docker_networks(server)
	except Exception as e:
		out["error"] = str(e)[:500]
	return out
