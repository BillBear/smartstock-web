import copy
from datetime import date
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_swing_research_dataset.py"
PROTOCOL = Path(__file__).parent / "fixtures/swing_quality/protocol.json"
DAY = "20260720"


def response(endpoint, day=DAY, count=1):
    row = {"ts_code": "600000.SH", "trade_date": day}
    if endpoint == "daily":
        row.update(open=10, high=11, low=9, close=10, pre_close=10,
                   change=0, pct_chg=0, vol=100, amount=500)
    elif endpoint == "daily_basic":
        row.update(turnover_rate=0, turnover_rate_f=1, volume_ratio=2, circ_mv=50)
    else:
        row.update(adj_factor=1.1)
    return {"code": 0, "msg": None, "data": {
        "fields": list(row), "items": [list(row.values()) for _ in range(count)]}}


class SwingDatasetCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = None
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location("swing_collector", SCRIPT)
            cls.cli = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.cli)

    def setUp(self):
        self.assertIsNotNone(self.cli, "bounded historical collector does not exist")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.protocol = json.loads(PROTOCOL.read_text())
        self.calls = []
        self.days = patch.object(self.cli, "calendar_dates", return_value=[DAY])
        self.days.start()
        self.addCleanup(self.days.stop)

    def fetch(self, endpoint, parameters, fields, timeout):
        self.calls.append((endpoint, parameters, fields, timeout))
        return response(endpoint, parameters["trade_date"])

    def run_collector(self, **kwargs):
        options = dict(protocol=self.protocol, output_dir=self.root / "out",
                       cache_dir=self.root / "cache", fetcher=self.fetch,
                       sleep=lambda _: None, progress=lambda _: None,
                       today=lambda: date(2026, 9, 5))
        options.update(kwargs)
        return self.cli.collect(**options)

    def test_raw_join_compact_dates_and_schema(self):
        result = self.run_collector()
        self.assertEqual(result["status"], "complete")
        self.assertEqual([x[0] for x in self.calls], ["daily", "daily_basic", "adj_factor"])
        for endpoint, params, fields, timeout in self.calls:
            self.assertEqual(params, {"trade_date": DAY})
            self.assertEqual(timeout, 8)
            self.assertIn("ts_code", fields)
        info = result["dates"][DAY]
        data = self.cli.read_json(self.root / "out" / info["output"])
        self.assertEqual(self.cli.digest(data), info["dataset_sha256"])
        self.assertEqual(self.cli.digest(data["coverage"]), info["coverage_sha256"])
        self.assertEqual(data["rows"][0]["volume"], 10000)
        self.assertEqual(data["rows"][0]["circ_mv"], 500000)
        self.assertIsNone(data["rows"][0]["available_at"])
        self.assertEqual(data["role"], "signal")
        self.assertEqual(data["trade_date"], DAY)
        self.assertIn("historical_security_status_unavailable", result["limitations"])

    def test_calendar_request_range_is_fixed_no_weekday_filter(self):
        self.days.stop()
        values = list(self.cli.calendar_dates("2024-01-01", "2026-09-04"))
        self.assertEqual((values[0], values[-1]), ("20240101", "20260904"))
        self.assertIn("20260719", values)
        self.assertIn(DAY, values)
        self.assertEqual(len(values), len(set(values)))

    def test_nan_preserved_as_null_with_archive_count(self):
        def fetch(endpoint, *args):
            payload = response(endpoint)
            if endpoint == "daily_basic":
                payload["data"]["items"][0][4] = float("nan")
            return payload
        result = self.run_collector(fetcher=fetch)
        raw = self.cli.read_json(self.root / "cache" / "requests" / DAY / "daily_basic.json.gz")
        self.assertEqual(raw["nonfinite_to_null_count"], 1)
        self.assertIsNone(raw["payload"]["data"]["items"][0][4])
        data = self.cli.read_json(self.root / "out" / result["dates"][DAY]["output"])
        self.assertIsNone(data["rows"][0]["volume_ratio"])
        self.assertEqual(data["rows"][0]["turnover_rate"], 0)
        self.assertEqual(result["dates"][DAY]["endpoints"]["daily_basic"]["nonfinite_to_null_count"], 1)

    def test_empty_daily_is_unknown_and_skips_supplements(self):
        result = self.run_collector(fetcher=lambda *args: response("daily", count=0))
        self.assertEqual(result["dates"][DAY]["status"], "empty_daily_unknown")
        self.assertEqual(result["new_requests"], 1)
        self.assertNotIn("calendar_closed", json.dumps(result))

    def test_empty_supplement_is_missing_not_request_failure(self):
        result = self.run_collector(fetcher=lambda ep, *args: response(ep, count=0 if ep == "daily_basic" else 1))
        data = self.cli.read_json(self.root / "out" / result["dates"][DAY]["output"])
        self.assertEqual(data["coverage"]["endpoint_status"]["basics"], "empty")
        self.assertIsNone(data["rows"][0]["turnover_rate"])
        self.assertEqual(result["status"], "complete")

    def test_cap_stops_without_unverified_pagination_or_overwrite(self):
        for ep in ("daily", "daily_basic", "adj_factor"):
            with self.subTest(endpoint=ep), tempfile.TemporaryDirectory() as path:
                result = self.run_collector(output_dir=Path(path)/"out", cache_dir=Path(path)/"cache",
                    fetcher=lambda endpoint, *args: response(endpoint, count=6000 if endpoint == ep else 1))
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["stop_reason"], "possible_truncation")
                self.assertEqual(result["new_requests"], ["daily", "daily_basic", "adj_factor"].index(ep)+1)
                self.assertIsNone(result["dates"][DAY]["output"])
                self.assertEqual(result["dates"][DAY]["endpoints"][ep]["row_count"], 6000)
                self.assertEqual(result["dates"][DAY]["endpoints"][ep]["status"], "possible_truncation")

    def test_duplicate_and_wrong_date_hard_fail_without_normalization(self):
        for payload, reason in ((response("daily", count=2), "duplicate_key"),
                                (response("daily", "20260721"), "wrong_date")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as path:
                result = self.run_collector(output_dir=Path(path)/"out", cache_dir=Path(path)/"cache",
                                            fetcher=lambda *args: payload)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["stop_reason"], reason)
                self.assertEqual(result["new_requests"], 1)

    def test_budget_stops_and_resume_fetches_only_missing(self):
        partial = self.run_collector(max_new_requests=2)
        self.assertEqual(partial["status"], "incomplete")
        self.assertEqual(partial["stop_reason"], "request_budget")
        self.assertEqual(partial["identity"]["signal_range"], ["2024-09-01", "2026-08-31"])
        self.calls.clear()
        final = self.run_collector(max_new_requests=1)
        self.assertEqual(final["status"], "complete")
        self.assertEqual([c[0] for c in self.calls], ["adj_factor"])

    def test_cache_only_fresh_output_identical_and_no_network(self):
        original = self.run_collector()
        replay = self.run_collector(output_dir=self.root/"replay", cache_only=True,
                                    fetcher=lambda *args: self.fail("network in cache-only"))
        self.assertEqual(replay["dataset_sha256"], original["dataset_sha256"])
        self.assertEqual(replay["coverage_sha256"], original["coverage_sha256"])
        self.assertEqual(replay["new_requests"], 0)

    def test_cache_only_missing_endpoint_remains_incomplete(self):
        partial = self.run_collector(max_new_requests=1)
        replay = self.run_collector(output_dir=self.root/"replay", cache_only=True,
                                    fetcher=lambda *args: self.fail("network in cache-only"))
        self.assertEqual(replay["status"], "incomplete")
        self.assertEqual(replay["dataset_sha256"], partial["dataset_sha256"])
        self.assertEqual(replay["coverage_sha256"], partial["coverage_sha256"])

    def test_corrupt_cache_and_mutated_payload_fail_checksum(self):
        self.run_collector()
        path = self.root/"cache"/"requests"/DAY/"daily.json.gz"
        raw = self.cli.read_json(path)
        raw["payload"]["data"]["items"][0][2] = 9.5
        path.write_bytes(gzip.compress(json.dumps(raw).encode()))
        result = self.run_collector(cache_only=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "cache_checksum_mismatch")
        path.write_bytes(b"broken gzip")
        result = self.run_collector(cache_only=True)
        self.assertEqual(result["stop_reason"], "corrupt_cache")

    def test_same_immutable_key_different_content_refuses_write(self):
        path = self.root/"immutable.json.gz"
        self.cli.write_immutable(path, {"value": 1})
        before = path.read_bytes()
        self.cli.write_immutable(path, {"value": 1})
        with self.assertRaises(self.cli.CollectionError):
            self.cli.write_immutable(path, {"value": 2})
        self.assertEqual(path.read_bytes(), before)

    def test_changed_protocol_source_or_label_end_refuses_cache_reuse(self):
        self.run_collector(label_end_date="2026-09-04")
        with self.assertRaises(self.cli.CollectionError):
            self.run_collector(label_end_date="2026-09-03")
        altered = copy.deepcopy(self.protocol)
        altered["sources"]["application_head_sha"] = "a"*40
        with self.assertRaises(self.cli.CollectionError):
            self.run_collector(protocol=altered, label_end_date="2026-09-04")
        with self.assertRaises(ValueError):
            self.run_collector(label_end_date="2026-08-30")

    def test_label_end_only_extends_fetch_range_not_signals(self):
        with patch.object(self.cli, "calendar_dates", return_value=["20260904"]):
            result = self.run_collector(label_end_date="2026-09-04")
        self.assertEqual(result["identity"]["label_end_date"], "2026-09-04")
        self.assertEqual(result["identity"]["signal_range"][-1], "2026-08-31")
        data = self.cli.read_json(self.root/"out"/result["dates"]["20260904"]["output"])
        self.assertEqual(data["role"], "label_only")

    def test_uncompleted_or_future_label_dates_are_rejected(self):
        for end in ("2026-09-05", "2026-09-06"):
            with self.subTest(end=end), self.assertRaises(ValueError):
                self.run_collector(label_end_date=end)

    def test_manifest_records_actual_collector_and_normalizer_source_hashes(self):
        import hashlib
        result = self.run_collector()
        hashes = result["identity"]["implementation_sha256"]
        self.assertEqual(hashes["collector"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        normalizer = SCRIPT.parents[1]/"app/evaluation/swing_dataset.py"
        self.assertEqual(hashes["normalizer"], hashlib.sha256(normalizer.read_bytes()).hexdigest())

    def test_permission_quota_and_unknown_errors_stop_not_spray(self):
        for category in ("permission_denied", "quota_exceeded", "provider_error"):
            with self.subTest(category=category), tempfile.TemporaryDirectory() as path:
                def fail(*args):
                    raise self.cli.ProviderError(category, provider_code=2002)
                result = self.run_collector(output_dir=Path(path)/"out", cache_dir=Path(path)/"cache", fetcher=fail)
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["stop_reason"], category)
                self.assertEqual(result["new_requests"], 1)
                self.assertTrue(list((Path(path)/"cache"/"errors").glob("*.json")))

    def test_transport_retry_finite_and_counts_toward_budget(self):
        def fail(*args):
            raise TimeoutError("https://bad.invalid?token=SECRET")
        result = self.run_collector(fetcher=fail)
        self.assertEqual(result["new_requests"], 3)
        self.assertEqual(result["stop_reason"], "timeout")
        self.assertNotIn("SECRET", json.dumps(result))
        for path in (self.root/"cache"/"errors").glob("*.json"):
            self.assertNotIn("SECRET", path.read_text())
        result = self.run_collector(fetcher=fail, max_new_requests=1)
        self.assertEqual(result["new_requests"], 1)
        self.assertEqual(result["stop_reason"], "request_budget")

    def test_request_rate_validation_and_spacing(self):
        for rate in (0, 121):
            with self.assertRaises(ValueError):
                self.run_collector(requests_per_minute=rate)
        waits = []
        result = self.run_collector(sleep=waits.append, monotonic=lambda: 0)
        self.assertEqual(result["new_requests"], 3)
        self.assertEqual(waits, [0.5, 0.5])

    def test_invalid_response_schema_is_blocked_not_empty(self):
        for payload in ({}, {"code": 0, "data": None}, response("daily") | {"code": 2002}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as path:
                result = self.run_collector(output_dir=Path(path)/"out", cache_dir=Path(path)/"cache",
                                            fetcher=lambda *args: payload)
                self.assertNotEqual(result["status"], "complete")
                self.assertNotEqual(result["dates"][DAY]["status"], "empty_daily_unknown")

    def test_provider_error_response_is_archived_but_resumable(self):
        payload = {"code": 2002, "msg": "no permission", "data": None}
        result = self.run_collector(fetcher=lambda *args: payload)
        errors = [self.cli.read_json(path) for path in (self.root/"cache"/"errors").glob("*.json")]
        self.assertEqual(errors[0]["response_archive"]["payload"], payload)
        self.assertEqual(errors[0]["response_archive"]["payload_sha256"], self.cli.digest(payload))
        self.assertEqual(errors[0]["response_archive"]["parameters"], {"trade_date": DAY})
        self.assertEqual(result["stop_reason"], "permission_denied")
        resumed = self.run_collector()
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(resumed["new_requests"], 3)

    def test_https_adapter_rejects_redirects_and_http_error_not_empty(self):
        import requests
        with patch.dict(os.environ, {"TUSHARE_TOKEN": "PRIVATE_TOKEN"}):
            fetch = self.cli.make_fetcher(None)
        for status in (302, 403, 429, 500):
            reply = Mock(status_code=status)
            reply.json.return_value = {"message": "PRIVATE_TOKEN https://unsafe.invalid?token=OTHER"}
            with self.subTest(status=status), patch.object(requests, "post", return_value=reply) as post:
                with self.assertRaises(self.cli.ProviderError) as caught:
                    fetch("daily", {"trade_date": DAY}, "ts_code,trade_date", 8)
                self.assertEqual(caught.exception.http_status, status)
                self.assertNotIn("PRIVATE_TOKEN", json.dumps(caught.exception.payload))
                self.assertNotIn("OTHER", json.dumps(caught.exception.payload))
                self.assertEqual(post.call_args.args[0], "https://api.tushare.pro")
                self.assertFalse(post.call_args.kwargs["allow_redirects"])
                self.assertEqual(post.call_args.kwargs["timeout"], 8)

    def test_provider_error_http_payload_and_timestamp_remain_visible(self):
        def fail(*args):
            raise self.cli.ProviderError("http_error", http_status=500, payload={"error": "unavailable"})
        result = self.run_collector(fetcher=fail)
        record = self.cli.read_json(self.root/"cache"/result["errors"][0]["error_file"])
        self.assertEqual(record["response_archive"]["payload"], {"error": "unavailable"})
        self.assertEqual(record["response_archive"]["http_status"], 500)
        self.assertIn("elapsed_seconds", record["response_archive"])

    def test_https_scalar_json_is_archived_as_invalid_not_uncaught(self):
        import requests
        with patch.dict(os.environ, {"TUSHARE_TOKEN": "PRIVATE_TOKEN"}):
            fetch = self.cli.make_fetcher(None)
        reply = Mock(status_code=200)
        reply.json.return_value = None
        with patch.object(requests, "post", return_value=reply):
            result = self.run_collector(fetcher=fetch)
        self.assertEqual(result["stop_reason"], "invalid_response_schema")
        self.assertEqual(result["status"], "blocked")

    def test_endpoint_field_schema_cannot_omit_requested_values(self):
        malformed = response("daily")
        malformed["data"]["fields"].pop()
        malformed["data"]["items"][0].pop()
        result = self.run_collector(fetcher=lambda *args: malformed)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "invalid_response_fields")

    def test_cache_contract_mutation_even_with_recomputed_hash_fails(self):
        self.run_collector()
        path = self.root/"cache"/"requests"/DAY/"daily.json.gz"
        raw = self.cli.read_json(path)
        raw["source"] = "other"
        raw.pop("archive_sha256")
        raw["archive_sha256"] = self.cli.digest(raw)
        path.write_bytes(gzip.compress(json.dumps(raw).encode()))
        result = self.run_collector(cache_only=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "cache_contract_mismatch")

    def test_cli_cache_only_needs_no_token_sdk_or_production_imports(self):
        completed = subprocess.run([sys.executable, str(SCRIPT), "--protocol", str(PROTOCOL),
            "--output-dir", str(self.root/"cli"), "--cache-only"], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        manifest = json.loads((self.root/"cli"/"manifest.json").read_text())
        self.assertEqual(manifest["new_requests"], 0)
        self.assertEqual(manifest["status"], "incomplete")
        text = SCRIPT.read_text()
        for forbidden in ("app.services", "app.main", "stock_basic(", "trade_cal(", "create_engine", "tushare"):
            if forbidden == "tushare":
                self.assertNotIn("import tushare", text)
            else:
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
