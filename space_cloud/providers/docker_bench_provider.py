"""Docker Bench provider driver registered with Space core."""

from __future__ import annotations

from typing import Any

import frappe

from space_cloud.services import bench_client, server_pool


class DockerBenchProvider:
	"""Provider type key: docker_bench."""

	provider_type = "docker_bench"

	def __init__(self, provider_name: str | None = None, server_name: str | None = None):
		self.provider_name = provider_name
		self.server_name = server_name

	def connect(self) -> dict[str, Any]:
		server = self._server()
		return bench_client.test_server_connection(server)

	def health_check(self) -> dict[str, Any]:
		from space_cloud.jobs.monitoring import refresh_server_health

		server = self._server()
		return refresh_server_health(server)

	def capacity_check(self) -> dict[str, Any]:
		return server_pool.capacity_summary()

	def _server(self) -> str:
		if self.server_name:
			return self.server_name
		if self.provider_name and frappe.db.exists("Space Provider", self.provider_name):
			prov = frappe.get_doc("Space Provider", self.provider_name)
			# Prefer linked default server via config / title match
			cfg = {}
			try:
				import json

				cfg = json.loads(prov.config_json or "{}")
			except Exception:
				cfg = {}
			if cfg.get("server"):
				return cfg["server"]
		server = bench_client.get_server()
		return server.name
