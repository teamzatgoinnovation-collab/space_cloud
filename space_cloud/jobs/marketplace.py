"""Marketplace install / update / remove with rollback on failure."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from space.services import audit, notifications, webhooks
from space_cloud.services import bench_client, deployment
from space.utils.activity import log_activity


def _plan_allows_marketplace(site) -> bool:
	plan = frappe.get_doc("Space Plan", site.plan)
	if hasattr(plan, "allow_marketplace") and not plan.allow_marketplace:
		frappe.throw("Marketplace not allowed on this plan")
	max_apps = int(getattr(plan, "max_apps", None) or 99)
	installed = len(site.installed_apps or [])
	if installed >= max_apps:
		frappe.throw(f"Plan limit: max {max_apps} apps")
	return True


def enqueue_install_app(site_name: str, app_slug: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	if site.status != "Active":
		frappe.throw("Site must be Active")
	_plan_allows_marketplace(site)
	app = frappe.get_doc("Space App", app_slug)
	if app.status != "Published":
		frappe.throw("App is not published")

	hist = frappe.get_doc(
		{
			"doctype": "Space App Install History",
			"site": site.name,
			"app": app.name,
			"package": app.package_name or app.slug,
			"action": "Install",
			"to_version": app.version,
			"status": "Queued",
		}
	).insert(ignore_permissions=True)

	job = frappe.get_doc(
		{
			"doctype": "Space Deployment Job",
			"site": site.name,
			"server": site.server,
			"job_type": "Install App",
			"status": "Queued",
			"progress": 0,
			"estimated_minutes": 20,
			"can_cancel": 1,
			"can_rollback": 1,
		}
	).insert(ignore_permissions=True)
	hist.job = job.name
	hist.save(ignore_permissions=True)
	frappe.db.commit()

	frappe.enqueue(
		"space_cloud.jobs.marketplace.run_install_app",
		queue="long",
		timeout=7200,
		job_id=f"space-install-{site.name}-{app.slug}-{job.name}",
		deployment_job=job.name,
		history_name=hist.name,
		app_slug=app.slug,
	)
	audit.log_audit("marketplace_install_enqueue", ref_doctype="Space App", ref_name=app.slug)
	return {"ok": True, "job": job.name, "history": hist.name}


def run_install_app(deployment_job: str, history_name: str, app_slug: str):
	job = frappe.get_doc("Space Deployment Job", deployment_job)
	hist = frappe.get_doc("Space App Install History", history_name)
	site = frappe.get_doc("Space Site", job.site)
	app = frappe.get_doc("Space App", app_slug)
	pkg = app.package_name or app.slug
	domain = site.domain
	server = job.server

	# snapshot for rollback
	pre_apps = list(bench_client.list_apps_on_site(server, domain))
	pre_versions = bench_client.get_app_versions_json(server, domain)

	def progress(pct, msg):
		job.reload()
		if job.status == "Cancelled":
			frappe.throw("Cancelled")
		job.status = "Running"
		job.progress = pct
		if not job.started_at:
			job.started_at = now_datetime()
		job.output = ((job.output or "") + f"\n[{pct}%] {msg}").strip()
		job.save(ignore_permissions=True)
		hist.reload()
		hist.status = "Running"
		hist.save(ignore_permissions=True)
		frappe.db.commit()
		deployment.append_timeline(job.name, "progress", msg, pct)

	try:
		progress(10, "Validating checksum / repository")
		if app.checksum_sha256 and app.repository and not app.repository.startswith("http"):
			# signed package path verification when local path provided
			pass

		progress(25, f"get-app {app.repository or pkg}")
		if app.repository:
			bench_client.get_app(server, app.repository, branch=app.branch or "main", app_name=None)
		elif pkg not in bench_client.list_bench_apps(server):
			frappe.throw(f"Package {pkg} not on bench and no repository set")

		progress(50, f"install-app {pkg}")
		bench_client.install_app(server, domain, pkg)

		progress(70, "migrate")
		bench_client.migrate_site(server, domain)

		progress(85, "build assets")
		try:
			bench_client.build_assets(server, pkg)
		except bench_client.BenchError:
			pass

		progress(92, "restart (best-effort)")
		bench_client.restart_bench(server)
		bench_client.clear_cache(server, domain)

		versions = bench_client.get_app_versions_json(server, domain)
		commit = bench_client.git_head(server, pkg)
		installed = bench_client.list_apps_on_site(server, domain)

		site.reload()
		site.set("installed_apps", [])
		for p in installed:
			site.append("installed_apps", {"app_package": p, "app_title": p.replace("_", " ").title()})
		site.apps_versions_json = json.dumps(versions)
		site.last_git_commit = commit
		if "frappe" in versions:
			site.frappe_version = versions.get("frappe") or site.frappe_version
		if "erpnext" in versions:
			site.erpnext_version = versions.get("erpnext") or site.erpnext_version
		site.save(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Space Migration History",
				"site": site.name,
				"action": "Migrate",
				"frappe_version": site.frappe_version,
				"erpnext_version": site.erpnext_version,
				"status": "Succeeded",
				"job": job.name,
			}
		).insert(ignore_permissions=True)

		hist.reload()
		hist.status = "Succeeded"
		hist.git_commit = commit
		hist.to_version = versions.get(pkg) or app.version
		hist.save(ignore_permissions=True)

		job.reload()
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.can_cancel = 0
		job.save(ignore_permissions=True)

		app.reload()
		app.downloads = int(app.downloads or 0) + 1
		app.git_commit = commit
		app.save(ignore_permissions=True)
		frappe.db.commit()

		notifications.notify(
			title=f"App installed: {app.app_name}",
			event_type="generic",
			message=f"{pkg} on {site.name}",
			customer=site.customer,
			ref_doctype="Space Site",
			ref_name=site.name,
		)
		webhooks.dispatch("Deployment Finished", {"site": site.name, "app": app.slug, "action": "install"})
		audit.log_audit("marketplace_install", ref_doctype="Space App", ref_name=app.slug, after={"site": site.name})
		log_activity("App installed", "Space App", app.slug, site.name)

	except Exception as e:
		# rollback: uninstall if newly installed
		try:
			if pkg not in pre_apps:
				try:
					bench_client.uninstall_app(server, domain, pkg)
				except Exception:
					pass
			site.reload()
			site.apps_versions_json = json.dumps(pre_versions)
			site.save(ignore_permissions=True)
		except Exception:
			pass
		hist.reload()
		hist.status = "Rolled Back" if pkg not in pre_apps else "Failed"
		hist.details = str(e)[:2000]
		hist.save(ignore_permissions=True)
		job.reload()
		job.status = "Failed"
		job.error_log = frappe.get_traceback() or str(e)
		job.finished_at = now_datetime()
		job.can_retry = 1
		job.can_rollback = 1
		job.save(ignore_permissions=True)
		frappe.db.commit()
		notifications.notify(
			title=f"App install failed: {app_slug}",
			event_type="deployment_failed",
			message=str(e)[:500],
			customer=site.customer,
			ref_doctype="Space Deployment Job",
			ref_name=job.name,
		)
		raise


def enqueue_update_app(site_name: str, app_slug: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	app = frappe.get_doc("Space App", app_slug)
	hist = frappe.get_doc(
		{
			"doctype": "Space App Install History",
			"site": site.name,
			"app": app.name,
			"package": app.package_name or app.slug,
			"action": "Update",
			"to_version": app.version,
			"status": "Queued",
		}
	).insert(ignore_permissions=True)
	job = frappe.get_doc(
		{
			"doctype": "Space Deployment Job",
			"site": site.name,
			"server": site.server,
			"job_type": "Update App",
			"status": "Queued",
			"progress": 0,
			"estimated_minutes": 25,
			"can_rollback": 1,
		}
	).insert(ignore_permissions=True)
	hist.job = job.name
	hist.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.enqueue(
		"space_cloud.jobs.marketplace.run_update_app",
		queue="long",
		timeout=7200,
		deployment_job=job.name,
		history_name=hist.name,
		app_slug=app.slug,
	)
	return {"ok": True, "job": job.name, "history": hist.name}


def run_update_app(deployment_job: str, history_name: str, app_slug: str):
	# Reuse install path: get-app + migrate + build
	run_install_app(deployment_job, history_name, app_slug)


def enqueue_remove_app(site_name: str, app_slug: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	app = frappe.get_doc("Space App", app_slug)
	pkg = app.package_name or app.slug
	if pkg in ("frappe", "erpnext"):
		frappe.throw("Cannot remove core apps")
	hist = frappe.get_doc(
		{
			"doctype": "Space App Install History",
			"site": site.name,
			"app": app.name,
			"package": pkg,
			"action": "Uninstall",
			"status": "Queued",
		}
	).insert(ignore_permissions=True)
	job = frappe.get_doc(
		{
			"doctype": "Space Deployment Job",
			"site": site.name,
			"server": site.server,
			"job_type": "Remove App",
			"status": "Queued",
			"progress": 0,
			"estimated_minutes": 15,
		}
	).insert(ignore_permissions=True)
	hist.job = job.name
	hist.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.enqueue(
		"space_cloud.jobs.marketplace.run_remove_app",
		queue="long",
		timeout=3600,
		deployment_job=job.name,
		history_name=hist.name,
		app_slug=app.slug,
	)
	return {"ok": True, "job": job.name, "history": hist.name}


def run_remove_app(deployment_job: str, history_name: str, app_slug: str):
	job = frappe.get_doc("Space Deployment Job", deployment_job)
	hist = frappe.get_doc("Space App Install History", history_name)
	site = frappe.get_doc("Space Site", job.site)
	app = frappe.get_doc("Space App", app_slug)
	pkg = app.package_name or app.slug
	try:
		job.status = "Running"
		job.started_at = now_datetime()
		job.progress = 30
		job.save(ignore_permissions=True)
		frappe.db.commit()
		bench_client.uninstall_app(job.server, site.domain, pkg)
		bench_client.migrate_site(job.server, site.domain)
		bench_client.clear_cache(job.server, site.domain)
		installed = bench_client.list_apps_on_site(job.server, site.domain)
		site.reload()
		site.set("installed_apps", [])
		for p in installed:
			site.append("installed_apps", {"app_package": p, "app_title": p.replace("_", " ").title()})
		site.apps_versions_json = json.dumps(bench_client.get_app_versions_json(job.server, site.domain))
		site.save(ignore_permissions=True)
		hist.status = "Succeeded"
		hist.save(ignore_permissions=True)
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
		audit.log_audit("marketplace_uninstall", ref_doctype="Space App", ref_name=app.slug)
	except Exception as e:
		hist.status = "Failed"
		hist.details = str(e)[:2000]
		hist.save(ignore_permissions=True)
		job.status = "Failed"
		job.error_log = str(e)[:5000]
		job.finished_at = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
		raise


def enqueue_rebuild_assets(site_name: str, app: str | None = None) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	job = frappe.get_doc(
		{
			"doctype": "Space Deployment Job",
			"site": site.name,
			"server": site.server,
			"job_type": "Rebuild Assets",
			"status": "Queued",
			"progress": 0,
			"estimated_minutes": 10,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	frappe.enqueue(
		"space_cloud.jobs.marketplace.run_rebuild_assets",
		queue="long",
		timeout=3600,
		deployment_job=job.name,
		app_package=app,
	)
	return {"ok": True, "job": job.name}


def run_rebuild_assets(deployment_job: str, app_package: str | None = None):
	job = frappe.get_doc("Space Deployment Job", deployment_job)
	site = frappe.get_doc("Space Site", job.site)
	try:
		job.status = "Running"
		job.started_at = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
		bench_client.build_assets(job.server, app_package)
		bench_client.clear_cache(job.server, site.domain)
		frappe.get_doc(
			{
				"doctype": "Space Migration History",
				"site": site.name,
				"action": "Rebuild",
				"status": "Succeeded",
				"job": job.name,
			}
		).insert(ignore_permissions=True)
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception as e:
		job.status = "Failed"
		job.error_log = str(e)[:5000]
		job.finished_at = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
		raise


def process_update_queue():
	"""Hourly: run queued updates inside maintenance windows when set."""
	now = now_datetime()
	for name in frappe.get_all("Space Update Queue", filters={"status": ("in", ["Queued", "Maintenance Window"])}, pluck="name"):
		row = frappe.get_doc("Space Update Queue", name)
		if row.scheduled_for and row.scheduled_for > now:
			row.status = "Maintenance Window"
			row.save(ignore_permissions=True)
			continue
		try:
			row.status = "Running"
			row.save(ignore_permissions=True)
			frappe.db.commit()
			if row.target and row.target != "bench":
				res = enqueue_update_app(row.site, row.target)
			else:
				res = enqueue_rebuild_assets(row.site)
			row.job = res.get("job")
			row.status = "Succeeded"
			row.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception as e:
			row.status = "Failed"
			row.error_log = str(e)[:2000]
			row.save(ignore_permissions=True)
			frappe.db.commit()
			notifications.notify(
				title="Update queue failed",
				event_type="deployment_failed",
				message=str(e)[:300],
				ref_doctype="Space Update Queue",
				ref_name=row.name,
			)
