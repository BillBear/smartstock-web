from __future__ import annotations

import unittest

import pandas as pd

from scripts.probe_full_market_tushare_history import probe_tushare_history


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
