"""Smart placement — extends Preferred / Round Robin / Least Loaded with region & affinity."""

from __future__ import annotations

import frappe


def select_server(preferred: str | None = None) -> str:
	"""Pick an Active, non-maintenance server for a new site (Phase 1/2 compatible)."""
	return select_server_advanced(preferred_server=preferred)


def select_server_advanced(
	*,
	preferred_server: str | None = None,
	preferred_region: str | None = None,
	preferred_cluster: str | None = None,
	plan: str | None = None,
	affinity_site: str | None = None,
	anti_affinity_site: str | None = None,
	manual_override: str | None = None,
) -> str:
	"""Placement by CPU/RAM/Disk/IO/load, plan, region, affinity, manual override."""
	if manual_override and _is_eligible(manual_override):
		return manual_override

	settings = frappe.get_single("Space Settings")
	mode = (settings.server_selection or "Preferred").strip()

	if preferred_server and _is_eligible(preferred_server):
		return preferred_server

	# affinity: same server as affinity site when eligible
	if affinity_site and frappe.db.exists("Space Site", affinity_site):
		aff_server = frappe.db.get_value("Space Site", affinity_site, "server")
		if aff_server and _is_eligible(aff_server):
			if not preferred_region or _server_region(aff_server) in (None, preferred_region):
				return aff_server

	prefer = settings.prefer_server or None
	if mode == "Preferred" and prefer and _is_eligible(prefer):
		if not preferred_region or _server_region(prefer) in (None, preferred_region):
			return prefer

	default = frappe.db.get_value("Space Server", {"is_default": 1, "status": "Active"}, "name")
	if default and _is_eligible(default) and mode == "Preferred":
		if not preferred_region or _server_region(default) in (None, preferred_region):
			return default

	fields = [
		"name",
		"active_sites",
		"max_sites",
		"ram_mb",
		"ram_used_mb",
		"disk_mb",
		"disk_used_mb",
		"weight",
		"health",
		"cpu_cores",
		"cpu_used_percent",
		"region",
		"cluster",
		"drain_mode",
		"io_wait_percent",
		"load_avg",
		"status",
		"storage_pool",
	]
	# only request columns that exist (pre-migrate safety)
	safe_fields = [f for f in fields if f in ("name", "active_sites", "max_sites", "ram_mb", "ram_used_mb", "disk_mb", "disk_used_mb", "weight", "health", "cpu_cores", "cpu_used_percent", "status") or frappe.db.has_column("Space Server", f)]

	candidates = frappe.get_all(
		"Space Server",
		filters={"status": "Active"},
		fields=safe_fields,
		order_by="is_default desc, weight desc, active_sites asc",
	)
	eligible = [c for c in candidates if _capacity_ok(c) and not (c.get("drain_mode") if isinstance(c, dict) else getattr(c, "drain_mode", 0))]

	if preferred_region:
		regional = [c for c in eligible if (c.get("region") if isinstance(c, dict) else getattr(c, "region", None)) == preferred_region]
		if regional:
			eligible = regional

	if preferred_cluster:
		clustered = [c for c in eligible if (c.get("cluster") if isinstance(c, dict) else getattr(c, "cluster", None)) == preferred_cluster]
		if clustered:
			eligible = clustered

	# anti-affinity: avoid server of anti_affinity_site
	if anti_affinity_site and frappe.db.exists("Space Site", anti_affinity_site):
		bad = frappe.db.get_value("Space Site", anti_affinity_site, "server")
		filtered = [c for c in eligible if (c.get("name") if isinstance(c, dict) else c.name) != bad]
		if filtered:
			eligible = filtered

	# plan-aware: need enough RAM/disk headroom vs plan limits
	plan_ram = plan_disk = 0
	if plan and frappe.db.exists("Space Plan", plan):
		plan_ram = int(frappe.db.get_value("Space Plan", plan, "ram_mb") or 0)
		plan_disk = int(frappe.db.get_value("Space Plan", plan, "storage_mb") or 0)

	pool_available_mb = {}
	if plan_disk and frappe.db.has_column("Space Server", "storage_pool"):
		pool_names = frappe.get_all(
			"Space Server", filters={"storage_pool": ("is", "set")}, pluck="storage_pool", distinct=True
		)
		if pool_names:
			for p in frappe.get_all(
				"Space Storage Pool",
				filters={"name": ("in", pool_names)},
				fields=["name", "available_gb", "status"],
			):
				pool_available_mb[p.name] = (p.available_gb or 0) * 1024 if p.status != "Offline" else 0

	def has_plan_headroom(c):
		ram_free = (c.get("ram_mb") or 0) - (c.get("ram_used_mb") or 0) if isinstance(c, dict) else (c.ram_mb or 0) - (c.ram_used_mb or 0)
		disk_free = (c.get("disk_mb") or 0) - (c.get("disk_used_mb") or 0) if isinstance(c, dict) else (c.disk_mb or 0) - (c.disk_used_mb or 0)
		if plan_ram and ram_free < plan_ram * 0.5:
			return False
		if plan_disk and disk_free < plan_disk * 0.5:
			return False
		pool = c.get("storage_pool") if isinstance(c, dict) else getattr(c, "storage_pool", None)
		if plan_disk and pool and pool in pool_available_mb:
			if pool_available_mb[pool] < plan_disk:
				return False
		return True

	with_plan = [c for c in eligible if has_plan_headroom(c)]
	if with_plan:
		eligible = with_plan

	if not eligible:
		frappe.throw("No eligible Space Server with capacity")

	if mode == "Round Robin":
		eligible.sort(key=lambda c: ((c.get("active_sites") if isinstance(c, dict) else c.active_sites) or 0, c.get("name") if isinstance(c, dict) else c.name))
		return eligible[0].name if hasattr(eligible[0], "name") else eligible[0]["name"]

	def load_score(c):
		get = (lambda k, d=0: (c.get(k) if isinstance(c, dict) else getattr(c, k, None)) or d)
		sites = get("active_sites")
		max_s = get("max_sites", 50)
		ram_pct = get("ram_used_mb") / max(get("ram_mb", 1), 1)
		disk_pct = get("disk_used_mb") / max(get("disk_mb", 1), 1)
		cpu_pct = (get("cpu_used_percent") or 0) / 100.0
		io_pct = (get("io_wait_percent") or 0) / 100.0
		load = (get("load_avg") or 0) / max(get("cpu_cores", 1), 1)
		health = get("health", "Unknown")
		health_pen = {"Healthy": 0, "Unknown": 0.1, "Degraded": 0.5, "Critical": 2.0}.get(health, 0.2)
		return (sites / max(max_s, 1)) + ram_pct + disk_pct + cpu_pct + io_pct + load + health_pen

	eligible.sort(key=load_score)
	top = eligible[0]
	return top.name if hasattr(top, "name") else top["name"]


def _server_region(name: str) -> str | None:
	if not frappe.db.has_column("Space Server", "region"):
		return None
	return frappe.db.get_value("Space Server", name, "region")


def _is_eligible(name: str) -> bool:
	fields = ["status", "active_sites", "max_sites", "health"]
	if frappe.db.has_column("Space Server", "drain_mode"):
		fields.append("drain_mode")
	row = frappe.db.get_value("Space Server", name, fields, as_dict=True)
	if not row or row.status != "Active":
		return False
	if row.get("drain_mode"):
		return False
	return _capacity_ok(row)


def _capacity_ok(row) -> bool:
	max_sites = row.get("max_sites") if isinstance(row, dict) else getattr(row, "max_sites", None)
	active = row.get("active_sites") if isinstance(row, dict) else getattr(row, "active_sites", None)
	max_sites = max_sites or 50
	active = active or 0
	return active < max_sites


def capacity_summary(server_name: str | None = None) -> list[dict]:
	filters = {}
	if server_name:
		filters["name"] = server_name
	base_fields = [
		"name",
		"title",
		"status",
		"health",
		"cpu_cores",
		"cpu_used_percent",
		"ram_mb",
		"ram_used_mb",
		"disk_mb",
		"disk_used_mb",
		"active_sites",
		"max_sites",
		"weight",
		"is_default",
	]
	extra = ["region", "cluster", "node", "drain_mode", "ha_role", "load_avg", "io_wait_percent", "last_heartbeat"]
	fields = base_fields + [f for f in extra if frappe.db.has_column("Space Server", f)]
	rows = frappe.get_all("Space Server", filters=filters, fields=fields)
	out = []
	for r in rows:
		out.append(
			{
				**r,
				"capacity_ok": _capacity_ok(r),
				"sites_remaining": max(0, (r.max_sites or 50) - (r.active_sites or 0)),
			}
		)
	return out


def list_regions() -> list[dict]:
	if not frappe.db.exists("DocType", "Space Region"):
		return []
	return frappe.get_all(
		"Space Region",
		filters={"status": "Active"},
		fields=["name", "region_code", "title", "country", "status"],
		order_by="title asc",
	)


def list_clusters(region: str | None = None) -> list[dict]:
	if not frappe.db.exists("DocType", "Space Cluster"):
		return []
	filters = {"status": ("in", ["Active", "Draining"])}
	if region:
		filters["region"] = region
	return frappe.get_all(
		"Space Cluster",
		filters=filters,
		fields=["name", "cluster_name", "title", "region", "status", "health", "active_sites", "max_sites", "load_score"],
		order_by="title asc",
	)
