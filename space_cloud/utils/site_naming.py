"""Site naming helpers."""

from __future__ import annotations

import re

import frappe

SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def get_domain_suffix() -> str:
	try:
		return frappe.db.get_single_value("Space Settings", "domain_suffix") or "zatgo.online"
	except Exception:
		return "zatgo.online"


def reserved_slugs() -> set[str]:
	raw = ""
	try:
		raw = frappe.db.get_single_value("Space Settings", "reserved_slugs") or ""
	except Exception:
		pass
	base = {"space", "portal", "erp", "www", "mail", "api", "frontend"}
	extra = {s.strip().lower() for s in raw.replace("\n", ",").split(",") if s.strip()}
	return base | extra


def validate_slug(slug: str) -> str:
	s = (slug or "").strip().lower()
	if not SLUG_RE.match(s):
		frappe.throw("Enter a valid subdomain (lowercase letters, numbers, hyphens)")
	if s in reserved_slugs():
		frappe.throw(f"Subdomain '{s}' is reserved")
	return s


def build_domain(slug: str) -> str:
	s = validate_slug(slug)
	return f"{s}.{get_domain_suffix()}"


REUSABLE_STATUSES = ("Failed", "Deleted")


def archive_stale_site(slug: str, domain: str, customer: str | None) -> bool:
	"""Free `slug` for reuse when its only holder is a Failed/Deleted Space Site
	owned by `customer`. Returns True when the name is now free (nothing there,
	or the stale record was archived), False when it is still taken.

	The old record is renamed, not deleted: ~14 doctypes link to it and
	SpaceSite.on_trash would wipe their history. A Failed site is only
	archived if no bench site by that name actually exists."""
	holders = {
		d.name
		for d in frappe.get_all(
			"Space Site",
			or_filters=[["name", "=", slug], ["domain", "=", domain]],
			fields=["name"],
		)
	}
	if not holders:
		return True
	if len(holders) > 1:
		return False
	name = holders.pop()
	old = frappe.db.get_value(
		"Space Site", name, ["status", "customer", "server", "domain", "subscription"], as_dict=True
	)
	if old.status not in REUSABLE_STATUSES or not customer or old.customer != customer:
		return False
	if old.status == "Failed":
		from space_cloud.services import bench_client

		try:
			if old.domain in bench_client.list_sites(old.server):
				return False
		except Exception:
			# Can't prove the bench site is absent -> keep the name taken.
			return False

	archived = f"{name}-archived-{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}"
	# db_set bypasses validate_slug/build_domain, which would otherwise rewrite
	# the domain straight back; site_name is unique, so it must change first.
	frappe.db.set_value(
		"Space Site", name, {"site_name": archived, "domain": archived}, update_modified=False
	)
	frappe.rename_doc("Space Site", name, archived, force=True)
	if old.subscription and old.status == "Failed":
		frappe.db.set_value(
			"Space Subscription", old.subscription, "status", "Cancelled", update_modified=False
		)
	return True
