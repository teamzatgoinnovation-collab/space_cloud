"""Company name/abbreviation helpers for post-provisioning setup."""

from __future__ import annotations

import re

WORD_RE = re.compile(r"[A-Za-z0-9]+")


def default_company_name(site_name: str) -> str:
	slug = (site_name or "").split(".")[0].replace("-", " ").replace("_", " ").strip()
	return slug.title() if slug else "My Company"


def derive_abbr(company_name: str) -> str:
	words = WORD_RE.findall(company_name or "")
	if len(words) > 1:
		abbr = "".join(w[0] for w in words[:5]).upper()
	elif words:
		abbr = words[0][:5].upper()
	else:
		abbr = ""
	return abbr or "CO"
