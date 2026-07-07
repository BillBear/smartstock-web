import unittest

import pandas as pd


class FakeTuShareClient:
    def daily_basic(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260701",
                    "turnover_rate": 2.1,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        raise RuntimeError("permission denied")

    def suspend_d(self, **kwargs):
        return pd.DataFrame()


class TuShareEnhancedFeatureAuditTests(unittest.TestCase):
    def test_endpoint_availability_records_available_error_and_empty_status(self):
        from app.evaluation.tushare_enhanced_feature_audit import audit_tushare_endpoint_availability

        summary = audit_tushare_endpoint_availability(
            FakeTuShareClient(),
            sample_date="2026-07-01",
            endpoints=["daily_basic", "adj_factor", "suspend_d"],
        )

        self.assertEqual(summary["sample_date"], "2026-07-01")
        self.assertEqual(summary["endpoints"]["daily_basic"]["status"], "available")
        self.assertEqual(summary["endpoints"]["daily_basic"]["row_count"], 1)
        self.assertIn("turnover_rate", summary["endpoints"]["daily_basic"]["columns"])
        self.assertEqual(summary["endpoints"]["adj_factor"]["status"], "error")
        self.assertIn("permission denied", summary["endpoints"]["adj_factor"]["error"])
        self.assertEqual(summary["endpoints"]["suspend_d"]["status"], "empty")

    def test_enhanced_feature_panel_merges_tushare_fields_and_computes_pre_signal_features(self):
        from app.evaluation.tushare_enhanced_feature_audit import build_tushare_enhanced_feature_panel

        base, daily_basic, adj_factor, stk_limit, suspend, final_date = make_tushare_feature_panels()

        panel = build_tushare_enhanced_feature_panel(
            base,
            daily_basic_panel=daily_basic,
            adj_factor_panel=adj_factor,
            stk_limit_panel=stk_limit,
            suspend_panel=suspend,
        )

        expected_columns = {
            "turnover_rate_rank",
            "volume_ratio_rank",
            "pe_ttm_rank",
            "pb_rank",
            "circ_mv_rank",
            "adj_close",
            "adj_return_20d_pct",
            "adj_return_60d_pct",
            "adj_return_60d_rank",
            "distance_to_up_limit_pct",
            "distance_to_down_limit_pct",
            "hit_limit_up_today",
            "suspend_risk_flag",
        }
        self.assertTrue(expected_columns.issubset(panel.columns))

        final = panel[panel["trade_date"] == final_date]
        turnover_000001 = final.loc[final["symbol"] == "000001", "turnover_rate_rank"].iloc[0]
        turnover_000002 = final.loc[final["symbol"] == "000002", "turnover_rate_rank"].iloc[0]
        self.assertGreater(turnover_000001, turnover_000002)
        self.assertTrue(final["adj_return_60d_rank"].notna().all())
        self.assertTrue(bool(final.loc[final["symbol"] == "000003", "hit_limit_up_today"].iloc[0]))
        self.assertTrue(bool(final.loc[final["symbol"] == "000002", "suspend_risk_flag"].iloc[0]))


if __name__ == "__main__":
    unittest.main()


def make_tushare_feature_panels(date_count=65):
    dates = pd.bdate_range("2026-01-02", periods=date_count)
    symbols = ["000001.SZ", "000002.SZ", "000003.SZ"]
    base_rows = []
    basic_rows = []
    adj_rows = []
    limit_rows = []
    for day_idx, date in enumerate(dates):
        trade_date = date.strftime("%Y%m%d")
        for symbol_idx, ts_code in enumerate(symbols):
            slope = [0.16, 0.04, 0.10][symbol_idx]
            close = 10.0 + symbol_idx + day_idx * slope
            is_final_limit = ts_code == "000003.SZ" and day_idx == len(dates) - 1
            up_limit = close if is_final_limit else close * 1.10
            down_limit = close * 0.90
            base_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "close": close,
                    "rank_no": symbol_idx + 1,
                    "score": 90.0 - symbol_idx,
                    "strong_10d": symbol_idx == 0,
                    "return_10d_pct": 8.0 - symbol_idx,
                    "tradability_status": "tradable",
                    "incomplete_horizons": "[]",
                    "has_60d_lookback": True,
                    "return_60d_rank": [0.30, 0.20, 0.10][symbol_idx],
                }
            )
            basic_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "turnover_rate": [4.0, 1.0, 2.5][symbol_idx] + day_idx * 0.01,
                    "volume_ratio": [1.8, 0.8, 1.2][symbol_idx],
                    "pe_ttm": [18.0, 40.0, 28.0][symbol_idx],
                    "pb": [1.6, 4.0, 2.2][symbol_idx],
                    "circ_mv": [800000.0, 180000.0, 360000.0][symbol_idx],
                    "total_mv": [1000000.0, 240000.0, 450000.0][symbol_idx],
                }
            )
            adj_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "adj_factor": 1.0 + symbol_idx * 0.05,
                }
            )
            limit_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "up_limit": up_limit,
                    "down_limit": down_limit,
                }
            )
    final_date = dates[-1].strftime("%Y-%m-%d")
    suspend = pd.DataFrame([{"ts_code": "000002.SZ", "trade_date": dates[-1].strftime("%Y%m%d")}])
    return (
        pd.DataFrame(base_rows),
        pd.DataFrame(basic_rows),
        pd.DataFrame(adj_rows),
        pd.DataFrame(limit_rows),
        suspend,
        final_date,
    )
