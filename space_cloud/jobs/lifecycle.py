"""Suspend / resume / delete site jobs."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from space_cloud.services import bench_client
from space.services import notifications
from space.utils.activity import log_activity


def _enqueue(site_name: str, job_type: str, method: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	job = frappe.get_doc(
		{
			"doctype": "Space Deployment Job",
			"site": site.name,
			"server": site.server,
			"job_type": job_type,
			"status": "Queued",
			"progress": 0,
			"estimated_minutes": 5,
			"can_cancel": 1,
		}
	).insert(ignore_permissions=True)
	site.job = job.name
	site.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.enqueue(
		method,
		queue="long",
		timeout=3600,
		job_id=f"space-{job_type.lower()}-{site.name}-{job.name}",
		deployment_job=job.name,
	)
	log_activity(f"{job_type} enqueued", "Space Site", site.name, job.name)
	return {"ok": True, "job": job.name}


def enqueue_suspend_site(site_name: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	if site.status != "Active":
		frappe.throw("Only Active sites can be suspended")
	return _enqueue(site_name, "Suspend", "space_cloud.jobs.lifecycle.run_suspend_site")


def enqueue_resume_site(site_name: str) -> dict:
	site = frappe.get_doc("Space Site", site_name)
	if site.status != "Suspended":
		frappe.throw("Only Suspended sites can be resumed")
	return _enqueue(site_name, "Resume", "space_cloud.jobs.lifecycle.run_resume_site")


def guard_deletable(site, source: str = "user") -> None:
	"""Refuse to delete what must never be deleted. Applies to every route (customer button, admin, scheduler):
	the portal's own site and protected domains first, then -- for the inactivity scheduler -- that the
	subscription really is scheduled, was warned, and is not held or excluded."""
	from space.services import lifecycle as lc

	domain = (site.domain or "").lower()
	if not domain or domain in lc.protected_domains():
		frappe.throw(f"{site.name} is a protected site and cannot be deleted")
	if source != "inactivity":
		return
	sub = site.subscription
	if not sub:
		frappe.throw("No subscription: refusing automatic deletion")
	row = frappe.db.get_value(
		"Space Subscription", sub, ["lifecycle_status", "deletion_hold", "paid_until"], as_dict=True
	)
	if row.lifecycle_status != lc.DELETION_SCHEDULED:
		frappe.throw("Subscription is not scheduled for deletion")
	if row.deletion_hold or lc.is_excluded(site.name) or lc.is_excluded(domain):
		frappe.throw("Site is held or excluded from automatic deletion")
	if lc.is_paid(row.paid_until):
		frappe.throw("Subscription is paid: refusing automatic deletion")


def enqueue_delete_site(site_name: str, source: str = "user") -> dict:
	site = frappe.get_doc("Space Site", site_name)
	if site.status == "Deleted":
		frappe.throw("Site already deleted")
	guard_deletable(site, source)
	return _enqueue(site_name, "Delete", "space_cloud.jobs.lifecycle.run_delete_site")


def run_suspend_site(deployment_job: str | None = None, job_name: str | None = None):
	_run_simple(deployment_job or job_name, maintenance=True, final_status="Suspended")


def run_resume_site(deployment_job: str | None = None, job_name: str | None = None):
	_run_simple(deployment_job or job_name, maintenance=False, final_status="Active")


def _run_simple(job_name: str, *, maintenance: bool, final_status: str):
	if not job_name:
		frappe.throw("deployment_job is required")
	job = frappe.get_doc("Space Deployment Job", job_name)
	site = frappe.get_doc("Space Site", job.site)
	try:
		job.status = "Running"
		job.started_at = now_datetime()
		job.progress = 20
		job.save(ignore_permissions=True)
		frappe.db.commit()

		bench_client.set_maintenance(job.server, site.domain, maintenance)
		job.progress = 80
		job.output = f"maintenance_mode={'on' if maintenance else 'off'}"
		job.save(ignore_permissions=True)

		site.reload()
		site.status = final_status
		site.save(ignore_permissions=True)

		job.reload()
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.can_cancel = 0
		job.save(ignore_permissions=True)
		frappe.db.commit()
		log_activity(f"Site {final_status}", "Space Site", site.name)
		if final_status in ("Suspended", "Active"):
			notifications.notify(
				title=f"Site {'suspended' if final_status == 'Suspended' else 'resumed'}: {site.name}",
				event_type="site_suspended" if final_status == "Suspended" else "site_resumed",
				message=site.domain or site.name,
				customer=site.customer,
				ref_doctype="Space Site",
				ref_name=site.name,
			)
	except Exception as e:
		job.reload()
		job.status = "Failed"
		job.error_log = frappe.get_traceback() or str(e)
		job.finished_at = now_datetime()
		job.can_retry = 1
		job.can_cancel = 0
		job.save(ignore_permissions=True)
		frappe.db.commit()
		notifications.notify(
			title=f"Deployment failed: {site.name}",
			event_type="deployment_failed",
			message=str(e)[:500],
			customer=site.customer,
			ref_doctype="Space Deployment Job",
			ref_name=job.name,
		)
		raise


def _stage(site, name: str) -> None:
	"""Audit row per deletion stage: a failed run shows exactly how far it got."""
	from space.services import lifecycle as lc

	lc.record_event("deletion_stage", subscription=site.subscription, site=site.name, details={"stage": name})
	frappe.db.commit()


def _cleanup_metadata(site) -> None:
	"""Provisioning metadata of THIS site only: domains and backup records (their files went with the site folder)."""
	frappe.db.set_value("Space Backup", {"site": site.name}, "status", "Deleted")
	frappe.db.delete("Space Domain", {"site": site.name})
	frappe.db.commit()


def _mark_subscription_deleted(site) -> None:
	from space.services import lifecycle as lc

	if site.subscription and frappe.db.get_value("Space Subscription", site.subscription, "lifecycle_status"):
		try:
			lc.transition(site.subscription, lc.DELETED, reason="site deleted", push=False)
			lc.record_event("deletion_completed", subscription=site.subscription, site=site.name)
		except Exception:
			frappe.log_error(title=f"Space lifecycle: could not mark {site.name} deleted")


def run_delete_site(deployment_job: str | None = None, job_name: str | None = None):
	job_name = deployment_job or job_name
	if not job_name:
		frappe.throw("deployment_job is required")
	job = frappe.get_doc("Space Deployment Job", job_name)
	site = frappe.get_doc("Space Site", job.site)
	try:
		job.status = "Running"
		job.started_at = now_datetime()
		job.progress = 10
		job.save(ignore_permissions=True)
		frappe.db.commit()

		guard_deletable(site, "user")  # protected domains again, at run time (settings may have changed since enqueue)
		_stage(site, "guards_passed")
		if site.domain in bench_client.list_sites(job.server):
			job.progress = 40
			job.output = f"Dropping {site.domain}"
			job.save(ignore_permissions=True)
			frappe.db.commit()
			bench_client.drop_site(job.server, site.domain)
			_stage(site, "dropped")
		if site.domain in bench_client.list_sites(job.server):
			raise RuntimeError(f"{site.domain} is still on the bench after drop-site")
		try:
			bench_client.purge_archived_site(job.server, site.domain)
			_stage(site, "files_purged")
		except bench_client.BenchError as e:
			job.reload()
			job.output = (job.output or "") + f"\nWARN archived files: {e}"
			job.save(ignore_permissions=True)
		try:
			bench_client.remove_route(job.server, site.domain)
		except bench_client.BenchError as e:
			job.reload()
			job.output = (job.output or "") + f"\nWARN route removal: {e}"
			job.save(ignore_permissions=True)

		_cleanup_metadata(site)
		site.reload()
		site.status = "Deleted"
		site.save(ignore_permissions=True)
		_stage(site, "completed")
		_mark_subscription_deleted(site)

		job.reload()
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.can_cancel = 0
		job.output = (job.output or "") + "\nDeleted"
		job.save(ignore_permissions=True)
		frappe.db.commit()
		log_activity("Site deleted", "Space Site", site.name)
		notifications.notify(
			title=f"Site deleted: {site.name}",
			event_type="site_deleted",
			message=site.domain or site.name,
			customer=site.customer,
			ref_doctype="Space Site",
			ref_name=site.name,
		)
	except Exception as e:
		job.reload()
		job.status = "Failed"
		job.error_log = frappe.get_traceback() or str(e)
		job.finished_at = now_datetime()
		job.can_retry = 1
		job.can_cancel = 0
		job.save(ignore_permissions=True)
		frappe.db.commit()
		notifications.notify(
			title=f"Deployment failed: {site.name}",
			event_type="deployment_failed",
			message=str(e)[:500],
			customer=site.customer,
			ref_doctype="Space Deployment Job",
			ref_name=job.name,
		)
		raise
