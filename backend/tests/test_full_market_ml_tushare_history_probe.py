from __future__ import annotations

from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.probe_full_market_tushare_history import (
    DEFAULT_ENDPOINTS,
    _parse_endpoint_subset,
    main,
    probe_tushare_history,
)


class FakeTuSharePro:
    def query(self, endpoint: str, **kwargs):
        if endpoint == "trade_cal":
            return pd.DataFrame(
                {"cal_date": ["20200102", "20260714"], "is_open": [1, 1]}
            )
        if endpoint == "stock_basic":
            return pd.DataFrame(
                {
                    "ts_code": ["000001.SZ"],
                    "list_status": [kwargs["list_status"]],
                    "list_date": ["19910403"],
                    "delist_date": ["20200101" if kwargs["list_status"] == "D" else None],
                }
            )
        if endpoint == "moneyflow":
            raise RuntimeError("permission denied")
        if endpoint == "suspend_d":
            return pd.DataFrame(columns=["ts_code", "trade_date"])
        trade_date = kwargs.get("trade_date") or kwargs.get("start_date")
        return pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": [trade_date]})


class FullMarketMLTuShareHistoryProbeTests(unittest.TestCase):
    def test_endpoint_subset_preserves_order_and_default(self):
        self.assertEqual(DEFAULT_ENDPOINTS, _parse_endpoint_subset(None))
        self.assertEqual(
            ("moneyflow", "daily_basic", "stk_limit"),
            _parse_endpoint_subset("moneyflow,daily_basic,stk_limit"),
        )

    def test_endpoint_subset_rejects_duplicates_and_unknown_endpoints(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            _parse_endpoint_subset("moneyflow,moneyflow")
        with self.assertRaisesRegex(ValueError, "unknown"):
            _parse_endpoint_subset("moneyflow,not_a_real_endpoint")

    def test_cli_rejects_invalid_endpoint_subset_before_reading_token(self):
        with tempfile.TemporaryDirectory() as root, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(
                [
                    "--start-date",
                    "20240603",
                    "--end-date",
                    "20260710",
                    "--output",
                    str(Path(root) / "probe.json"),
                    "--endpoints",
                    "moneyflow,moneyflow",
                ]
            )

    def test_probe_reports_timestamp_and_coverage_contracts(self):
        report = probe_tushare_history(
            FakeTuSharePro(),
            start_date="20200101",
            end_date="20260714",
            endpoints=("daily", "moneyflow", "suspend_d"),
        )

        daily = report["endpoints"]["daily"]
        self.assertEqual(daily["row_count"], 2)
        self.assertEqual(daily["earliest_date"], "20200102")
        self.assertEqual(daily["latest_date"], "20260714")
        self.assertIn("trade_date", daily["required_timestamp_fields"])
        self.assertTrue(daily["timestamp_contract_satisfied"])
        self.assertEqual(daily["date_coverage"]["requested_count"], 2)
        self.assertEqual(daily["date_coverage"]["returned_count"], 2)
        self.assertEqual(daily["symbol_coverage"]["unique_symbol_count"], 1)

    def test_probe_classifies_invalid_endpoint_separately_from_request_failure(self):
        class InvalidEndpointClient(FakeTuSharePro):
            def query(self, endpoint: str, **kwargs):
                if endpoint == "not_a_real_endpoint":
                    raise RuntimeError("请指定正确的接口名")
                return super().query(endpoint, **kwargs)

        report = probe_tushare_history(
            InvalidEndpointClient(),
            start_date="20240603",
            end_date="20260717",
            endpoints=("not_a_real_endpoint",),
        )

        result = report["endpoints"]["not_a_real_endpoint"]
        self.assertEqual(result["status"], "invalid_endpoint")
        self.assertEqual(result["error_code"], "invalid_endpoint")

    def test_probe_separates_permission_empty_and_freshness(self):
        report = probe_tushare_history(
            FakeTuSharePro(),
            start_date="20200101",
            end_date="20260714",
            endpoints=("daily", "moneyflow", "suspend_d"),
        )

        self.assertEqual(report["open_date_range"], ["20200102", "20260714"])
        self.assertEqual(report["endpoints"]["daily"]["status"], "valid_with_rows")
        self.assertEqual(report["endpoints"]["daily"]["earliest_returned_date"], "20200102")
        self.assertEqual(report["endpoints"]["daily"]["latest_returned_date"], "20260714")
        self.assertEqual(report["endpoints"]["suspend_d"]["status"], "valid_but_empty")
        self.assertEqual(report["endpoints"]["moneyflow"]["status"], "permission_denied")
        self.assertTrue(report["stock_basic"]["historical_intervals_ready"])
        self.assertEqual(report["stock_basic"]["list_status_counts"], {"D": 1, "L": 1, "P": 1})
        self.assertNotIn("token", str(report).lower())

    def test_probe_rejects_endpoint_that_ignores_requested_date(self):
        class ScopeIgnoringClient(FakeTuSharePro):
            def query(self, endpoint: str, **kwargs):
                if endpoint == "suspend_d":
                    return pd.DataFrame(
                        {"ts_code": ["000001.SZ"], "suspend_date": ["19990504"]}
                    )
                return super().query(endpoint, **kwargs)

        report = probe_tushare_history(
            ScopeIgnoringClient(),
            start_date="20200101",
            end_date="20260714",
            endpoints=("suspend_d",),
        )

        self.assertEqual(report["endpoints"]["suspend_d"]["status"], "query_scope_mismatch")
        self.assertEqual(report["endpoints"]["suspend_d"]["earliest_returned_date"], "19990504")


if __name__ == "__main__":
    unittest.main()
