"""Site quota computation — reads only already-cached Space Site/Space Plan
fields (populated by space_cloud.jobs.monitoring's hourly/daily scans), no
remote calls here, safe to run on every API read."""

from __future__ import annotations

import frappe

WARNING_PERCENT = 80.0
CRITICAL_PERCENT = 95.0


def _status_for_percent(percent: float | None) -> str:
	if percent is None:
		return "Healthy"
	if percent >= CRITICAL_PERCENT:
		return "Critical"
	if percent >= WARNING_PERCENT:
		return "Warning"
	return "Healthy"


def _dimension(used: float, limit: float) -> dict:
	if not limit:
		return {"used": used, "limit": None, "remaining": None, "percent": None, "status": "Healthy"}
	percent = round(100.0 * used / limit, 2)
	return {
		"used": used,
		"limit": limit,
		"remaining": max(0.0, limit - used),
		"percent": percent,
		"status": _status_for_percent(percent),
	}


_STATUS_RANK = {"Healthy": 0, "Warning": 1, "Critical": 2}


def compute_site_quota(site: str) -> dict:
	row = frappe.db.get_value(
		"Space Site",
		site,
		["storage_used_mb", "site_user_count", "site_company_count", "plan"],
		as_dict=True,
	)
	if not row:
		frappe.throw(f"Space Site not found: {site}")

	plan = (
		frappe.db.get_value("Space Plan", row.plan, ["storage_mb", "max_users", "max_companies"], as_dict=True)
		if row.plan
		else None
	) or {}

	dims = {
		"storage": _dimension(row.storage_used_mb or 0, plan.get("storage_mb") or 0),
		"users": _dimension(row.site_user_count or 0, plan.get("max_users") or 0),
		"companies": _dimension(row.site_company_count or 0, plan.get("max_companies") or 0),
	}
	overall = max(dims.values(), key=lambda d: _STATUS_RANK[d["status"]])["status"]
	return {"site": site, "plan": row.plan, **dims, "overall_status": overall}


def compute_fleet_quota_summary() -> list[dict]:
	sites = frappe.get_all(
		"Space Site",
		filters={"status": ("!=", "Deleted")},
		fields=["name", "domain", "storage_used_mb", "site_user_count", "site_company_count", "plan"],
	)
	plans = {
		p.name: p
		for p in frappe.get_all("Space Plan", fields=["name", "storage_mb", "max_users", "max_companies"])
	}

	out = []
	for s in sites:
		plan = plans.get(s.plan) or {}
		dims = {
			"storage": _dimension(s.storage_used_mb or 0, plan.get("storage_mb") or 0),
			"users": _dimension(s.site_user_count or 0, plan.get("max_users") or 0),
			"companies": _dimension(s.site_company_count or 0, plan.get("max_companies") or 0),
		}
		overall = max(dims.values(), key=lambda d: _STATUS_RANK[d["status"]])["status"]
		# Sites list only needs the headline number — storage is the dimension users care about day-to-day.
		out.append(
			{
				"site": s.name,
				"domain": s.domain,
				"quota_percent": dims["storage"]["percent"],
				"status": overall,
			}
		)
	return out
