"""Backfill: give every existing Space Server a Hosting Pool (Space Storage Pool)
so capacity/allocated/available accounting works without manual setup."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "Space Storage Pool") or not frappe.db.exists("DocType", "Space Server"):
		return

	from space_cloud.services import hosting_pool

	for server_name in frappe.get_all("Space Server", pluck="name"):
		try:
			hosting_pool.ensure_pool_for_server(server_name)
		except Exception:
			frappe.log_error(title=f"Space hosting pool backfill failed: {server_name}")

	hosting_pool.recompute_all_pools()
