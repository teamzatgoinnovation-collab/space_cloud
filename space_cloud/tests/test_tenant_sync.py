"""tenant_sync: what the platform pushes into / reads from a customer site. The bench is replaced by a recorder, so
this pins the exact commands (they were verified once against a real bench) and the safety rules around them."""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest import mock

from space_cloud.services import tenant_sync

LIVE = frappe_row = None


def _row(domain="acme.zatgoinnovation.com", status="Active", server="srv1"):
	return mock.Mock(domain=domain, server=server, status=status)


class TestPush(unittest.TestCase):
	def _push(self, row, payload, protected=False):
		calls = []
		with mock.patch.object(tenant_sync, "_site_row", return_value=row), \
				mock.patch.object(tenant_sync, "_protected", return_value=protected), \
				mock.patch.object(tenant_sync.bench_client, "run_on_bench", side_effect=lambda server, argv, **kw: calls.append((server, argv)) or {"stdout": ""}):
			ok = tenant_sync.push_state("acme", payload)
		return ok, calls

	def test_pushes_compact_json_with_parse_flag_and_no_shell(self):
		ok, calls = self._push(_row(), {"enforcement_on": 1, "status": "TRIAL", "trial_ends_at": "2026-12-06T12:00:00+00:00"})
		self.assertTrue(ok)
		server, argv = calls[0]
		self.assertEqual(server, "srv1")
		self.assertEqual(argv[:5], ["bench", "--site", "acme.zatgoinnovation.com", "set-config", "zg_subscription"])
		self.assertEqual(argv[-1], "--parse")
		self.assertEqual(json.loads(argv[5])["status"], "TRIAL")
		self.assertNotIn(" ", argv[5].replace('"trial_ends_at":"2026-12-06T12:00:00+00:00"', ""))  # compact separators

	def test_protected_sites_are_always_told_enforcement_off(self):
		ok, calls = self._push(_row(), {"enforcement_on": 1, "status": "EXPIRED"}, protected=True)
		self.assertTrue(ok)
		self.assertEqual(json.loads(calls[0][1][5])["enforcement_on"], 0)

	def test_sites_that_are_not_live_are_never_touched(self):
		for status in ("Draft", "Provisioning", "Failed", "Deleted"):
			ok, calls = self._push(_row(status=status), {"enforcement_on": 1})
			self.assertFalse(ok, status)
			self.assertEqual(calls, [], status)
		ok, calls = self._push(None, {"enforcement_on": 1})
		self.assertFalse(ok)

	def test_a_hostile_domain_is_refused_before_any_command_is_built(self):
		with self.assertRaises(Exception):
			self._push(_row(domain="a.com; rm -rf /"), {"enforcement_on": 1})

	def test_payload_with_quotes_stays_one_argument(self):
		ok, calls = self._push(_row(), {"enforcement_on": 1, "status": 'TR"IAL; echo hi'})
		argv = calls[0][1]
		self.assertEqual(len(argv), 7)  # bench --site X set-config KEY VALUE --parse
		self.assertEqual(json.loads(argv[5])["status"], 'TR"IAL; echo hi')


class TestReadActivity(unittest.TestCase):
	def _read(self, stdout, row=None):
		with mock.patch.object(tenant_sync, "_site_row", return_value=row or _row()), \
				mock.patch.object(tenant_sync.bench_client, "run_on_bench", return_value={"stdout": stdout}) as run:
			return tenant_sync.get_last_activity("acme"), run

	def test_parses_utc_and_converts_other_offsets(self):
		value, run = self._read('"2026-11-06T12:13:02.563844+00:00"\n')
		self.assertEqual(value, datetime(2026, 11, 6, 12, 13, 2, 563844))
		self.assertEqual(run.call_args[0][1][:5], ["bench", "--site", "acme.zatgoinnovation.com", "execute", "zatgo_core.services.activity.last_human_activity"])
		value, _ = self._read('"2026-11-06T15:00:00+03:00"')
		self.assertEqual(value, datetime(2026, 11, 6, 12, 0, 0))

	def test_nothing_recorded_or_unparseable_output_is_none_not_a_date(self):
		self.assertIsNone(self._read("")[0])
		self.assertIsNone(self._read("Traceback ... no timestamp here")[0])

	def test_sites_that_are_not_live_are_not_read(self):
		for status in ("Draft", "Failed", "Deleted"):
			value, run = self._read('"2026-11-06T12:00:00+00:00"', row=_row(status=status))
			self.assertIsNone(value)
			run.assert_not_called()

	def test_a_bench_failure_propagates_so_the_caller_can_treat_it_as_unknown(self):
		with mock.patch.object(tenant_sync, "_site_row", return_value=_row()), \
				mock.patch.object(tenant_sync.bench_client, "run_on_bench", side_effect=tenant_sync.bench_client.BenchError("boom")):
			with self.assertRaises(tenant_sync.bench_client.BenchError):
				tenant_sync.get_last_activity("acme")


if __name__ == "__main__":
	unittest.main()
