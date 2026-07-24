"""Site migration / maintenance / DR jobs — best-effort on Docker bench."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from space.services import audit, notifications
from space_cloud.services import bench_client, deployment, server_pool
from space.utils.activity import log_activity


def enqueue_site_migration(migration_name: str) -> dict:
	mig = frappe.get_doc("Space Site Migration", migration_name)
	site = frappe.get_doc("Space Site", mig.site)
	if site.status not in ("Active", "Suspended"):
		frappe.throw("Site must be Active or Suspended to migrate")

	# validate
	notes = []
	ok = True
	if not _is_eligible_target(mig.target_server):
		ok = False
		notes.append("Target server not eligible")
	if mig.source_server == mig.target_server:
		ok = False
		notes.append("Source and target must differ")
	mig.validation_ok = 1 if ok else 0
	mig.validation_notes = "; ".join(notes) or "OK"
	mig.status = "Validating"
	mig.save(ignore_permissions=True)
	frappe.db.commit()
	if not ok:
		mig.status = "Failed"
		mig.error_log = mig.validation_notes
		mig.save(ignore_permissions=True)
		frappe.db.commit()
		return {"ok": False, "error": mig.validation_notes}

	job = frappe.get_doc(
		{
			"doctype": "Space Deployment Job",
			"site": site.name,
			"server": mig.target_server,
			"job_type": "Migrate Site",
			"status": "Queued",
			"progress": 0,
			"estimated_minutes": 45,
			"can_rollback": 1,
		}
	).insert(ignore_permissions=True)
	mig.job = job.name
	mig.status = "Queued"
	mig.save(ignore_permissions=True)
	frappe.db.commit()

	frappe.enqueue(
		"space_cloud.jobs.infrastructure.run_site_migration",
		queue="long",
		timeout=7200,
		deployment_job=job.name,
		migration_name=mig.name,
	)
	audit.log_audit("site_migration_enqueue", ref_doctype="Space Site Migration", ref_name=mig.name)
	return {"ok": True, "job": job.name, "migration": mig.name}


def run_site_migration(deployment_job: str, migration_name: str):
	job = frappe.get_doc("Space Deployment Job", deployment_job)
	mig = frappe.get_doc("Space Site Migration", migration_name)
	site = frappe.get_doc("Space Site", mig.site)
	src, dst = mig.source_server, mig.target_server

	def progress(pct, msg):
		job.reload()
		job.status = "Running"
		job.progress = pct
		if not job.started_at:
			job.started_at = now_datetime()
		job.output = ((job.output or "") + f"\n[{pct}%] {msg}").strip()
		job.save(ignore_permissions=True)
		mig.reload()
		mig.status = "Running"
		mig.started_at = mig.started_at or now_datetime()
		mig.save(ignore_permissions=True)
		frappe.db.commit()
		deployment.append_timeline(job.name, "progress", msg, pct)

	try:
		progress(10, "Backup source site")
		bench_client.backup_site(src, site.domain)

		progress(35, "Record target placement (metadata move)")
		# Full cross-host restore requires shared storage / rsync; on single-bench DO we reassign metadata.
		same_bench = _same_physical_bench(src, dst)
		if not same_bench:
			progress(50, "Cross-host restore hook (best-effort)")
			try:
				# Attempt restore path if bench_client supports it; otherwise metadata-only.
				if hasattr(bench_client, "restore_latest_backup"):
					bench_client.restore_latest_backup(dst, site.domain)
			except Exception as e:
				# rollback metadata
				raise RuntimeError(f"Cross-host migrate not fully supported: {e}") from e

		progress(80, "Update Space Site server assignment")
		site.reload()
		site.server = dst
		if mig.target_region and frappe.db.has_column("Space Site", "preferred_region"):
			site.preferred_region = mig.target_region
		site.save(ignore_permissions=True)

		progress(95, "Clear cache on target")
		try:
			bench_client.clear_cache(dst, site.domain)
		except Exception:
			pass

		mig.reload()
		mig.status = "Succeeded"
		mig.finished_at = now_datetime()
		mig.save(ignore_permissions=True)
		job.reload()
		job.status = "Succeeded"
		job.progress = 100
		job.finished_at = now_datetime()
		job.save(ignore_permissions=True)
		frappe.db.commit()
		notifications.notify(
			title=f"Site migrated: {site.name}",
			event_type="generic",
			message=f"{src} → {dst}",
			customer=site.customer,
			ref_doctype="Space Site Migration",
			ref_name=mig.name,
		)
		log_activity("Site migrated", "Space Site", site.name, f"{src}->{dst}")

	except Exception as e:
		# rollback assignment
		try:
			site.reload()
			site.server = src
			site.save(ignore_permissions=True)
			mig.reload()
			mig.status = "Rolled Back"
			mig.error_log = str(e)[:5000]
			mig.finished_at = now_datetime()
			mig.save(ignore_permissions=True)
		except Exception:
			mig.reload()
			mig.status = "Failed"
			mig.error_log = str(e)[:5000]
			mig.save(ignore_permissions=True)
		job.reload()
		job.status = "Failed"
		job.error_log = frappe.get_traceback() or str(e)
		job.finished_at = now_datetime()
		job.can_retry = 1
		job.save(ignore_permissions=True)
		frappe.db.commit()
		notifications.notify(
			title=f"Migration failed: {site.name}",
			event_type="deployment_failed",
			message=str(e)[:500],
			customer=site.customer,
			ref_doctype="Space Site Migration",
			ref_name=mig.name,
		)
		raise


def process_migration_queue():
	for name in frappe.get_all("Space Site Migration", filters={"status": "Queued"}, pluck="name"):
		mig = frappe.get_doc("Space Site Migration", name)
		if mig.job:
			continue
		try:
			enqueue_site_migration(name)
		except Exception:
			frappe.log_error(title=f"Migration queue failed: {name}")


def run_maintenance_window(window_name: str):
	win = frappe.get_doc("Space Maintenance Window", window_name)
	win.status = "Draining"
	win.save(ignore_permissions=True)
	frappe.db.commit()
	server = win.server
	if server and win.drain_sites:
		frappe.db.set_value("Space Server", server, "drain_mode", 1)
		# reassign future placements only — do not force-move live sites here
	win.status = "In Progress"
	win.save(ignore_permissions=True)
	frappe.db.commit()
	if win.upgrade_bench and server:
		try:
			bench_client.restart_bench(server)
		except Exception:
			pass
	win.status = "Completed"
	if server:
		frappe.db.set_value("Space Server", server, "drain_mode", 0)
	win.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "window": window_name}


def process_maintenance_windows():
	now = now_datetime()
	for name in frappe.get_all(
		"Space Maintenance Window",
		filters={"status": "Scheduled", "starts_at": ("<=", now)},
		pluck="name",
	):
		try:
			run_maintenance_window(name)
		except Exception:
			frappe.log_error(title=f"Maintenance window failed: {name}")


def run_dr_test(plan_name: str) -> dict:
	plan = frappe.get_doc("Space DR Plan", plan_name)
	plan.status = "Testing"
	plan.save(ignore_permissions=True)
	frappe.db.commit()
	# best-effort: ensure recent backups exist for scoped sites
	scope = (plan.sites_scope or "*").strip()
	filters = {"status": "Active"}
	sites = frappe.get_all("Space Site", filters=filters, pluck="name") if scope == "*" else [s.strip() for s in scope.split(",") if s.strip()]
	ok_count = 0
	for s in sites[:20]:
		try:
			site = frappe.get_doc("Space Site", s)
			bench_client.backup_site(site.server, site.domain)
			ok_count += 1
		except Exception:
			pass
	result = "Passed" if ok_count else "Failed"
	if ok_count and ok_count < len(sites[:20]):
		result = "Partial"
	plan.last_test_at = now_datetime()
	plan.last_test_result = result
	plan.test_notes = f"Backed up {ok_count}/{len(sites[:20])} sites (cross-region restore is manual hook)"
	plan.status = "Active"
	plan.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "result": result, "backed_up": ok_count}


def _is_eligible_target(server: str) -> bool:
	return server_pool._is_eligible(server)


def _same_physical_bench(a: str, b: str) -> bool:
	"""Treat same docker backend container / host as same bench."""
	fa = frappe.db.get_value("Space Server", a, ["ip_address", "backend_container"], as_dict=True) or {}
	fb = frappe.db.get_value("Space Server", b, ["ip_address", "backend_container"], as_dict=True) or {}
	return (fa.get("ip_address"), fa.get("backend_container")) == (fb.get("ip_address"), fb.get("backend_container"))
