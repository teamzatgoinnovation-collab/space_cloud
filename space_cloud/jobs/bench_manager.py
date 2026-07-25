"""Bench Manager — raw bench-level operations (get-app from git, install/uninstall
app, migrate, list apps, restart) for admins, independent of the Space App
marketplace catalog. Site-scoped ops reuse the existing Space Deployment Job
envelope + job_type values (Install App / Remove App / Migrate Site / Rebuild
Assets); server-scoped ops (fetching a new app onto the bench, restarting it)
use the core Space Job envelope via space.jobs.runner, since they aren't tied
to any one Space Site/Resource — exactly what Space Job exists for."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from space.services import audit, notifications
from space.utils.activity import log_activity
from space_cloud.services import bench_client, deployment


# ---------------------------------------------------------------------------
# Server-scoped (core Space Job) — bench get-app, bench restart
# ---------------------------------------------------------------------------


def enqueue_get_app(server: str, repo: str, branch: str = "main", app_name: str | None = None) -> str:
	from space.jobs.runner import enqueue_job

	frappe.get_doc("Space Server", server)  # existence check, raises if missing
	job_name = enqueue_job(
		"bench_get_app",
		reference_doctype="Space Server",
		reference_name=server,
		server=server,
		repo=repo,
		branch=branch,
		app_name=app_name,
	)
	audit.log_audit("bench_manager_get_app_enqueue", ref_doctype="Space Server", ref_name=server, details=repo)
	return job_name


def run_bench_get_app(space_job: str, server: str, repo: str, branch: str = "main", app_name: str | None = None):
	before = set(bench_client.list_bench_apps(server))
	bench_client.get_app(server, repo, branch=branch, app_name=app_name)
	after = set(bench_client.list_bench_apps(server))
	fetched = sorted(after - before) or sorted(after)
	log_activity(f"bench get-app {repo}", "Space Server", server, space_job)
	notifications.notify(
		title=f"App fetched onto bench: {server}",
		event_type="generic",
		message=f"{repo} ({branch}) — now on bench: {', '.join(fetched) or 'unchanged'}",
		ref_doctype="Space Job",
		ref_name=space_job,
	)
	return {"server": server, "repo": repo, "branch": branch, "apps_on_bench": sorted(after), "newly_fetched": fetched}


def enqueue_restart_bench(server: str) -> str:
	from space.jobs.runner import enqueue_job

	frappe.get_doc("Space Server", server)
	job_name = enqueue_job(
		"bench_restart", reference_doctype="Space Server", reference_name=server, server=server
	)
	audit.log_audit("bench_manager_restart_enqueue", ref_doctype="Space Server", ref_name=server)
	return job_name


def run_bench_restart(space_job: str, server: str):
	result = bench_client.restart_bench(server)
	log_activity("bench restart", "Space Server", server, space_job)
	return result


# ---------------------------------------------------------------------------
# Site-scoped (Space Deployment Job) — install-app, uninstall-app, migrate
# ---------------------------------------------------------------------------


def _new_deployment_job(site, job_type: str, *, estimated_minutes: int = 10) -> "frappe.model.document.Document":
	job = frappe.get_doc(
		{
			"doctype": "Space Deployment Job",
			"site": site.name,
			"server": site.server,
			"job_type": job_type,
			"status": "Queued",
			"progress": 0,
			"estimated_minutes": estimated_minutes,
			"can_cancel": 1,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return job


def _progress(job, pct: int, msg: str):
	job.reload()
	if job.status == "Cancelled":
		frappe.throw("Cancelled")
	job.status = "Running"
	job.progress = pct
	if not job.started_at:
		job.started_at = now_datetime()
	job.output = ((job.output or "") + f"\n[{pct}%] {msg}").strip()
	job.save(ignore_permissions=True)
	frappe.db.commit()
	deployment.append_timeline(job.name, "progress", msg, pct)


def _sync_installed_apps(site, server: str, domain: str):
	installed = bench_client.list_apps_on_site(server, domain)
	versions = bench_client.get_app_versions_json(server, domain)
	site.reload()
	site.set("installed_apps", [])
	for p in installed:
		site.append("installed_apps", {"app_package": p, "app_title": p.replace("_", " ").title()})
	site.apps_versions_json = json.dumps(versions)
	if "frappe" in versions:
		site.frappe_version = versions.get("frappe") or site.frappe_version
	if "erpnext" in versions:
		site.erpnext_version = versions.get("erpnext") or site.erpnext_version
	site.save(ignore_permissions=True)
	frappe.db.commit()
	return installed


def enqueue_install_app(site_name: str, app_package: str, repo: str | None = None, branch: str = "main") -> dict:
	site = frappe.get_doc("Space Site", site_name)
	if site.status != "Active":
		frappe.throw("Site must be Active")

	job = _new_deployment_job(site, "Install App", estimated_minutes=15)
	frappe.enqueue(
		"space_cloud.jobs.bench_manager.run_install_app",
		queue="long",
		timeout=7200,
		job_id=f"space-bm-install-{site.name}-{app_package}-{job.name}",
		deployment_job=job.name,
		app_package=app_package,
		repo=repo,
		branch=branch,
	)
	audit.log_audit("bench_manager_install_enqueue", ref_doctype="Space Site", ref_name=site.name, details=app_package)
	return {"ok": True, "job": job.name}


def run_install_app(deployment_job: str, app_package: str, repo: str | None = None, branch: str = "main"):
	job = frappe.get_doc("Space Deployment Job", deployment_job)
	site = frappe.get_doc("Space Site", job.site)
	server = job.server
	domain = site.domain
	pre_apps = set(bench_client.list_apps_on_site(server, domain))

	try:
		if repo:
			_progress(job, 20, f"get-app {repo}")
			bench_client.get_app(server, repo, branch=branch, app_name=app_package)
		elif app_package not in bench_client.list_bench_apps(server):
			frappe.throw(f"Package {app_package} not on bench and no repository given")

		_progress(job, 50, f"install-app {app_package}")
		bench_client.install_app(server, domain, app_package)

		_progress(job, 75, "migrate")
		bench_client.migrate_site(server, domain)

		_progress(job, 90, "sync installed apps")
		_sync_installed_apps(site, server, domain)
		bench_client.clear_cache(server, domain)

		job.reload()
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.can_cancel = 0
		job.save(ignore_permissions=True)
		frappe.db.commit()

		notifications.notify(
			title=f"App installed: {app_package}",
			event_type="generic",
			message=f"{app_package} on {site.name}",
			customer=site.customer,
			ref_doctype="Space Site",
			ref_name=site.name,
		)
		audit.log_audit("bench_manager_install", ref_doctype="Space Site", ref_name=site.name, details=app_package)
		log_activity("App installed (bench manager)", "Space Site", site.name, job.name)
	except Exception as e:
		try:
			if app_package not in pre_apps:
				bench_client.uninstall_app(server, domain, app_package)
		except Exception:
			pass
		job.reload()
		job.status = "Failed"
		job.error_log = frappe.get_traceback() or str(e)
		job.finished_at = now_datetime()
		job.can_retry = 1
		job.save(ignore_permissions=True)
		frappe.db.commit()
		raise


def enqueue_uninstall_app(site_name: str, app_package: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	job = _new_deployment_job(site, "Remove App", estimated_minutes=10)
	frappe.enqueue(
		"space_cloud.jobs.bench_manager.run_uninstall_app",
		queue="long",
		timeout=7200,
		job_id=f"space-bm-uninstall-{site.name}-{app_package}-{job.name}",
		deployment_job=job.name,
		app_package=app_package,
	)
	audit.log_audit("bench_manager_uninstall_enqueue", ref_doctype="Space Site", ref_name=site.name, details=app_package)
	return {"ok": True, "job": job.name}


def run_uninstall_app(deployment_job: str, app_package: str):
	job = frappe.get_doc("Space Deployment Job", deployment_job)
	site = frappe.get_doc("Space Site", job.site)
	server = job.server
	domain = site.domain

	try:
		_progress(job, 30, f"uninstall-app {app_package}")
		bench_client.uninstall_app(server, domain, app_package)

		_progress(job, 70, "migrate")
		bench_client.migrate_site(server, domain)

		_progress(job, 90, "sync installed apps")
		_sync_installed_apps(site, server, domain)
		bench_client.clear_cache(server, domain)

		job.reload()
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.can_cancel = 0
		job.save(ignore_permissions=True)
		frappe.db.commit()

		audit.log_audit("bench_manager_uninstall", ref_doctype="Space Site", ref_name=site.name, details=app_package)
		log_activity("App uninstalled (bench manager)", "Space Site", site.name, job.name)
	except Exception as e:
		job.reload()
		job.status = "Failed"
		job.error_log = frappe.get_traceback() or str(e)
		job.finished_at = now_datetime()
		job.can_retry = 1
		job.save(ignore_permissions=True)
		frappe.db.commit()
		raise


def enqueue_migrate_site(site_name: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	job = _new_deployment_job(site, "Migrate Site", estimated_minutes=10)
	frappe.enqueue(
		"space_cloud.jobs.bench_manager.run_migrate_site",
		queue="long",
		timeout=3600,
		job_id=f"space-bm-migrate-{site.name}-{job.name}",
		deployment_job=job.name,
	)
	audit.log_audit("bench_manager_migrate_enqueue", ref_doctype="Space Site", ref_name=site.name)
	return {"ok": True, "job": job.name}


def run_migrate_site(deployment_job: str):
	job = frappe.get_doc("Space Deployment Job", deployment_job)
	site = frappe.get_doc("Space Site", job.site)
	server = job.server
	domain = site.domain

	try:
		_progress(job, 40, "migrate")
		bench_client.migrate_site(server, domain)
		_progress(job, 80, "clear cache")
		bench_client.clear_cache(server, domain)
		_sync_installed_apps(site, server, domain)

		job.reload()
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.can_cancel = 0
		job.save(ignore_permissions=True)
		frappe.db.commit()
		audit.log_audit("bench_manager_migrate", ref_doctype="Space Site", ref_name=site.name)
		log_activity("Site migrated (bench manager)", "Space Site", site.name, job.name)
	except Exception as e:
		job.reload()
		job.status = "Failed"
		job.error_log = frappe.get_traceback() or str(e)
		job.finished_at = now_datetime()
		job.can_retry = 1
		job.save(ignore_permissions=True)
		frappe.db.commit()
		raise


# ---------------------------------------------------------------------------
# Read-only helpers (no job)
# ---------------------------------------------------------------------------


def list_bench_apps(server: str) -> list[str]:
	return bench_client.list_bench_apps(server)


def list_site_apps(site: str) -> list[str]:
	row = frappe.db.get_value("Space Site", site, ["server", "domain"], as_dict=True)
	if not row:
		frappe.throw("Site not found")
	return bench_client.list_apps_on_site(row.server, row.domain)
