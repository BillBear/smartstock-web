import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

    def test_enhanced_feature_audit_allows_ml_gate_only_when_holdout_beats_return_60d_baseline(self):
        from app.evaluation.tushare_enhanced_feature_audit import run_tushare_enhanced_feature_audit

        summary = run_tushare_enhanced_feature_audit(
            make_labeled_enhanced_candidates(enhanced_signal="strong"),
            horizon=10,
            train_ratio=0.5,
            round_trip_cost_pct=0.1,
            min_margin_pct=0.3,
        )

        self.assertEqual(summary["status"], "completed")
        self.assertFalse(summary["production_evidence"])
        self.assertFalse(summary["strategy_impact"])
        self.assertEqual(summary["production_action"], "do_not_change_strategy")
        self.assertEqual(summary["baseline_rule"], "return_60d_rank_desc")
        self.assertTrue(summary["ml_v2_2_gate"]["allowed"])
        self.assertGreaterEqual(summary["ml_v2_2_gate"]["top5_after_cost_margin_pct"], 0.3)
        self.assertGreaterEqual(summary["ml_v2_2_gate"]["candidate_test_ndcg_at_10"], summary["ml_v2_2_gate"]["baseline_test_ndcg_at_10"])

    def test_enhanced_feature_audit_blocks_ml_gate_when_margin_is_not_enough(self):
        from app.evaluation.tushare_enhanced_feature_audit import run_tushare_enhanced_feature_audit

        summary = run_tushare_enhanced_feature_audit(
            make_labeled_enhanced_candidates(enhanced_signal="baseline"),
            horizon=10,
            train_ratio=0.5,
            round_trip_cost_pct=0.1,
            min_margin_pct=0.3,
        )

        self.assertFalse(summary["ml_v2_2_gate"]["allowed"])
        self.assertIn("top5_after_cost_margin_below_required", summary["ml_v2_2_gate"]["blocking_reasons"])

    def test_artifact_writer_outputs_json_csv_and_markdown(self):
        from app.evaluation.tushare_enhanced_feature_audit import (
            run_tushare_enhanced_feature_audit,
            write_tushare_enhanced_feature_artifacts,
        )

        panel = make_labeled_enhanced_candidates(enhanced_signal="strong")
        summary = run_tushare_enhanced_feature_audit(panel, horizon=10, train_ratio=0.5)

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_tushare_enhanced_feature_artifacts(summary, panel, tmp)
            self.assertTrue(Path(paths["summary"]).exists())
            self.assertTrue(Path(paths["feature_panel"]).exists())
            self.assertTrue(Path(paths["rule_summary"]).exists())
            self.assertTrue(Path(paths["report"]).exists())
            payload = json.loads(Path(paths["summary"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["audit_type"], "tushare_enhanced_feature_audit")
            self.assertFalse(payload["production_evidence"])
            self.assertIn("ml_v2_2_gate", payload)

    def test_cli_runs_enhanced_feature_audit_from_csv_panels(self):
        base, daily_basic, adj_factor, stk_limit, suspend, _ = make_tushare_feature_panels()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_path = root / "base.csv"
            daily_basic_path = root / "daily_basic.csv"
            adj_factor_path = root / "adj_factor.csv"
            stk_limit_path = root / "stk_limit.csv"
            suspend_path = root / "suspend.csv"
            output_dir = root / "out"
            base.to_csv(base_path, index=False)
            daily_basic.to_csv(daily_basic_path, index=False)
            adj_factor.to_csv(adj_factor_path, index=False)
            stk_limit.to_csv(stk_limit_path, index=False)
            suspend.to_csv(suspend_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_tushare_enhanced_feature_audit.py"),
                    "--base-panel-csv",
                    str(base_path),
                    "--daily-basic-csv",
                    str(daily_basic_path),
                    "--adj-factor-csv",
                    str(adj_factor_path),
                    "--stk-limit-csv",
                    str(stk_limit_path),
                    "--suspend-csv",
                    str(suspend_path),
                    "--output-dir",
                    str(output_dir),
                    "--horizon",
                    "10",
                    "--train-ratio",
                    "0.5",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output_dir / "tushare_enhanced_feature_audit.json").exists())
            self.assertTrue((output_dir / "tushare_enhanced_feature_panel.csv").exists())
            self.assertIn("tushare_enhanced_feature_audit_completed", result.stdout)


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


def make_labeled_enhanced_candidates(enhanced_signal):
    rows = []
    dates = pd.bdate_range("2026-04-01", periods=6).strftime("%Y-%m-%d")
    for date in dates:
        for idx in range(12):
            symbol = f"600{idx:03d}"
            is_strong = idx >= 9
            if enhanced_signal == "strong":
                enhanced_rank = idx / 11
            else:
                enhanced_rank = (11 - idx) / 11
            rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "name": f"样本{idx}",
                    "rank_no": idx + 1,
                    "score": 100.0 - idx,
                    "strong_10d": is_strong,
                    "return_10d_pct": 9.0 if is_strong else -3.0,
                    "tradability_status": "tradable",
                    "incomplete_horizons": "[]",
                    "has_60d_lookback": True,
                    "return_60d_rank": (11 - idx) / 11,
                    "adj_return_60d_rank": enhanced_rank,
                    "turnover_rate_rank": enhanced_rank,
                    "volume_ratio_rank": enhanced_rank,
                    "distance_to_up_limit_pct": 7.0,
                    "main_net_inflow_ratio_rank": enhanced_rank,
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
