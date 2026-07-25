"""Hosting Pool accounting — wires the existing (previously inert) Space Storage
Pool doctype into a real allocation ledger: capacity is admin-configurable and
independent of the server's total physical disk; allocated/used/available are
rolled up hourly from already-cached Space Server/Space Site/Space Plan fields
(no remote calls here, same safety property as space_cloud.services.quota)."""

from __future__ import annotations

import frappe

DEFAULT_RESERVATIONS = [
	{"reservation_type": "OS", "size_mb": 5120, "notes": "Base OS footprint"},
	{"reservation_type": "Docker", "size_mb": 3072, "notes": "Docker engine + images layer"},
	{"reservation_type": "Logs", "size_mb": 2048, "notes": "Application + bench logs"},
]

ALLOCATION_STATUSES = ("Active", "Provisioning", "Suspended")


def ensure_pool_for_server(server_name: str) -> str | None:
	"""Idempotently create/link a Space Storage Pool for a server. Never touches
	an already-linked pool's capacity_gb — that stays admin-owned."""
	if not frappe.db.exists("DocType", "Space Storage Pool"):
		return None
	server = frappe.get_doc("Space Server", server_name)
	if server.storage_pool and frappe.db.exists("Space Storage Pool", server.storage_pool):
		return server.storage_pool

	if not server.reservations:
		for r in DEFAULT_RESERVATIONS:
			server.append("reservations", dict(r))
		server.save(ignore_permissions=True)
		server.reload()

	pool_name = f"{server_name}-pool"
	reserved_mb = server.reserved_mb or sum(int(r.size_mb or 0) for r in (server.reservations or []))
	default_capacity_gb = max(0.0, ((server.disk_mb or 0) - reserved_mb) / 1024.0)

	if not frappe.db.exists("Space Storage Pool", pool_name):
		frappe.get_doc(
			{
				"doctype": "Space Storage Pool",
				"pool_name": pool_name,
				"title": f"{server.title or server_name} Hosting Pool",
				"server": server_name,
				"region": server.get("region"),
				"cluster": server.get("cluster"),
				"backend": "Local",
				"capacity_gb": round(default_capacity_gb, 2),
				"status": "Active",
			}
		).insert(ignore_permissions=True)

	if server.storage_pool != pool_name:
		server.storage_pool = pool_name
		server.save(ignore_permissions=True)
	frappe.db.commit()
	return pool_name


def recompute_pool(pool_name: str) -> dict:
	pool = frappe.get_doc("Space Storage Pool", pool_name)
	servers = frappe.get_all("Space Server", filters={"storage_pool": pool_name}, pluck="name")
	if not servers and pool.server:
		servers = [pool.server]

	if not servers:
		frappe.db.set_value(
			"Space Storage Pool", pool_name, {"allocated_gb": 0, "used_gb": 0, "available_gb": pool.capacity_gb or 0}, update_modified=False
		)
		return {"pool": pool_name, "allocated_gb": 0, "used_gb": 0, "available_gb": pool.capacity_gb or 0}

	sites = frappe.get_all(
		"Space Site",
		filters={"server": ("in", servers), "status": ("in", ALLOCATION_STATUSES)},
		fields=["name", "plan", "storage_used_mb"],
	)
	plan_storage_mb = {
		p.name: p.storage_mb or 0
		for p in frappe.get_all("Space Plan", fields=["name", "storage_mb"])
	}

	allocated_mb = sum(plan_storage_mb.get(s.plan, 0) for s in sites)
	used_mb = sum(float(s.storage_used_mb or 0) for s in sites)
	allocated_gb = round(allocated_mb / 1024.0, 2)
	used_gb = round(used_mb / 1024.0, 2)
	available_gb = round((pool.capacity_gb or 0) - allocated_gb, 2)

	status = pool.status
	if status != "Offline":
		status = "Full" if available_gb <= 0 else "Active"

	frappe.db.set_value(
		"Space Storage Pool",
		pool_name,
		{"allocated_gb": allocated_gb, "used_gb": used_gb, "available_gb": available_gb, "status": status},
		update_modified=False,
	)
	return {"pool": pool_name, "allocated_gb": allocated_gb, "used_gb": used_gb, "available_gb": available_gb, "status": status}


def recompute_all_pools():
	if not frappe.db.exists("DocType", "Space Storage Pool"):
		return
	for name in frappe.get_all("Space Storage Pool", pluck="name"):
		try:
			recompute_pool(name)
		except Exception:
			frappe.log_error(title=f"Space hosting pool recompute failed: {name}")
	frappe.db.commit()


def pool_status(server: str | None = None, cluster: str | None = None) -> list[dict]:
	if not frappe.db.exists("DocType", "Space Storage Pool"):
		return []
	filters = {}
	if server:
		filters["server"] = server
	if cluster:
		filters["cluster"] = cluster
	pools = frappe.get_all(
		"Space Storage Pool",
		filters=filters,
		fields=[
			"name",
			"pool_name",
			"title",
			"server",
			"region",
			"cluster",
			"backend",
			"capacity_gb",
			"allocated_gb",
			"used_gb",
			"available_gb",
			"status",
		],
	)
	out = []
	for p in pools:
		reserved_mb = 0
		disk_mb = 0
		if p.server:
			row = frappe.db.get_value("Space Server", p.server, ["disk_mb", "reserved_mb"], as_dict=True)
			if row:
				disk_mb = row.disk_mb or 0
				reserved_mb = row.reserved_mb or 0
		out.append(
			{
				**p,
				"disk_gb": round(disk_mb / 1024.0, 2),
				"reserved_gb": round(reserved_mb / 1024.0, 2),
			}
		)
	return out
