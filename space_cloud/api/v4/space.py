"""Space API v4 — enterprise cloud infrastructure."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, today

from space.api.v1.response import customer_for_user, fail, ok, require_roles
from space_cloud.jobs import infrastructure as infra_jobs
from space.services import audit, rate_limit
from space_cloud.services import infrastructure, server_pool
from space_cloud.services import bench_client
from space_cloud.services import quota as quota_service
from space_cloud.services import hosting_pool
from space_cloud.jobs import bench_manager


def _rl():
	rate_limit.check_rate_limit("v4")


def _require_site_access(site: str) -> None:
	"""Admin/operator roles see any site; a plain Space Customer only their own."""
	require_roles("Space Admin", "Space Operator", "System Manager", "Support Engineer", "Readonly Auditor", "Space Customer")
	admin_roles = {"Space Admin", "Space Operator", "System Manager", "Support Engineer", "Readonly Auditor"}
	if frappe.session.user == "Administrator" or admin_roles.intersection(frappe.get_roles()):
		return
	owner = frappe.db.get_value("Space Site", site, "customer")
	if not owner or owner != customer_for_user():
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def list_regions():
	_rl()
	return ok(server_pool.list_regions())


@frappe.whitelist()
def list_clusters(region: str | None = None):
	_rl()
	return ok(server_pool.list_clusters(region=region))


@frappe.whitelist()
def list_nodes(cluster: str | None = None):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	filters = {}
	if cluster:
		filters["cluster"] = cluster
	rows = frappe.get_all(
		"Space Node",
		filters=filters,
		fields=["name", "node_name", "title", "cluster", "server", "region", "status", "health", "active_sites", "max_sites"],
		order_by="name asc",
	)
	return ok(rows)


@frappe.whitelist()
def infra_status():
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	return ok(
		{
			"regions": server_pool.list_regions(),
			"clusters": server_pool.list_clusters(),
			"servers": server_pool.capacity_summary(),
			"alerts_open": frappe.db.count("Space Alert", {"status": "Open"}) if frappe.db.exists("DocType", "Space Alert") else 0,
		}
	)


@frappe.whitelist()
def create_site_v4(
	site_name: str,
	plan: str,
	admin_password: str,
	customer: str | None = None,
	preferred_server: str | None = None,
	preferred_region: str | None = None,
	preferred_cluster: str | None = None,
	affinity_site: str | None = None,
	anti_affinity_site: str | None = None,
	manual_override: str | None = None,
):
	"""Create site with advanced placement; mirrors v2 response shape."""
	_rl()
	require_roles("Space Admin", "Space Operator", "Space Customer", "System Manager")
	from space_cloud.utils.site_naming import build_domain, validate_slug

	slug = validate_slug(site_name)
	domain = build_domain(slug)
	if frappe.db.exists("Space Site", slug) or frappe.db.exists("Space Site", {"domain": domain}):
		return fail("Site already exists", "EXISTS")

	cust = customer or customer_for_user()
	if not cust:
		if frappe.session.user in (None, "Guest"):
			return fail("Login required", "AUTH", 401)
		email = frappe.db.get_value("User", frappe.session.user, "email") or frappe.session.user
		cust_name = frappe.session.user
		if not frappe.db.exists("Space Customer", cust_name):
			frappe.get_doc(
				{
					"doctype": "Space Customer",
					"customer_name": cust_name,
					"email": email,
					"user": frappe.session.user,
					"status": "Active",
				}
			).insert(ignore_permissions=True)
		cust = cust_name

	server = server_pool.select_server_advanced(
		preferred_server=preferred_server,
		preferred_region=preferred_region,
		preferred_cluster=preferred_cluster,
		plan=plan,
		affinity_site=affinity_site,
		anti_affinity_site=anti_affinity_site,
		manual_override=manual_override,
	)
	plan_doc = frappe.get_doc("Space Plan", plan)
	trial_days = int(plan_doc.trial_days or 0)
	payment_status = "Trial" if trial_days > 0 and float(plan_doc.monthly_price or 0) > 0 else "Free"
	status = "Trial" if payment_status == "Trial" else "Active"

	sub = frappe.get_doc(
		{
			"doctype": "Space Subscription",
			"customer": cust,
			"plan": plan,
			"start_date": today(),
			"end_date": add_days(today(), 365),
			"renewal_date": add_days(today(), 365),
			"trial_ends_on": add_days(today(), trial_days) if trial_days else None,
			"grace_period_days": 3,
			"status": status,
			"payment_status": payment_status,
			"renewal": 0,
		}
	).insert(ignore_permissions=True)

	site_payload = {
		"doctype": "Space Site",
		"site_name": slug,
		"customer": cust,
		"server": server,
		"plan": plan,
		"subscription": sub.name,
		"status": "Draft",
		"admin_password": admin_password,
	}
	if preferred_region:
		site_payload["preferred_region"] = preferred_region
	if preferred_cluster:
		site_payload["preferred_cluster"] = preferred_cluster
	if affinity_site:
		site_payload["affinity_site"] = affinity_site
	if anti_affinity_site:
		site_payload["anti_affinity_site"] = anti_affinity_site

	site = frappe.get_doc(site_payload).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Space Domain",
			"site": site.name,
			"domain": site.domain,
			"is_primary": 1,
			"dns_status": "Verified",
			"ssl_status": "Wildcard",
			"verified_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	from space_cloud.jobs.provision import enqueue_create_site

	result = enqueue_create_site(site.name)
	audit.log_audit(
		"create_site_v4",
		api_method="space.api.v4.space.create_site_v4",
		ref_doctype="Space Site",
		ref_name=site.name,
		after={"server": server, "plan": plan, "region": preferred_region},
	)
	return ok(
		{
			"site": site.name,
			"domain": site.domain,
			"job": result.get("job"),
			"server": server,
			"region": preferred_region,
			"api": "v4",
		}
	)


@frappe.whitelist()
def enqueue_migration(site: str, target_server: str, target_region: str | None = None):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager")
	site_doc = frappe.get_doc("Space Site", site)
	mig = frappe.get_doc(
		{
			"doctype": "Space Site Migration",
			"site": site,
			"source_server": site_doc.server,
			"target_server": target_server,
			"source_region": frappe.db.get_value("Space Server", site_doc.server, "region") if frappe.db.has_column("Space Server", "region") else None,
			"target_region": target_region,
			"status": "Draft",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return ok(infra_jobs.enqueue_site_migration(mig.name))


@frappe.whitelist()
def list_migrations(site: str | None = None):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	filters = {}
	if site:
		filters["site"] = site
	rows = frappe.get_all(
		"Space Site Migration",
		filters=filters,
		fields=["name", "site", "source_server", "target_server", "status", "validation_ok", "job", "creation"],
		order_by="creation desc",
		limit_page_length=50,
	)
	return ok(rows)


@frappe.whitelist()
def list_alerts(status: str | None = "Open"):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Support Engineer", "Readonly Auditor")
	filters = {}
	if status:
		filters["status"] = status
	rows = frappe.get_all(
		"Space Alert",
		filters=filters,
		fields=["name", "title", "severity", "status", "metric", "value", "server", "cluster", "opened_at"],
		order_by="creation desc",
		limit_page_length=100,
	)
	return ok(rows)


@frappe.whitelist()
def acknowledge_alert(name: str):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Support Engineer")
	doc = frappe.get_doc("Space Alert", name)
	doc.status = "Acknowledged"
	doc.save(ignore_permissions=True)
	return ok({"name": name, "status": "Acknowledged"})


@frappe.whitelist()
def docker_overview(server: str | None = None):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager")
	return ok(infrastructure.list_docker_overview(server))


@frappe.whitelist()
def docker_restart(server: str | None = None, container: str | None = None):
	_rl()
	require_roles("Space Admin", "System Manager")
	if not container:
		return fail("container required", "INVALID")
	return ok(bench_client.docker_restart(server, container))


@frappe.whitelist()
def docker_logs(server: str | None = None, container: str | None = None, tail: int = 100):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager")
	if not container:
		return fail("container required", "INVALID")
	return ok({"logs": bench_client.docker_logs(server, container, tail=int(tail or 100))})


@frappe.whitelist()
def failover_stub(primary_server: str):
	_rl()
	require_roles("Space Admin", "System Manager")
	return ok(infrastructure.safe_failover_stub(primary_server))


@frappe.whitelist()
def run_dr_test(plan: str):
	_rl()
	require_roles("Space Admin", "System Manager")
	return ok(infra_jobs.run_dr_test(plan))


@frappe.whitelist()
def capacity_forecast(horizon_days: int = 30):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	names = infrastructure.forecast_capacity(int(horizon_days or 30))
	rows = frappe.get_all(
		"Space Capacity Forecast",
		filters={"name": ("in", names)} if names else {},
		fields=["*"],
		order_by="creation desc",
		limit_page_length=50,
	)
	return ok(rows)


@frappe.whitelist()
def observability_query(q: str | None = None, server: str | None = None, limit: int = 50):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	return ok(infrastructure.query_observability_logs(q=q, server=server, limit=int(limit or 50)))


@frappe.whitelist()
def rotate_secret(name: str, new_value: str):
	_rl()
	require_roles("Space Admin", "System Manager")
	return ok(infrastructure.rotate_secret(name, new_value))


@frappe.whitelist()
def start_maintenance(window: str):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager")
	return ok(infra_jobs.run_maintenance_window(window))


@frappe.whitelist()
def heartbeat_now():
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager")
	infrastructure.heartbeat_all()
	return ok({"ran": True})


@frappe.whitelist()
def site_usage(site: str):
	_rl()
	_require_site_access(site)
	row = frappe.db.get_value(
		"Space Site",
		site,
		[
			"storage_used_mb",
			"database_size_mb",
			"public_files_mb",
			"private_files_mb",
			"backup_files_mb",
			"site_user_count",
			"site_company_count",
			"usage_last_scanned_at",
		],
		as_dict=True,
	)
	if not row:
		return fail("Site not found", "NOT_FOUND")
	return ok(row)


@frappe.whitelist()
def site_quota(site: str):
	_rl()
	_require_site_access(site)
	return ok(quota_service.compute_site_quota(site))


@frappe.whitelist()
def fleet_quota_summary():
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	return ok(quota_service.compute_fleet_quota_summary())


@frappe.whitelist()
def storage_pool_status(server: str | None = None, cluster: str | None = None):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	return ok(hosting_pool.pool_status(server=server, cluster=cluster))


@frappe.whitelist()
def hosting_pool_summary():
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	pools = hosting_pool.pool_status()
	return ok(
		{
			"pools": pools,
			"total_capacity_gb": round(sum(p.get("capacity_gb") or 0 for p in pools), 2),
			"total_allocated_gb": round(sum(p.get("allocated_gb") or 0 for p in pools), 2),
			"total_used_gb": round(sum(p.get("used_gb") or 0 for p in pools), 2),
			"total_available_gb": round(sum(p.get("available_gb") or 0 for p in pools), 2),
		}
	)


@frappe.whitelist()
def bench_list_apps(server: str):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Readonly Auditor")
	return ok(bench_manager.list_bench_apps(server))


@frappe.whitelist()
def bench_list_site_apps(site: str):
	_rl()
	_require_site_access(site)
	return ok(bench_manager.list_site_apps(site))


@frappe.whitelist()
def bench_get_app(server: str, repo: str, branch: str = "main", app_name: str | None = None):
	"""bench get-app <repo> — fetches a new app onto the shared bench. Affects
	every site on this server; Space Admin / System Manager only."""
	_rl()
	require_roles("Space Admin", "System Manager")
	job = bench_manager.enqueue_get_app(server, repo, branch=branch, app_name=app_name)
	return ok({"job": job})


@frappe.whitelist()
def bench_restart(server: str):
	_rl()
	require_roles("Space Admin", "System Manager")
	job = bench_manager.enqueue_restart_bench(server)
	return ok({"job": job})


@frappe.whitelist()
def bench_install_app(site: str, app_package: str, repo: str | None = None, branch: str = "main"):
	_rl()
	require_roles("Space Admin", "System Manager")
	return ok(bench_manager.enqueue_install_app(site, app_package, repo=repo, branch=branch))


@frappe.whitelist()
def bench_uninstall_app(site: str, app_package: str):
	_rl()
	require_roles("Space Admin", "System Manager")
	return ok(bench_manager.enqueue_uninstall_app(site, app_package))


@frappe.whitelist()
def bench_migrate_site(site: str):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager")
	return ok(bench_manager.enqueue_migrate_site(site))


@frappe.whitelist()
def site_log_files(site: str):
	_rl()
	_require_site_access(site)
	site_doc = frappe.db.get_value("Space Site", site, ["server", "domain"], as_dict=True)
	if not site_doc or not site_doc.domain:
		return fail("Site not found", "NOT_FOUND")
	return ok(bench_client.list_site_log_files(site_doc.server, site_doc.domain))


@frappe.whitelist()
def site_log_tail(site: str, log_file: str, lines: int = 200):
	_rl()
	_require_site_access(site)
	site_doc = frappe.db.get_value("Space Site", site, ["server", "domain"], as_dict=True)
	if not site_doc or not site_doc.domain:
		return fail("Site not found", "NOT_FOUND")
	return ok({"logs": bench_client.get_site_log_tail(site_doc.server, site_doc.domain, log_file, lines=int(lines or 200))})
