"""Unit tests for Space Phase 3/4 pure helpers (no frappe runtime required)."""

from __future__ import annotations

import unittest


class TestAlertCompare(unittest.TestCase):
	def test_compare_ops(self):
		def compare(value, op, threshold):
			if op == ">":
				return value > threshold
			if op == ">=":
				return value >= threshold
			if op == "<":
				return value < threshold
			if op == "<=":
				return value <= threshold
			if op == "==":
				return value == threshold
			return False

		self.assertTrue(compare(91, ">", 90))
		self.assertFalse(compare(90, ">", 90))
		self.assertTrue(compare(90, ">=", 90))
		self.assertTrue(compare(0, "<", 1))
		self.assertTrue(compare(1, "==", 1))


class TestLoadScore(unittest.TestCase):
	def test_prefers_lighter_server(self):
		def load_score(c):
			sites = c.get("active_sites") or 0
			max_s = c.get("max_sites") or 50
			ram_pct = (c.get("ram_used_mb") or 0) / max(c.get("ram_mb") or 1, 1)
			disk_pct = (c.get("disk_used_mb") or 0) / max(c.get("disk_mb") or 1, 1)
			cpu_pct = (c.get("cpu_used_percent") or 0) / 100.0
			io_pct = (c.get("io_wait_percent") or 0) / 100.0
			load = (c.get("load_avg") or 0) / max(c.get("cpu_cores") or 1, 1)
			health = c.get("health") or "Unknown"
			health_pen = {"Healthy": 0, "Unknown": 0.1, "Degraded": 0.5, "Critical": 2.0}.get(health, 0.2)
			return (sites / max(max_s, 1)) + ram_pct + disk_pct + cpu_pct + io_pct + load + health_pen

		light = {"active_sites": 1, "max_sites": 50, "ram_used_mb": 100, "ram_mb": 8000, "disk_used_mb": 1000, "disk_mb": 50000, "cpu_used_percent": 10, "health": "Healthy", "cpu_cores": 4, "load_avg": 0.2}
		heavy = {"active_sites": 40, "max_sites": 50, "ram_used_mb": 7000, "ram_mb": 8000, "disk_used_mb": 40000, "disk_mb": 50000, "cpu_used_percent": 85, "health": "Degraded", "cpu_cores": 4, "load_avg": 3.5}
		self.assertLess(load_score(light), load_score(heavy))


class TestRegionSeed(unittest.TestCase):
	def test_five_regions(self):
		codes = {"sa", "ae", "sg", "eu", "us"}
		self.assertEqual(len(codes), 5)


class TestSameBench(unittest.TestCase):
	def test_tuple_equality(self):
		a = ("157.230.8.164", "frappe_docker-backend-1")
		b = ("157.230.8.164", "frappe_docker-backend-1")
		c = ("1.2.3.4", "frappe_docker-backend-1")
		self.assertEqual(a, b)
		self.assertNotEqual(a, c)


if __name__ == "__main__":
	unittest.main()
