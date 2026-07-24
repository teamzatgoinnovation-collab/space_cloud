# Copyright (c) 2026, ZatGo Innovation and contributors
# License: MIT

import frappe
from frappe.model.document import Document


class SpaceSite(Document):
	def before_insert(self):
		from space_cloud.utils.site_naming import build_domain, validate_slug
		validate_slug(self.site_name)
		self.domain = build_domain(self.site_name)
		if not self.status:
			self.status = "Draft"

	def validate(self):
		from space_cloud.utils.site_naming import build_domain, validate_slug
		if self.site_name:
			validate_slug(self.site_name)
			self.domain = build_domain(self.site_name)

	def on_trash(self):
		doctypes_to_clean = [
			"Space Deployment Job",
			"Space Backup",
			"Space Domain",
			"Space Alert",
			"Space Observability Log",
			"Space Metric Snapshot",
			"Space Meter Snapshot",
			"Space Volume",
			"Space IP Allow List",
			"Space App Install History",
			"Space Migration History",
			"Space Site Migration",
			"Space Update Queue",
		]
		for dt in doctypes_to_clean:
			frappe.db.delete(dt, {"site": self.name})

	@frappe.whitelist()
	def create_site(self):
		from space_cloud.jobs.provision import enqueue_create_site
		return enqueue_create_site(self.name)

	@frappe.whitelist()
	def suspend_site(self):
		from space_cloud.jobs.lifecycle import enqueue_suspend_site
		return enqueue_suspend_site(self.name)

	@frappe.whitelist()
	def resume_site(self):
		from space_cloud.jobs.lifecycle import enqueue_resume_site
		return enqueue_resume_site(self.name)

	@frappe.whitelist()
	def delete_site(self):
		from space_cloud.jobs.lifecycle import enqueue_delete_site
		return enqueue_delete_site(self.name)

	@frappe.whitelist()
	def backup_now(self):
		from space_cloud.jobs.backup import enqueue_backup
		return enqueue_backup(self.name, backup_type="Manual")

	@frappe.whitelist()
	def open_site(self):
		return {"url": f"https://{self.domain}"}
