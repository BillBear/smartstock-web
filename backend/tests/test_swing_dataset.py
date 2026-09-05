import copy
import hashlib
import importlib
import importlib.util
import json
import unittest


def daily_row(symbol="000001.SZ", day="20260720", **changes):
    return {"ts_code": symbol, "trade_date": day, "open": 10, "high": 11,
            "low": 9, "close": 10, "pre_close": 9.5, "pct_chg": 5.26,
            "vol": 2, "amount": 3, **changes}


def basic_row(symbol="000001.SZ", day="20260720", **changes):
    return {"ts_code": symbol, "trade_date": day, "turnover_rate": 2,
            "turnover_rate_f": 3, "volume_ratio": 1.5, "circ_mv": 4, **changes}


def factor_row(symbol="000001.SZ", day="20260720", factor=2):
    return {"ts_code": symbol, "trade_date": day, "adj_factor": factor}


class SwingDatasetTests(unittest.TestCase):
    def setUp(self):
        # A missing contract is a failing assertion, not an import-time test crash.
        name = "app.evaluation.swing_dataset"
        self.assertIsNotNone(importlib.util.find_spec(name), "daily input contract is absent")
        self.dataset = importlib.import_module(name)

    def join(self, daily=None, basics=None, factors=None, metadata=None):
        return self.dataset.join_daily_inputs(
            [daily_row()] if daily is None else daily,
            [basic_row()] if basics is None else basics,
            [factor_row()] if factors is None else factors,
            {} if metadata is None else metadata,
        )

    def test_daily_units_dates_and_raw_reference_prices(self):
        raw = daily_row(day="2026-07-20")
        row = self.dataset.normalize_daily_rows([raw], "tushare", "raw")[0]
        self.assertEqual(row["symbol"], "000001")
        self.assertEqual(row["trade_date"], "20260720")
        self.assertEqual(row["volume"], 200)
        self.assertEqual(row["amount"], 3000)
        self.assertEqual(row["pre_close"], 9.5)
        self.assertEqual(row["pct_change"], 5.26)
        self.assertEqual(row["units"]["volume"], "shares")
        self.assertEqual(row["units"]["amount"], "yuan")
        self.assertEqual(row["raw"], raw)
        self.assertEqual(row["adjustment"], "raw")
        self.assertEqual(row["source"], "tushare")
        self.assertIsNone(row["fetched_at"])
        self.assertIsNone(row["available_at"])

    def test_basic_units_and_actual_field_kinds(self):
        row = self.join()["rows"][0]
        self.assertEqual(row["circ_mv"], 40000)
        self.assertEqual(row["turnover_rate"], 2)
        self.assertEqual(row["turnover_rate_f"], 3)
        self.assertEqual(row["volume_ratio"], 1.5)
        self.assertEqual(row["units"]["turnover_rate"], "percent")
        self.assertEqual(row["units"]["volume_ratio"], "unitless")
        self.assertEqual(row["units"]["circ_mv"], "yuan")
        self.assertEqual(row["value_kind"]["turnover_rate"], "actual")
        self.assertEqual(row["quality_status"], "complete")
        self.assertTrue(row["adjusted_input_usable"])

    def test_missing_and_zero_are_distinct_without_proxies(self):
        row = self.join(
            daily=[daily_row(vol=0, amount=None)],
            basics=[basic_row(turnover_rate=0, volume_ratio=None)],
        )["rows"][0]
        self.assertEqual(row["volume"], 0)
        self.assertEqual(row["turnover_rate"], 0)
        self.assertIsNone(row["amount"])
        self.assertIsNone(row["volume_ratio"])
        self.assertEqual(row["value_kind"]["volume_ratio"], "missing")
        self.assertEqual(row["value_kind"]["turnover_rate"], "actual")
        self.assertEqual(row["quality_status"], "incomplete")

    def test_join_uses_symbol_and_date_not_position(self):
        result = self.join(
            daily=[daily_row(), daily_row("600000.SH"), daily_row(day="20260721")],
            basics=[basic_row(day="20260721", circ_mv=8), basic_row("600000.SH", circ_mv=6),
                    basic_row(circ_mv=4)],
            factors=[factor_row(day="20260721", factor=4), factor_row("600000.SH", factor=3),
                     factor_row(factor=2)],
        )
        values = {(row["symbol"], row["trade_date"]): (row["circ_mv"], row["adj_factor"])
                  for row in result["rows"]}
        self.assertEqual(values, {("000001", "20260720"): (40000, 2),
                                  ("600000", "20260720"): (60000, 3),
                                  ("000001", "20260721"): (80000, 4)})

    def test_missing_factors_are_not_usable_adjusted_input(self):
        result = self.join(factors=[factor_row(day="20260721")])
        row = result["rows"][0]
        self.assertIsNone(row["adj_factor"])
        self.assertFalse(row["adjusted_input_usable"])
        self.assertEqual(row["quality_status"], "incomplete")
        self.assertEqual(result["coverage"]["matched"]["factors"], 0)
        self.assertEqual(result["rejected"][0]["reason"], "unmatched_key")

    def test_corporate_action_scale_keeps_raw_prices_and_factor_separate(self):
        result = self.join(
            daily=[daily_row(close=10), daily_row(day="20260721", close=5, pre_close=5, pct_chg=0)],
            basics=[basic_row(), basic_row(day="20260721")],
            factors=[factor_row(factor=1), factor_row(day="20260721", factor=2)],
        )
        before, after = result["rows"]
        self.assertEqual([before["close"], after["close"]], [10, 5])
        self.assertEqual([before["adj_factor"], after["adj_factor"]], [1, 2])
        self.assertEqual(after["close"] * after["adj_factor"] / before["adj_factor"], 10)
        self.assertEqual(after["pre_close"], 5)
        self.assertEqual(after["pct_change"], 0)

    def test_duplicate_keys_hard_fail_in_every_input_even_invalid_rows(self):
        for endpoint in ("daily", "basics", "factors"):
            with self.subTest(endpoint=endpoint):
                rows = {"daily": daily_row(), "basics": basic_row(), "factors": factor_row()}
                first = rows[endpoint]
                second = dict(first, trade_date="2026-07-20")
                if endpoint == "daily":
                    second["close"] = "bad"
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    self.join(**{endpoint: [first, second]})

    def test_normalization_rejects_duplicate_keys(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.dataset.normalize_daily_rows([daily_row(), daily_row()], "tushare", "raw")

    def test_qfq_and_unknown_source_contracts_are_rejected(self):
        for source, adjustment in (("tushare", "qfq"), ("tushare", "hfq"),
                                   ("tencent", "raw"), ("akshare", "raw")):
            with self.subTest(source=source, adjustment=adjustment):
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    self.dataset.normalize_daily_rows([daily_row()], source, adjustment)
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    self.join(metadata={"source": source, "adjustment": adjustment})

    def test_repeated_normalization_and_canonical_join_are_rejected(self):
        normalized = self.dataset.normalize_daily_rows([daily_row()], "tushare", "raw")
        with self.assertRaisesRegex(ValueError, "normalized"):
            self.dataset.normalize_daily_rows(normalized, "tushare", "raw")
        with self.assertRaisesRegex(ValueError, "normalized"):
            self.join(daily=normalized)

    def test_dates_are_calendar_valid_and_only_two_formats_supported(self):
        self.assertEqual(self.dataset.compact_trade_date("2026-07-20"), "20260720")
        self.assertEqual(self.dataset.compact_trade_date("20240229"), "20240229")
        for value in ("20260229", "20261301", "2026-7-20", "2026072", 20260720, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "date"):
                self.dataset.compact_trade_date(value)
        result = self.join(daily=[daily_row(day="20260229")], basics=[], factors=[])
        self.assertEqual(result["rows"], [])
        self.assertIn("date", result["rejected"][0]["reason"])

    def test_invalid_numeric_inputs_are_rejected_not_zeroed(self):
        for value in ("bad", "", "NaN", float("nan"), float("inf"), True, [], -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.dataset.normalize_daily_rows([daily_row(vol=value)], "tushare", "raw")
                result = self.join(daily=[daily_row(vol=value)], basics=[], factors=[])
                self.assertEqual(result["rows"], [])
                self.assertIn("vol", result["rejected"][0]["reason"])

    def test_invalid_supplemental_values_reject_whole_record(self):
        for name, rows in (("basics", [basic_row(circ_mv="NaN")]),
                           ("factors", [factor_row(factor=0)]),
                           ("factors", [factor_row(factor=-2)])):
            with self.subTest(name=name, rows=rows):
                result = self.join(**{name: rows})
                self.assertEqual(result["coverage"]["matched"][name], 0)
                self.assertEqual(result["rejected"][0]["input"], name)
                self.assertEqual(result["rows"][0]["quality_status"], "incomplete")

    def test_unknown_symbols_are_rejected(self):
        result = self.join(daily=[daily_row(symbol="000001"), daily_row(symbol="ABC.US")],
                           basics=[], factors=[])
        self.assertEqual(result["rows"], [])
        self.assertEqual(len(result["rejected"]), 2)

    def test_response_and_orphan_hashes_preserve_all_inputs(self):
        basic = [basic_row(), basic_row("600000.SH")]
        factors = [factor_row(), factor_row(day="20260721")]
        result = self.join(basics=basic, factors=factors)
        expected = hashlib.sha256(json.dumps(basic, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(result["provenance"]["response_sha256"]["basics"], expected)
        self.assertEqual(result["coverage"]["received"], {"daily": 1, "basics": 2, "factors": 2})
        self.assertEqual(result["coverage"]["rejected"], {"daily": 0, "basics": 1, "factors": 1})
        self.assertEqual({item["input"] for item in result["rejected"]}, {"basics", "factors"})
        for item in result["rejected"]:
            self.assertEqual(len(item["raw_sha256"]), 64)
            self.assertEqual(item["reason"], "unmatched_key")
        self.assertEqual(result["rows"][0]["raw_inputs"]["daily"], daily_row())
        self.assertEqual(result["rows"][0]["raw_inputs"]["basics"], basic[0])
        self.assertEqual(result["rows"][0]["raw_inputs"]["factors"], factors[0])

    def test_stable_hashes_and_no_input_or_metadata_mutation(self):
        daily, basics, factors = [daily_row()], [basic_row()], [factor_row()]
        metadata = {"fetched_at": "2026-09-05T00:00:00Z", "fallback_chain": ["tushare"]}
        before = copy.deepcopy((daily, basics, factors, metadata))
        first = self.dataset.join_daily_inputs(daily, basics, factors, metadata)
        second = self.dataset.join_daily_inputs(
            [dict(reversed(list(daily[0].items())))], basics, factors, metadata)
        self.assertEqual(first, second)
        self.assertEqual((daily, basics, factors, metadata), before)
        first["rows"][0]["raw_inputs"]["daily"]["close"] = 999
        first["provenance"]["metadata"]["fallback_chain"].append("other")
        self.assertEqual((daily, basics, factors, metadata), before)

    def test_unknown_availability_is_not_invented_from_fetch_time(self):
        row = self.join(metadata={"fetched_at": "2026-09-05T00:00:00Z"})["rows"][0]
        self.assertEqual(row["fetched_at"], "2026-09-05T00:00:00Z")
        self.assertIsNone(row["available_at"])
        self.assertEqual(row["availability_status"], "unknown")
        self.assertIsNone(row["availability_assumption"])

    def test_explicit_availability_assumption_and_fallback_chain_are_preserved(self):
        metadata = {"source": "tushare", "fetched_at": "2026-09-05T00:00:00Z",
                    "available_at": "2026-07-21T09:00:00+08:00",
                    "availability_assumption": "conservative_next_session_input_not_historically_verified",
                    "fallback_chain": [{"source": "tencent", "status": "timeout"},
                                       {"source": "tushare", "status": "ok"}],
                    "endpoints": {"daily": {"source": "tushare", "endpoint": "daily",
                                              "status": "ok", "fields": ["ts_code", "trade_date"]}}}
        result = self.join(metadata=metadata)
        row = result["rows"][0]
        self.assertEqual(row["available_at"], metadata["available_at"])
        self.assertEqual(row["availability_status"], "assumed")
        self.assertEqual(row["availability_assumption"], metadata["availability_assumption"])
        self.assertEqual(result["provenance"]["metadata"], metadata)

    def test_available_at_needs_an_explicit_basis(self):
        with self.assertRaisesRegex(ValueError, "availability"):
            self.join(metadata={"available_at": "2026-07-21T09:00:00+08:00"})

    def test_metadata_rejects_invalid_or_timezone_ambiguous_timestamps(self):
        for field in ("fetched_at", "available_at"):
            for value in ("not-a-date", "2026-07-21", "2026-07-21T09:00:00", 123):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                    self.join(metadata={field: value, "availability_assumption": "fixture assumption"})
        with self.assertRaisesRegex(ValueError, "availability_assumption"):
            self.join(metadata={"availability_assumption": True})

    def test_endpoint_availability_cannot_silently_override_batch_time(self):
        metadata = {"available_at": "2026-07-21T09:00:00+08:00",
                    "availability_assumption": "fixture assumption",
                    "endpoints": {"basics": {"available_at": "2026-07-21T10:00:00+08:00"}}}
        with self.assertRaisesRegex(ValueError, "available_at"):
            self.join(metadata=metadata)

    def test_null_factor_and_missing_optional_reference_fields_stay_missing(self):
        raw = daily_row()
        del raw["pre_close"]
        del raw["pct_chg"]
        row = self.join(daily=[raw], factors=[factor_row(factor=None)])["rows"][0]
        self.assertIsNone(row["pre_close"])
        self.assertIsNone(row["pct_change"])
        self.assertIsNone(row["adj_factor"])
        self.assertFalse(row["adjusted_input_usable"])

    def test_empty_error_timeout_and_permission_responses_are_distinct(self):
        empty = self.join(daily=[], basics=[], factors=[])
        self.assertEqual(empty["rows"], [])
        self.assertEqual(empty["coverage"]["endpoint_status"]["daily"], "empty")
        self.assertEqual(empty["coverage"]["field_coverage"]["close"]["fraction"], None)
        for status in ("error", "timeout", "permission_denied"):
            metadata = {"endpoints": {"daily": {"status": status, "error": "fixture"}}}
            result = self.join(daily=[], basics=[], factors=[], metadata=metadata)
            self.assertEqual(result["coverage"]["endpoint_status"]["daily"], status)
            self.assertEqual(result["provenance"]["metadata"], metadata)

    def test_non_ok_endpoint_cannot_claim_complete_input(self):
        result = self.join(metadata={"endpoints": {"factors": {"status": "partial"}}})
        self.assertEqual(result["rows"][0]["quality_status"], "incomplete")
        self.assertFalse(result["rows"][0]["adjusted_input_usable"])

    def test_endpoint_source_mismatch_and_proxy_claim_are_rejected(self):
        for endpoint in ("daily", "basics", "factors"):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, "unsupported"):
                self.join(metadata={"endpoints": {endpoint: {"source": "tencent"}}})
        with self.assertRaisesRegex(ValueError, "proxy"):
            self.join(basics=[basic_row(value_kind="proxy", formula_version="estimate-v1")])

    def test_coverage_counts_actual_missing_and_factor_completeness(self):
        result = self.join(
            daily=[daily_row(), daily_row(day="20260721")],
            basics=[basic_row(volume_ratio=None)], factors=[factor_row()],
        )
        self.assertEqual(result["coverage"]["daily_rows"], 2)
        self.assertEqual(result["coverage"]["adjusted_input_usable"], 1)
        self.assertEqual(result["coverage"]["field_coverage"]["turnover_rate"],
                         {"actual": 1, "missing": 1, "proxy": 0, "fraction": 0.5})
        self.assertEqual(result["coverage"]["field_coverage"]["volume_ratio"]["missing"], 2)


if __name__ == "__main__":
    unittest.main()
