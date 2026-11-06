"""Platform <-> tenant site: push the subscription state in, read the last human activity out.

Both go through the same bench channel the provisioning code uses (in-process inside the bench container, the
Space Agent otherwise). The state lands in the tenant's `site_config.json` as `zg_subscription`, a file nobody
inside the site can write; zatgo_core's subscription_gate reads it. Reading activity calls zatgo_core's own
`services.activity.last_human_activity`, so the SQL, the "who is a person" rules and the timezone handling live
next to the data. A site that cannot answer returns None -- the caller must treat that as "unknown", never "inactive".
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import frappe

from space_cloud.services import bench_client

ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
LIVE_STATUSES = ("Active", "Suspended")


def _site_row(site: str) -> Any:
	return frappe.db.get_value("Space Site", site, ["domain", "server", "status"], as_dict=True)


def _protected(domain: str) -> bool:
	from space.services import lifecycle as lc

	return domain.lower() in lc.protected_domains()


def push_state(site: str, payload: dict[str, Any]) -> bool:
	"""Write `zg_subscription` into the tenant's site_config. Sites the platform must not restrict (its own,
	protected ones) always get enforcement off."""
	row = _site_row(site)
	if not row or not row.domain or row.status not in LIVE_STATUSES:
		return False
	payload = dict(payload)
	if _protected(row.domain):
		payload["enforcement_on"] = 0
	domain = bench_client._assert_site(row.domain)
	bench_client.run_on_bench(
		row.server,
		["bench", "--site", domain, "set-config", "zg_subscription", json.dumps(payload, separators=(",", ":")), "--parse"],
		timeout_s=60,
	)
	return True


def get_last_activity(site: str) -> datetime | None:
	"""Last human activity on the tenant as naive UTC, or None when unknown or never."""
	row = _site_row(site)
	if not row or not row.domain or row.status not in LIVE_STATUSES:
		return None
	domain = bench_client._assert_site(row.domain)
	r = bench_client.run_on_bench(
		row.server,
		["bench", "--site", domain, "execute", "zatgo_core.services.activity.last_human_activity"],
		timeout_s=90,
	)
	match = ISO.search(r.get("stdout") or "")
	if not match:
		return None
	return datetime.fromisoformat(match.group(0).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
