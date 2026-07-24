"""Seed hosting DocTypes: server, regions, clusters, dashboard cards, workspace links."""

from __future__ import annotations

import json

import frappe


DEFAULT_REGIONS = [
	{"region_code": "sa", "title": "Saudi Arabia", "country": "Saudi Arabia"},
	{"region_code": "ae", "title": "UAE", "country": "United Arab Emirates"},
	{"region_code": "sg", "title": "Singapore", "country": "Singapore"},
	{"region_code": "eu", "title": "Europe", "country": "EU"},
	{"region_code": "us", "title": "USA", "country": "United States"},
]

DEFAULT_ALERT_RULES = [
	{"rule_name": "cpu-high", "metric": "CPU", "operator": ">", "threshold": 90, "severity": "Warning", "scope": "Global"},
	{"rule_name": "disk-high", "metric": "Disk", "operator": ">", "threshold": 85, "severity": "Critical", "scope": "Global"},
	{"rule_name": "redis-down", "metric": "Redis", "operator": "<", "threshold": 1, "severity": "Critical", "scope": "Global"},
	{"rule_name": "backup-failures", "metric": "Backup", "operator": ">", "threshold": 0, "severity": "Warning", "scope": "Global"},
	{"rule_name": "deploy-failures", "metric": "Deployment", "operator": ">", "threshold": 0, "severity": "Warning", "scope": "Global"},
]

NUMBER_CARDS = [
	{
		"name": "Space Total Servers",
		"label": "Servers",
		"type": "Document Type",
		"document_type": "Space Server",
		"function": "Count",
		"filters_json": "[]",
	},
	{
		"name": "Space Total Sites",
		"label": "Sites",
		"type": "Document Type",
		"document_type": "Space Site",
		"function": "Count",
		"filters_json": '[["Space Site","status","!=","Deleted"]]',
	},
	{
		"name": "Space Active Sites",
		"label": "Active Sites",
		"type": "Document Type",
		"document_type": "Space Site",
		"function": "Count",
		"filters_json": '[["Space Site","status","=","Active"]]',
	},
	{
		"name": "Space Failed Jobs",
		"label": "Failed Jobs",
		"type": "Document Type",
		"document_type": "Space Deployment Job",
		"function": "Count",
		"filters_json": '[["Space Deployment Job","status","=","Failed"]]',
	},
	{
		"name": "Space Running Jobs",
		"label": "Running Jobs",
		"type": "Document Type",
		"document_type": "Space Deployment Job",
		"function": "Count",
		"filters_json": '[["Space Deployment Job","status","in",["Queued","Running"]]]',
	},
]

EXTRA_LINKS = [
	("Ops", "Card Break", None),
	("Space Backup", "Link", "Space Backup"),
	("Space Domain", "Link", "Space Domain"),
	("Space Metric Snapshot", "Link", "Space Metric Snapshot"),
	("Infrastructure", "Card Break", None),
	("Space Region", "Link", "Space Region"),
	("Space Cluster", "Link", "Space Cluster"),
	("Space Node", "Link", "Space Node"),
	("Space Availability Zone", "Link", "Space Availability Zone"),
	("Space Storage Pool", "Link", "Space Storage Pool"),
	("Space Volume", "Link", "Space Volume"),
	("Space DR Plan", "Link", "Space DR Plan"),
	("Space Alert", "Link", "Space Alert"),
	("Space Alert Rule", "Link", "Space Alert Rule"),
	("Space Maintenance Window", "Link", "Space Maintenance Window"),
	("Space Site Migration", "Link", "Space Site Migration"),
	("Space Secret", "Link", "Space Secret"),
	("Space Firewall Rule", "Link", "Space Firewall Rule"),
	("Space IP Allow List", "Link", "Space IP Allow List"),
	("Space Observability Log", "Link", "Space Observability Log"),
	("Space Capacity Forecast", "Link", "Space Capacity Forecast"),
]


def after_install():
	try:
		_seed_all()
	except Exception:
		frappe.log_error(title="Space Cloud after_install seed failed")


def after_migrate():
	try:
		_seed_all()
	except Exception:
		frappe.log_error(title="Space Cloud after_migrate seed failed")
		frappe.db.rollback()
		try:
			_seed_default_server()
			_link_provider_to_server()
			frappe.db.commit()
		except Exception:
			frappe.log_error(title="Space Cloud after_migrate core seed failed")
			frappe.db.rollback()


def _seed_all():
	_seed_default_server()
	_seed_regions()
	_seed_alert_rules()
	_seed_default_cluster()
	_link_provider_to_server()
	_seed_number_cards()
	_seed_workspace_links()
	_ensure_prefer_server()
	frappe.db.commit()


def _seed_default_server():
	if not frappe.db.exists("DocType", "Space Server"):
		return
	name = "primary-do"
	if frappe.db.exists("Space Server", name):
		return
	frappe.get_doc(
		{
			"doctype": "Space Server",
			"server_name": name,
			"title": "DigitalOcean Primary",
			"ip_address": "157.230.8.164",
			"ssh_user": "root",
			"ssh_port": 22,
			"auth_method": "Private Key",
			"docker_host": "unix:///var/run/docker.sock",
			"backend_container": "frappe_docker-backend-1",
			"cpu_cores": 1,
			"ram_mb": 2048,
			"disk_mb": 49152,
			"max_sites": 50,
			"weight": 1,
			"ssl_mode": "Wildcard",
			"status": "Active",
			"health": "Unknown",
			"is_default": 1,
		}
	).insert(ignore_permissions=True)


def _link_provider_to_server():
	"""Ensure Space Provider config points at primary server."""
	if not frappe.db.exists("DocType", "Space Provider"):
		return
	if not frappe.db.exists("Space Provider", "docker-bench-primary"):
		return
	prov = frappe.get_doc("Space Provider", "docker-bench-primary")
	cfg = {}
	try:
		cfg = json.loads(prov.config_json or "{}")
	except Exception:
		cfg = {}
	if cfg.get("server") != "primary-do":
		cfg["server"] = "primary-do"
		cfg.setdefault("host", "157.230.8.164")
		prov.config_json = json.dumps(cfg)
		prov.save(ignore_permissions=True)


def _ensure_prefer_server():
	if not frappe.db.exists("DocType", "Space Settings"):
		return
	if not frappe.db.exists("Space Server", "primary-do"):
		return
	doc = frappe.get_single("Space Settings")
	if not doc.prefer_server:
		doc.prefer_server = "primary-do"
		doc.save(ignore_permissions=True)


def _seed_regions():
	if not frappe.db.exists("DocType", "Space Region"):
		return
	for r in DEFAULT_REGIONS:
		if frappe.db.exists("Space Region", r["region_code"]):
			continue
		frappe.get_doc({"doctype": "Space Region", **r, "status": "Active"}).insert(ignore_permissions=True)
	if frappe.db.exists("DocType", "Space Availability Zone"):
		for code, region in (("sa-1", "sa"), ("ae-1", "ae"), ("sg-1", "sg"), ("eu-1", "eu"), ("us-1", "us")):
			if frappe.db.exists("Space Availability Zone", code):
				continue
			frappe.get_doc(
				{
					"doctype": "Space Availability Zone",
					"az_code": code,
					"title": f"{region.upper()} AZ1",
					"region": region,
					"status": "Active",
				}
			).insert(ignore_permissions=True)


def _seed_alert_rules():
	if not frappe.db.exists("DocType", "Space Alert Rule"):
		return
	for rule in DEFAULT_ALERT_RULES:
		if frappe.db.exists("Space Alert Rule", rule["rule_name"]):
			continue
		frappe.get_doc({"doctype": "Space Alert Rule", **rule, "is_active": 1, "cooldown_minutes": 30}).insert(
			ignore_permissions=True
		)


def _seed_default_cluster():
	if not frappe.db.exists("DocType", "Space Cluster"):
		return
	if not frappe.db.exists("Space Cluster", "primary-sa"):
		frappe.get_doc(
			{
				"doctype": "Space Cluster",
				"cluster_name": "primary-sa",
				"title": "Primary SA Cluster",
				"region": "sa" if frappe.db.exists("Space Region", "sa") else None,
				"status": "Active",
				"health": "Unknown",
				"role": "Primary",
				"max_sites": 100,
			}
		).insert(ignore_permissions=True)
	if frappe.db.exists("Space Server", "primary-do") and frappe.db.has_column("Space Server", "region"):
		frappe.db.set_value(
			"Space Server",
			"primary-do",
			{"region": "sa", "cluster": "primary-sa", "availability_zone": "sa-1", "ha_role": "Standalone"},
			update_modified=False,
		)
	if frappe.db.exists("DocType", "Space Node") and not frappe.db.exists("Space Node", "node-primary-do"):
		frappe.get_doc(
			{
				"doctype": "Space Node",
				"node_name": "node-primary-do",
				"title": "Primary DO Node",
				"cluster": "primary-sa",
				"server": "primary-do" if frappe.db.exists("Space Server", "primary-do") else None,
				"region": "sa",
				"availability_zone": "sa-1",
				"status": "Active",
				"health": "Unknown",
			}
		).insert(ignore_permissions=True)


def _seed_number_cards():
	if not frappe.db.exists("DocType", "Number Card"):
		return
	card_names = []
	for spec in NUMBER_CARDS:
		wanted = spec["name"]
		if frappe.db.exists("Number Card", wanted):
			doc = frappe.get_doc("Number Card", wanted)
			for k, v in spec.items():
				if k != "name":
					doc.set(k, v)
			doc.is_public = 1
			doc.module = "Space Cloud"
			doc.save(ignore_permissions=True)
			card_names.append(doc.name)
		else:
			doc = frappe.get_doc(
				{
					"doctype": "Number Card",
					**spec,
					"is_public": 1,
					"module": "Space Cloud",
					"show_percentage_stats": 0,
				}
			)
			doc.insert(ignore_permissions=True)
			card_names.append(doc.name)
	frappe.db.commit()

	if not frappe.db.exists("Workspace", "Cloud Manager"):
		return
	ws = frappe.get_doc("Workspace", "Cloud Manager")
	if not ws.get("type"):
		ws.type = "Workspace"
	# Merge cloud cards into workspace (preserve existing)
	existing_nc = {r.number_card_name for r in (ws.number_cards or [])}
	for name in card_names:
		if name not in existing_nc and frappe.db.exists("Number Card", name):
			ws.append("number_cards", {"number_card_name": name, "label": name})
	try:
		content = json.loads(ws.content or "[]")
	except Exception:
		content = []
	# Ensure number_card blocks exist for new cards
	existing_blocks = {
		b.get("data", {}).get("number_card_name")
		for b in content
		if b.get("type") == "number_card"
	}
	nc_blocks = [
		{
			"id": f"nccloud{i}",
			"type": "number_card",
			"data": {"number_card_name": name, "col": 2},
		}
		for i, name in enumerate(card_names)
		if name not in existing_blocks and frappe.db.exists("Number Card", name)
	]
	if nc_blocks:
		if content and content[0].get("type") == "header":
			content = [content[0]] + nc_blocks + content[1:]
		else:
			content = nc_blocks + content
		ws.content = json.dumps(content)
	ws.flags.ignore_links = True
	ws.flags.ignore_mandatory = True
	ws.save(ignore_permissions=True)


def _seed_workspace_links():
	if not frappe.db.exists("Workspace", "Cloud Manager"):
		return
	ws = frappe.get_doc("Workspace", "Cloud Manager")
	existing = {(l.label, l.type) for l in (ws.links or [])}
	changed = False
	# Ensure core hosting links
	for label, typ, link_to in [
		("Sites", "Card Break", None),
		("Space Site", "Link", "Space Site"),
		("Space Deployment Job", "Link", "Space Deployment Job"),
		("Space Customer", "Link", "Space Customer"),
		("Infrastructure", "Card Break", None),
		("Space Server", "Link", "Space Server"),
		("Space Provider", "Link", "Space Provider"),
		("Space Activity Log", "Link", "Space Activity Log"),
		("Billing", "Card Break", None),
		("Space Plan", "Link", "Space Plan"),
		("Space Subscription", "Link", "Space Subscription"),
		("Space Settings", "Link", "Space Settings"),
	] + EXTRA_LINKS:
		if (label, typ) in existing:
			continue
		row = {"label": label, "type": typ, "hidden": 0, "onboard": 0}
		if typ == "Link":
			row.update({"link_type": "DocType", "link_to": link_to})
		elif typ == "Card Break":
			row["link_count"] = 0
		ws.append("links", row)
		changed = True
	if changed:
		ws.flags.ignore_links = True
		ws.save(ignore_permissions=True)
