"""Space API v3 — marketplace, licenses, support, tokens, webhooks, search."""

from __future__ import annotations

import frappe
from frappe import _

from space.api.v1.response import customer_for_user, fail, ok, require_roles
from space_cloud.jobs import marketplace as marketplace_jobs
from space.services import analytics, audit, licenses, rate_limit, search, tokens, webhooks


def _rl():
	rate_limit.check_rate_limit("v3")


def _ensure_site_access(doc, write: bool = False):
	roles = set(frappe.get_roles())
	if frappe.session.user == "Administrator" or roles.intersection(
		{"System Manager", "Space Admin", "Space Operator", "Support Engineer", "Billing Manager"}
	):
		return
	cust = customer_for_user()
	if not cust or doc.customer != cust:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def list_apps(category: str | None = None, featured: int = 0, q: str | None = None):
	_rl()
	filters = {"status": "Published"}
	if category:
		filters["category"] = category
	if int(featured or 0):
		filters["is_featured"] = 1
	rows = frappe.get_all(
		"Space App",
		filters=filters,
		fields=[
			"name",
			"app_name",
			"slug",
			"version",
			"category",
			"developer",
			"description",
			"price",
			"icon",
			"is_featured",
			"downloads",
			"avg_rating",
			"rating_count",
			"compatible_erp_version",
		],
		order_by="is_featured desc, downloads desc, modified desc",
		limit_page_length=100,
	)
	if q:
		ql = q.lower()
		rows = [r for r in rows if ql in (r.app_name or "").lower() or ql in (r.description or "").lower() or ql in (r.slug or "")]
	return ok(rows)


@frappe.whitelist(allow_guest=True)
def get_app(slug: str):
	_rl()
	if not frappe.db.exists("Space App", slug):
		return fail("App not found", "NOT_FOUND", 404)
	doc = frappe.get_doc("Space App", slug)
	if doc.status != "Published" and frappe.session.user == "Guest":
		return fail("App not found", "NOT_FOUND", 404)
	data = doc.as_dict()
	data["screenshots"] = [{"image": s.image, "caption": s.caption} for s in (doc.screenshots or [])]
	data["dependencies"] = [{"app_package": d.app_package, "min_version": d.min_version} for d in (doc.dependencies or [])]
	ratings = frappe.get_all(
		"Space App Rating",
		filters={"app": slug},
		fields=["rating", "comment", "user", "creation"],
		order_by="creation desc",
		limit_page_length=20,
	)
	data["ratings"] = ratings
	return ok(data)


@frappe.whitelist()
def install_app(site: str, app: str):
	_rl()
	doc = frappe.get_doc("Space Site", site)
	_ensure_site_access(doc, write=True)
	with audit.AuditTimer("marketplace_install", api_method="space.api.v3.space.install_app", ref_doctype="Space Site", ref_name=site):
		return ok(marketplace_jobs.enqueue_install_app(site, app))


@frappe.whitelist()
def update_app(site: str, app: str):
	_rl()
	doc = frappe.get_doc("Space Site", site)
	_ensure_site_access(doc, write=True)
	return ok(marketplace_jobs.enqueue_update_app(site, app))


@frappe.whitelist()
def remove_app(site: str, app: str):
	_rl()
	doc = frappe.get_doc("Space Site", site)
	_ensure_site_access(doc, write=True)
	require_roles("Space Admin", "Space Operator", "System Manager", "Space Customer")
	return ok(marketplace_jobs.enqueue_remove_app(site, app))


@frappe.whitelist()
def rebuild_assets(site: str, app: str | None = None):
	_rl()
	doc = frappe.get_doc("Space Site", site)
	_ensure_site_access(doc, write=True)
	require_roles("Space Admin", "Space Operator", "System Manager")
	return ok(marketplace_jobs.enqueue_rebuild_assets(site, app))


@frappe.whitelist()
def rate_app(app: str, rating: int, comment: str | None = None):
	_rl()
	rating = int(rating or 0)
	if rating < 1 or rating > 5:
		return fail("Rating must be 1-5", "INVALID")
	cust = customer_for_user()
	doc = frappe.get_doc(
		{
			"doctype": "Space App Rating",
			"app": app,
			"customer": cust,
			"user": frappe.session.user,
			"rating": rating,
			"comment": comment,
		}
	).insert(ignore_permissions=True)
	# refresh avg
	rows = frappe.get_all("Space App Rating", filters={"app": app}, fields=["rating"])
	if rows:
		avg = sum(float(r.rating or 0) for r in rows) / len(rows)
		frappe.db.set_value("Space App", app, {"avg_rating": round(avg, 2), "rating_count": len(rows)})
	frappe.db.commit()
	return ok(doc.as_dict())


@frappe.whitelist()
def list_install_history(site: str | None = None):
	_rl()
	filters = {}
	if site:
		doc = frappe.get_doc("Space Site", site)
		_ensure_site_access(doc)
		filters["site"] = site
	rows = frappe.get_all(
		"Space App Install History",
		filters=filters,
		fields=["name", "site", "app", "package", "action", "from_version", "to_version", "status", "job", "creation"],
		order_by="creation desc",
		limit_page_length=50,
	)
	return ok(rows)


@frappe.whitelist()
def create_license(customer: str | None = None, plan: str | None = None, site: str | None = None, days: int = 365):
	_rl()
	require_roles("Space Admin", "Billing Manager", "System Manager")
	cust = customer or customer_for_user()
	if not cust:
		return fail("Customer required", "INVALID")
	name = licenses.generate_license(cust, plan=plan, site=site, days=int(days or 365))
	return ok({"name": name})


@frappe.whitelist()
def renew_license(name: str, days: int = 365):
	_rl()
	require_roles("Space Admin", "Billing Manager", "System Manager")
	return ok(licenses.renew_license(name, days=int(days or 365)))


@frappe.whitelist()
def deactivate_license(name: str):
	_rl()
	require_roles("Space Admin", "Billing Manager", "System Manager")
	return ok(licenses.deactivate_license(name))


@frappe.whitelist()
def list_licenses():
	_rl()
	filters = {}
	cust = customer_for_user()
	roles = set(frappe.get_roles())
	if cust and not roles.intersection({"System Manager", "Space Admin", "Billing Manager"}):
		filters["customer"] = cust
	rows = frappe.get_all(
		"Space License",
		filters=filters,
		fields=["name", "license_key", "customer", "plan", "site", "status", "issued_on", "expires_on"],
		order_by="creation desc",
		limit_page_length=100,
	)
	return ok(rows)


@frappe.whitelist()
def create_ticket(subject: str, description: str | None = None, site: str | None = None, category: str | None = None, priority: str = "Medium"):
	_rl()
	cust = customer_for_user()
	if site:
		doc = frappe.get_doc("Space Site", site)
		_ensure_site_access(doc, write=True)
		cust = cust or doc.customer
	ticket = frappe.get_doc(
		{
			"doctype": "Space Support Ticket",
			"subject": subject,
			"description": description,
			"customer": cust,
			"site": site,
			"category": category,
			"priority": priority or "Medium",
			"status": "Open",
			"raised_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return ok(ticket.as_dict())


@frappe.whitelist()
def reply_ticket(ticket: str, message: str, is_internal: int = 0):
	_rl()
	t = frappe.get_doc("Space Support Ticket", ticket)
	if t.site:
		_ensure_site_access(frappe.get_doc("Space Site", t.site), write=True)
	elif t.customer:
		cust = customer_for_user()
		roles = set(frappe.get_roles())
		if cust and t.customer != cust and not roles.intersection({"System Manager", "Space Admin", "Support Engineer"}):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	reply = frappe.get_doc(
		{
			"doctype": "Space Ticket Reply",
			"ticket": ticket,
			"author": frappe.session.user,
			"is_internal": 1 if int(is_internal or 0) else 0,
			"message": message,
		}
	).insert(ignore_permissions=True)
	if t.status == "Open":
		t.status = "In Progress"
		t.save(ignore_permissions=True)
	frappe.db.commit()
	return ok(reply.as_dict())


@frappe.whitelist()
def list_tickets(status: str | None = None):
	_rl()
	filters = {}
	if status:
		filters["status"] = status
	cust = customer_for_user()
	roles = set(frappe.get_roles())
	if cust and not roles.intersection({"System Manager", "Space Admin", "Support Engineer"}):
		filters["customer"] = cust
	rows = frappe.get_all(
		"Space Support Ticket",
		filters=filters,
		fields=["name", "subject", "customer", "site", "category", "priority", "status", "assigned_to", "creation"],
		order_by="modified desc",
		limit_page_length=50,
	)
	return ok(rows)


@frappe.whitelist()
def create_api_token(token_name: str, scopes: str | None = None):
	_rl()
	cust = customer_for_user()
	if not cust:
		require_roles("Space Admin", "System Manager")
		return fail("Customer required", "INVALID")
	return ok(tokens.create_token(cust, token_name, scopes or "sites:read,apps:read"))


@frappe.whitelist()
def revoke_api_token(name: str):
	_rl()
	doc = frappe.get_doc("Space API Token", name)
	cust = customer_for_user()
	roles = set(frappe.get_roles())
	if cust and doc.customer != cust and not roles.intersection({"System Manager", "Space Admin"}):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return ok(tokens.revoke_token(name))


@frappe.whitelist()
def register_webhook(title: str, url: str, events: str, secret: str | None = None):
	_rl()
	cust = customer_for_user()
	doc = frappe.get_doc(
		{
			"doctype": "Space Webhook",
			"title": title,
			"direction": "Outgoing",
			"url": url,
			"events": events,
			"customer": cust,
			"is_active": 1,
			"secret": secret,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return ok({"name": doc.name})


@frappe.whitelist()
def test_webhook(name: str):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Space Customer")
	doc = frappe.get_doc("Space Webhook", name)
	webhooks.dispatch("test", {"webhook": name, "ok": True}, customer=doc.customer)
	return ok({"dispatched": True})


@frappe.whitelist()
def global_search(q: str, limit: int = 20):
	_rl()
	require_roles("Space Admin", "Space Operator", "System Manager", "Support Engineer", "Readonly Auditor")
	return ok(search.global_search(q, limit=int(limit or 20)))


@frappe.whitelist()
def analytics_summary():
	_rl()
	require_roles("Space Admin", "System Manager", "Billing Manager", "Readonly Auditor")
	return ok(analytics.analytics_summary())
