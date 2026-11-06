"""Customer backup download: the database backup of the caller's own site, as a file.

Frappe's `type=download` response carries the bytes, so the size is capped; larger archives stay an admin /
support job. The path is rebuilt from the site, never taken from the caller, and must resolve inside that
site's own private/backups folder.
"""

from __future__ import annotations

import os

import frappe
from frappe import _

from space.services import audit
from space_cloud.api.v1.space import _ensure_site_access

MAX_BYTES = 200 * 1024 * 1024


def _backup_file(backup, site) -> str:
	root = os.path.realpath(os.path.join(frappe.utils.get_bench_path(), "sites", site.domain, "private", "backups"))
	candidate = backup.file_path or ""
	if candidate.startswith("sites/"):
		candidate = os.path.join(frappe.utils.get_bench_path(), candidate)
	path = os.path.realpath(candidate)
	if not path.startswith(root + os.sep) or not path.endswith(".sql.gz") or not os.path.isfile(path):
		frappe.throw(_("This backup file is not available for download."), frappe.PermissionError)
	return path


@frappe.whitelist()
def list_downloadable(site: str):
	"""Database backups of the caller's site that can be downloaded."""
	doc = frappe.get_doc("Space Site", site)
	_ensure_site_access(doc)
	rows = frappe.get_all(
		"Space Backup",
		filters={"site": site, "status": "Succeeded"},
		fields=["name", "backup_type", "file_size_mb", "finished_at", "file_path"],
		order_by="creation desc", limit_page_length=20,
	)
	out = []
	for row in rows:
		path = (row.pop("file_path", "") or "")
		if path.endswith(".sql.gz"):
			out.append(row)
	return {"ok": True, "data": out}


@frappe.whitelist()
def download_backup(backup: str):
	doc = frappe.get_doc("Space Backup", backup)
	site = frappe.get_doc("Space Site", doc.site)
	_ensure_site_access(site)
	if doc.status != "Succeeded":
		frappe.throw(_("This backup is not ready."), frappe.PermissionError)
	path = _backup_file(doc, site)
	if os.path.getsize(path) > MAX_BYTES:
		frappe.throw(_("This backup is too large to download here. Contact support."), frappe.PermissionError)
	audit.log_audit("backup_download", ref_doctype="Space Backup", ref_name=backup)
	with open(path, "rb") as fh:
		frappe.local.response.filecontent = fh.read()
	frappe.local.response.filename = os.path.basename(path)
	frappe.local.response.type = "download"
