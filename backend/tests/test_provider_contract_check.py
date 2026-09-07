import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd

from app.evaluation.provider_contract_check import compare_field_stages, build_verified_replay, load_verified_capture
from app.services.data_source_manager import DataSourceManager
from app.services.tushare_service import TuShareService


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_provider_field_contracts.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("provider_contract_probe", SCRIPT_PATH)
provider_contract_probe = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(provider_contract_probe)


FIELD_MAP = {
    "turnover_rate": {
        "raw": "turnover_rate",
        "adapted": "turnover_rate",
        "normalized": "turnover_rate",
        "source": "tushare.daily_basic",
        "unit": "percent",
        "multiplier": 1,
    },
    "volume_ratio": {
        "raw": "volume_ratio",
        "adapted": "volume_ratio",
        "normalized": "volume_ratio",
        "source": "tushare.daily_basic",
        "unit": "unitless",
        "multiplier": 1,
    },
    "circ_mv": {
        "raw": "circ_mv",
        "adapted": "circ_mv",
        "normalized": "circ_mv",
        "source": "tushare.daily_basic",
        "unit": "yuan",
        "multiplier": 10000,
    },
}


def record(symbol="000651", trade_date="20260720", **values):
    return {"symbol": symbol, "trade_date": trade_date, "values": values}


def captures_fixture(status="ok", empty=False):
    captures = []
    for day in provider_contract_probe.DATES:
        for endpoint in provider_contract_probe.TUSHARE_FIELDS:
            values = {
                "daily": {"open": 10, "high": 12, "low": 9, "close": 11, "pre_close": 10,
                          "pct_chg": 10, "vol": 2, "amount": 3},
                "daily_basic": {"turnover_rate": 0, "turnover_rate_f": 2, "volume_ratio": 1.5, "circ_mv": 4},
                "adj_factor": {"adj_factor": 2},
            }[endpoint]
            captures.append({"source": "tushare", "endpoint": endpoint, "trade_date": day,
                             "status": status, "rows": [] if empty else [dict(values, ts_code=symbol, trade_date=day)
                                                                         for symbol in provider_contract_probe.SYMBOLS]})
    return captures


def write_capture(root, captures):
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, capture in enumerate(captures):
        path = root / f"raw-{index}.json"
        path.write_text(json.dumps(capture), encoding="utf-8")
        entries.append({"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (root / "request-manifest.json").write_text(json.dumps({"raw_files": entries}), encoding="utf-8")
    return entries


class ProviderContractCheckTests(unittest.TestCase):
    def test_circ_mv_requires_declared_conversion(self):
        rows = [record(circ_mv=4)]
        result = compare_field_stages(rows, rows, rows, {"circ_mv": FIELD_MAP["circ_mv"]})
        self.assertEqual(result["rows"][0]["fields"]["circ_mv"]["status"], "invalid")

    def test_missing_in_all_stages_never_counts_as_retained(self):
        rows = [record()]
        result = compare_field_stages(rows, rows, rows, {"turnover_rate": FIELD_MAP["turnover_rate"]})
        self.assertEqual(result["coverage"]["tushare.daily_basic"]["retained"], 0)

    def test_missing_becomes_zero_only_at_normalizer(self):
        result = compare_field_stages([record()], [record()], [record(turnover_rate=0)],
                                      {"turnover_rate": FIELD_MAP["turnover_rate"]})
        self.assertEqual(result["rows"][0]["fields"]["turnover_rate"]["status"], "missing_coerced_to_zero")

    def test_unknown_unit_cannot_be_compared(self):
        rows = [record(turnover_rate=4)]
        field = dict(FIELD_MAP["turnover_rate"], unit="unknown")
        result = compare_field_stages(rows, rows, rows, {"turnover_rate": field})
        self.assertEqual(result["rows"][0]["fields"]["turnover_rate"]["status"], "not_comparable")

    def test_all_endpoints_unavailable_is_partial_without_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captures = [{"source": "tushare", "endpoint": endpoint, "trade_date": day,
                         "status": "unavailable", "rows": []}
                        for day in provider_contract_probe.DATES for endpoint in provider_contract_probe.TUSHARE_FIELDS]
            write_capture(root, captures)
            with patch("requests.Session.request", side_effect=AssertionError("network forbidden")), \
                    patch("tushare.pro_api", side_effect=AssertionError("SDK forbidden")):
                result = provider_contract_probe.replay_probe(root, root / "replay")
            self.assertEqual(result["status"], "partial")

    def test_missing_raw_value_coerced_to_zero_is_reported(self):
        result = compare_field_stages(
            [record(turnover_rate=None)],
            [record(turnover_rate=0)],
            [record(turnover_rate=0)],
            {"turnover_rate": FIELD_MAP["turnover_rate"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["turnover_rate"]["status"], "missing_coerced_to_zero")
        self.assertEqual(result["coverage"]["tushare.daily_basic"]["denominator"], 1)

    def test_adapted_field_dropped_by_normalizer_is_reported(self):
        result = compare_field_stages(
            [record(volume_ratio=1.5)],
            [record(volume_ratio=1.5)],
            [record()],
            {"volume_ratio": FIELD_MAP["volume_ratio"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["volume_ratio"]["status"], "field_dropped")

    def test_raw_field_dropped_by_adapter_is_reported(self):
        result = compare_field_stages(
            [record(volume_ratio=1.5)],
            [record()],
            [record()],
            {"volume_ratio": FIELD_MAP["volume_ratio"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["volume_ratio"]["status"], "field_dropped")

    def test_multiplier_is_applied_once_and_is_explicit(self):
        result = compare_field_stages(
            [record(circ_mv=4)],
            [record(circ_mv=40000)],
            [record(circ_mv=40000)],
            {"circ_mv": FIELD_MAP["circ_mv"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["circ_mv"]["status"], "unit_converted")

    def test_duplicate_identity_hard_fails_instead_of_deduplicating(self):
        duplicate = [record(turnover_rate=1), record(turnover_rate=2)]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compare_field_stages(duplicate, [], [], {"turnover_rate": FIELD_MAP["turnover_rate"]})

    def test_unknown_date_is_not_compared_as_if_it_were_historical(self):
        result = compare_field_stages(
            [record(trade_date=None, turnover_rate=1)],
            [record(trade_date=None, turnover_rate=1)],
            [record(trade_date=None, turnover_rate=1)],
            {"turnover_rate": FIELD_MAP["turnover_rate"]},
        )

        self.assertEqual(result["rows"][0]["fields"]["turnover_rate"]["status"], "not_comparable")

    def test_unavailable_source_keeps_coverage_rate_null(self):
        result = compare_field_stages([], [], [], {"turnover_rate": FIELD_MAP["turnover_rate"]})

        stats = result["coverage"]["tushare.daily_basic"]
        self.assertEqual(stats["denominator"], 0)
        self.assertIsNone(stats["rate"])
        self.assertIsNone(stats["fields"]["turnover_rate"]["raw"]["numeric_available_rate"])

    def test_tushare_realtime_adapter_only_requests_daily_and_coerces_basic_fields(self):
        class FakePro:
            def __init__(self):
                self.daily_calls = 0

            def stock_basic(self, **_kwargs):
                return pd.DataFrame([{"name": "格力电器"}])

            def daily(self, **_kwargs):
                self.daily_calls += 1
                return pd.DataFrame([{
                    "trade_date": "20260720", "close": 10, "pre_close": 9,
                    "pct_chg": 11.11, "high": 10, "low": 9, "open": 9.5,
                    "vol": 2, "amount": 3,
                }])

        service = object.__new__(TuShareService)
        service._cache = {}
        service._cache_ttl = 60
        service.pro = FakePro()
        quote = service.get_realtime_quote("000651.SZ")

        self.assertEqual(service.pro.daily_calls, 1)
        self.assertEqual(quote["turnover_rate"], 0.0)
        self.assertEqual(quote["circ_mv"], 0.0)

    def test_realtime_normalizer_drops_unmapped_basic_fields(self):
        manager = object.__new__(DataSourceManager)
        normalized = manager._normalize_realtime_quote({
            "code": "000651",
            "price": 10,
            "turnover_rate": 2,
            "turnover_rate_f": 3,
            "volume_ratio": 1.5,
            "circ_mv": 40000,
        }, "000651")

        self.assertEqual(normalized["turnover_rate"], 2)
        self.assertNotIn("turnover_rate_f", normalized)
        self.assertNotIn("volume_ratio", normalized)
        self.assertNotIn("circ_mv", normalized)

    def test_verified_replay_refuses_tampered_raw_capture_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "capture"
            raw_dir = input_dir / "raw"
            raw_dir.mkdir(parents=True)
            raw_path = raw_dir / "daily.json"
            raw_path.write_text(json.dumps(captures_fixture()[0]), encoding="utf-8")
            digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            (input_dir / "request-manifest.json").write_text(json.dumps({
                "raw_files": [{"path": "raw/daily.json", "sha256": digest}],
            }), encoding="utf-8")

            result = build_verified_replay(input_dir, root / "replay", FIELD_MAP, provider_contract_probe.analyze_captures)
            self.assertTrue((root / "replay" / "stage-diff.json").is_file())
            self.assertEqual(result["coverage"]["tushare.daily_basic"]["rate"], None)
            with self.assertRaisesRegex(FileExistsError, "output"):
                build_verified_replay(input_dir, root / "replay", FIELD_MAP, provider_contract_probe.analyze_captures)

            raw_path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sha256"):
                build_verified_replay(input_dir, root / "tampered", FIELD_MAP, provider_contract_probe.analyze_captures)

    def test_probe_adapter_keeps_each_symbol_on_its_own_daily_row(self):
        adapted, normalized = provider_contract_probe._adapter_rows([
            {
                "ts_code": "000001.SZ", "trade_date": "20260720", "close": 10,
                "pre_close": 9, "pct_chg": 1, "high": 11, "low": 9,
                "open": 9.5, "vol": 2, "amount": 3,
            },
            {
                "ts_code": "000651.SZ", "trade_date": "20260720", "close": 40,
                "pre_close": 39, "pct_chg": 1, "high": 41, "low": 39,
                "open": 39.5, "vol": 4, "amount": 5,
            },
        ], "20260720")

        self.assertEqual({row["symbol"]: row["values"]["price"] for row in adapted}, {
            "000001": 10.0,
            "000651": 40.0,
        })
        self.assertEqual({row["symbol"]: row["values"]["price"] for row in normalized}, {
            "000001": 10.0,
            "000651": 40.0,
        })

    def test_probe_cache_replay_uses_only_verified_raw_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "probe"
            raw_files = []
            for day in provider_contract_probe.DATES:
                endpoint_rows = {
                    "daily": [{
                        "ts_code": "000651.SZ", "trade_date": day, "close": 40,
                        "pre_close": 39, "pct_chg": 1, "high": 41, "low": 39,
                        "open": 39.5, "vol": 4, "amount": 5,
                    }],
                    "daily_basic": [{
                        "ts_code": "000651.SZ", "trade_date": day, "turnover_rate": 1,
                        "turnover_rate_f": 2, "volume_ratio": 1.5, "circ_mv": 3,
                    }],
                    "adj_factor": [{"ts_code": "000651.SZ", "trade_date": day, "adj_factor": 2}],
                }
                for endpoint, rows in endpoint_rows.items():
                    path = input_dir / "raw" / day / f"tushare-{endpoint}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({
                        "source": "tushare", "endpoint": endpoint, "trade_date": day, "rows": rows,
                    }), encoding="utf-8")
                    raw_files.append({
                        "path": str(path.relative_to(input_dir)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    })
            (input_dir / "request-manifest.json").write_text(json.dumps({"raw_files": raw_files}), encoding="utf-8")

            result = provider_contract_probe.replay_probe(input_dir, root / "replay")

            self.assertEqual(result["status"], "partial")
            replay_manifest = json.loads((root / "replay" / "replay-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(replay_manifest["transport"], "none")
            self.assertEqual(replay_manifest["raw_file_count"], 6)

    def test_numeric_edges_and_cross_dates(self):
        for raw, adapted, normalized, expected in (
                (4, 40000, 400000000, "invalid"), (4, 0, 0, "invalid"),
                (float("nan"), 4, 4, "invalid"), (True, 1, 1, "invalid"),
                (None, None, None, "missing")):
            with self.subTest(raw=raw, adapted=adapted):
                result = compare_field_stages([record(circ_mv=raw)], [record(circ_mv=adapted)],
                                              [record(circ_mv=normalized)], {"circ_mv": FIELD_MAP["circ_mv"]})
                self.assertEqual(result["rows"][0]["fields"]["circ_mv"]["status"], expected)
        result = compare_field_stages([record(turnover_rate=1)],
                                      [record(trade_date="20260721", turnover_rate=1)], [],
                                      {"turnover_rate": FIELD_MAP["turnover_rate"]})
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(all(row["fields"]["turnover_rate"]["status"] == "unmatched_identity" for row in result["rows"]))

    def test_cli_partial_empty_and_missing_symbol_and_source_failures(self):
        variants = [captures_fixture("unavailable", True), captures_fixture("ok", True), captures_fixture()]
        variants[-1][0]["rows"].pop()
        for captures in variants:
            with self.subTest(captures=captures[0]["status"]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_capture(root, captures)
                with patch("requests.Session.request", side_effect=AssertionError("network forbidden")), \
                        patch("tushare.pro_api", side_effect=AssertionError("SDK forbidden")):
                    code = provider_contract_probe.main(["--mode", "cache-only", "--input-dir", str(root), "--output-dir", str(root / "out")])
                self.assertEqual(code, 2)
                manifest = json.loads((root / "out/replay-manifest.json").read_text())
                self.assertTrue(manifest["replay_completed"])
                self.assertEqual(manifest["capture_status"], "partial")
                self.assertIn("akshare", {item["source"] for item in manifest["statuses"]})

    def test_cli_rejects_duplicate_identity_endpoint_wrong_date_before_output(self):
        for case in ("identity", "endpoint", "date", "reference", "hash", "traversal", "symlink"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "input"
                captures = captures_fixture()
                if case == "identity":
                    captures[0]["rows"].append(captures[0]["rows"][0])
                elif case == "endpoint":
                    captures.append(captures[0])
                elif case == "date":
                    captures[0]["rows"][0]["trade_date"] = "20260721"
                entries = write_capture(root, captures)
                if case == "reference":
                    entries.append(entries[0])
                elif case == "hash":
                    entries[0]["sha256"] = "0" * 64
                elif case in {"traversal", "symlink"}:
                    outside = root.parent / "outside.json"
                    outside.write_bytes((root / entries[0]["path"]).read_bytes())
                    if case == "symlink":
                        (root / "link.json").symlink_to(outside)
                        entries[0]["path"] = "link.json"
                    else:
                        entries[0]["path"] = "../outside.json"
                (root / "request-manifest.json").write_text(json.dumps({"raw_files": entries}))
                with patch("requests.Session.request", side_effect=AssertionError("network forbidden")), \
                        patch("tushare.pro_api", side_effect=AssertionError("SDK forbidden")):
                    self.assertEqual(provider_contract_probe.main(["--mode", "cache-only", "--input-dir", str(root),
                                                                  "--output-dir", str(root / "out")]), 1)
                self.assertFalse((root / "out").exists())

    def test_source_without_response_has_zero_observation_denominator(self):
        captures = captures_fixture()
        for item in captures:
            if item["endpoint"] == "daily_basic":
                item.update(status="unavailable", rows=[])
        result = provider_contract_probe.analyze_captures(captures, provider_contract_probe.FIELD_MAP)
        stats = result["coverage"]["tushare.daily_basic"]
        self.assertEqual(stats["denominator"], 0)
        self.assertEqual(stats["expected_rows"], 6)
        self.assertIsNone(stats["fields"]["circ_mv"]["raw"]["missing_rate"])

    def test_complete_capture_is_distinct_from_field_loss(self):
        captures = captures_fixture() + [
            {"source": "tencent", "status": "ok", "rows": [{"code": symbol} for symbol in provider_contract_probe.PLAIN_SYMBOLS]},
            {"source": "akshare", "status": "ok", "rows": [{"代码": symbol} for symbol in provider_contract_probe.PLAIN_SYMBOLS]}]
        result = provider_contract_probe.analyze_captures(captures, provider_contract_probe.FIELD_MAP)
        self.assertEqual(result["capture_status"], "complete")
        self.assertEqual(result["contract_status"], "issues_detected")


if __name__ == "__main__":
    unittest.main()
