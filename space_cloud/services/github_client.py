"""
GitHub client for Bench Manager app discovery.

Lists installable Frappe custom apps from the configured GitHub org's repos,
so the Bench Manager UI can offer a dropdown instead of a free-text repo
URL. Read-only (Contents: Read-only PAT scope expected) — never writes to
GitHub. Mirrors agent_client.py's role as a thin transport module: no
Frappe doc mutation beyond reading Space Settings and the redis cache.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import frappe
import requests

from space_cloud.services.bench_client import PACKAGE_RE

CACHE_KEY_PREFIX = "space_cloud:bench:github_apps"
CACHE_TTL_S = 600
API_VERSION = "2022-11-28"


class GitHubError(Exception):
	pass


def _settings() -> tuple[str, str | None]:
	settings = frappe.get_single("Space Settings")
	org = (settings.github_org or "").strip()
	try:
		pat = settings.get_password("github_pat")
	except Exception:
		pat = None
	return org, (pat or None)


def list_org_apps(force_refresh: bool = False) -> dict[str, Any]:
	"""Frappe custom app repos in the configured GitHub org, ready for the
	Bench Manager install dropdown. Never raises — a bad/missing PAT or a
	GitHub-side failure comes back as {"error": "..."} so it can't break
	the page; callers should render that message rather than fail closed."""
	org, pat = _settings()
	if not org:
		return {"configured": False, "apps": [], "error": "GitHub org is not configured in Space Settings."}
	if not pat:
		return {
			"configured": False,
			"apps": [],
			"error": "GitHub PAT not configured — set it in Space Settings → GitHub Integration.",
		}

	cache_key = f"{CACHE_KEY_PREFIX}:{org}"
	if not force_refresh:
		cached = frappe.cache().get_value(cache_key)
		if cached:
			return cached

	try:
		apps = _fetch_repos(org, pat)
	except GitHubError as e:
		return {"configured": True, "apps": [], "error": str(e)}
	except Exception as e:
		frappe.log_error(title="GitHub app discovery failed", message=frappe.get_traceback())
		return {"configured": True, "apps": [], "error": f"GitHub app discovery failed: {e}"}

	result = {"configured": True, "apps": apps, "error": None}
	frappe.cache().set_value(cache_key, result, expires_in_sec=CACHE_TTL_S)
	return result


def _headers(pat: str) -> dict[str, str]:
	return {
		"Authorization": f"Bearer {pat}",
		"Accept": "application/vnd.github+json",
		"X-GitHub-Api-Version": API_VERSION,
		"User-Agent": "space-cloud-bench-manager",
	}


def _fetch_repos(org: str, pat: str) -> list[dict[str, Any]]:
	session = requests.Session()
	session.headers.update(_headers(pat))
	org_q = urllib.parse.quote(org, safe="")

	repos: list[dict[str, Any]] = []
	page = 1
	while page <= 10:  # safety valve, well past this org's actual repo count
		resp = session.get(
			f"https://api.github.com/orgs/{org_q}/repos",
			params={"per_page": 100, "page": page, "type": "sources"},  # sources = exclude forks
			timeout=10,
		)
		_raise_for_status(resp)
		batch = resp.json()
		repos.extend(batch)
		if len(batch) < 100:
			break
		page += 1

	apps: list[dict[str, Any]] = []
	for repo in repos:
		if repo.get("archived"):
			continue
		repo_name = repo.get("name") or ""
		module = repo_name.replace("-", "_")
		if not PACKAGE_RE.match(module):
			continue
		default_branch = repo.get("default_branch") or "main"
		if not _has_hooks_py(session, org_q, repo_name, module, default_branch):
			continue
		apps.append(
			{
				"package_name": module,
				"repo_name": repo_name,
				"clone_url": repo.get("clone_url"),
				"default_branch": default_branch,
				"html_url": repo.get("html_url"),
			}
		)

	apps.sort(key=lambda a: a["package_name"])
	return apps


def _has_hooks_py(session: requests.Session, org_q: str, repo_name: str, module: str, ref: str) -> bool:
	"""True iff <repo>/<module>/hooks.py exists at `ref` — the structural
	signal that distinguishes a real Frappe app repo from everything else
	in the org (flutter-*, desktop-*, web-*, plain docker-compose repos)."""
	path = urllib.parse.quote(f"{module}/hooks.py", safe="/")
	repo_q = urllib.parse.quote(repo_name, safe="")
	url = f"https://api.github.com/repos/{org_q}/{repo_q}/contents/{path}"
	try:
		resp = session.get(url, params={"ref": ref}, timeout=8)
	except requests.RequestException:
		return False
	return resp.status_code == 200


def _raise_for_status(resp: requests.Response) -> None:
	if resp.status_code == 401:
		raise GitHubError("GitHub PAT is invalid or missing the required scope.")
	if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
		raise GitHubError("GitHub API rate limit reached — try again shortly.")
	if resp.status_code == 404:
		raise GitHubError("GitHub org not found, or the PAT can't see it.")
	if not resp.ok:
		raise GitHubError(f"GitHub API error ({resp.status_code}): {(resp.text or '')[:200]}")
