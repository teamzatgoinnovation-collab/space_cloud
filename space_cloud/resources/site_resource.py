"""Site resource lifecycle handlers registered with Space core."""

from __future__ import annotations

import frappe

from space_cloud.jobs.lifecycle import enqueue_delete_site, enqueue_resume_site, enqueue_suspend_site
from space_cloud.jobs.provision import enqueue_create_site


def create(site_name: str) -> dict:
	return enqueue_create_site(site_name)


def suspend(site_name: str) -> dict:
	return enqueue_suspend_site(site_name)


def resume(site_name: str) -> dict:
	return enqueue_resume_site(site_name)


def delete(site_name: str) -> dict:
	return enqueue_delete_site(site_name)


def get(site_name: str) -> dict:
	doc = frappe.get_doc("Space Site", site_name)
	return doc.as_dict()
