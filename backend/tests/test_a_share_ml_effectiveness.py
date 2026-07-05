import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AShareMLEffectivenessTests(unittest.TestCase):
    def test_label_specs_do_not_promote_tp_before_sl_as_primary(self):
        from app.evaluation.a_share_ml_effectiveness import LABEL_SPECS

        self.assertFalse(LABEL_SPECS["label_tp_before_sl_10d"]["primary_allowed"])
        self.assertTrue(LABEL_SPECS["label_profit_quality_10d"]["primary_allowed"])

    def test_profit_quality_label_requires_return_excess_drawdown_and_tradability(self):
        from app.evaluation.a_share_ml_effectiveness import build_profit_quality_labels

        frame = pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "symbol": "600001",
                    "future_return_10d_pct": 12.0,
                    "future_excess_return_10d_pct": 8.0,
                    "future_max_drawdown_10d_pct": -3.0,
                    "tradability_flag": True,
                },
                {
                    "date": "2026-01-02",
                    "symbol": "600002",
                    "future_return_10d_pct": 9.0,
                    "future_excess_return_10d_pct": 6.0,
                    "future_max_drawdown_10d_pct": -9.0,
                    "tradability_flag": True,
                },
                {
                    "date": "2026-01-02",
                    "symbol": "600003",
                    "future_return_10d_pct": 10.0,
                    "future_excess_return_10d_pct": 7.0,
                    "future_max_drawdown_10d_pct": -2.0,
                    "tradability_flag": False,
                },
            ]
        )

        labeled = build_profit_quality_labels(frame)

        self.assertEqual(labeled.loc[0, "label_profit_quality_10d"], 1)
        self.assertEqual(labeled.loc[1, "label_profit_quality_10d"], 0)
        self.assertEqual(labeled.loc[2, "label_profit_quality_10d"], 0)

    def test_wave_quality_label_requires_20d_return_drawdown_and_favorable_excursion(self):
        from app.evaluation.a_share_ml_effectiveness import build_profit_quality_labels

        frame = pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "symbol": "600001",
                    "future_return_10d_pct": 1.0,
                    "future_excess_return_10d_pct": 0.0,
                    "future_max_drawdown_10d_pct": -1.0,
                    "future_return_20d_pct": 14.0,
                    "future_max_drawdown_20d_pct": -5.0,
                    "future_max_gain_20d_pct": 14.0,
                    "tradability_flag": True,
                },
                {
                    "date": "2026-01-02",
                    "symbol": "600002",
                    "future_return_10d_pct": 1.0,
                    "future_excess_return_10d_pct": 0.0,
                    "future_max_drawdown_10d_pct": -1.0,
                    "future_return_20d_pct": 12.0,
                    "future_max_drawdown_20d_pct": -12.0,
                    "future_max_gain_20d_pct": 16.0,
                    "tradability_flag": True,
                },
            ]
        )

        labeled = build_profit_quality_labels(frame)

        self.assertEqual(labeled.loc[0, "label_wave_quality_20d"], 1)
        self.assertEqual(labeled.loc[1, "label_wave_quality_20d"], 0)

    def test_present_feature_groups_report_missing_turnover_without_zero_fill(self):
        from app.evaluation.a_share_ml_effectiveness import present_feature_groups

        frame = pd.DataFrame({"amount_log": [1.0], "amount_pct_rank": [0.8], "macd_hist": [0.1], "rsi": [55.0]})

        groups = present_feature_groups(frame)

        self.assertIn("amount_liquidity", groups)
        self.assertGreaterEqual(len(groups["amount_liquidity"]["present"]), 2)
        self.assertIn("turnover_rate", groups["turnover_activity"]["missing"])
        self.assertIn("technical_basic", groups)

    def test_add_a_share_audit_features_builds_amount_windows_and_deltas(self):
        from app.evaluation.a_share_ml_effectiveness import add_a_share_audit_features

        rows = []
        for day in range(25):
            rows.append(
                {
                    "date": f"2026-01-{day + 1:02d}",
                    "symbol": "600001",
                    "close": 10 + day * 0.1,
                    "amount": 100_000_000 + day * 1_000_000,
                    "volume": 10_000_000 + day * 100_000,
                    "turnover_rate": 1.0 + day * 0.05,
                    "macd_hist": day * 0.01,
                    "rsi": 45 + day * 0.2,
                }
            )

        featured = add_a_share_audit_features(pd.DataFrame(rows))

        self.assertIn("amount_ma_3", featured.columns)
        self.assertIn("amount_ratio_3_10", featured.columns)
        self.assertIn("turnover_ratio_5_20", featured.columns)
        self.assertIn("macd_hist_delta_3d", featured.columns)
        self.assertIn("rsi_delta_3d", featured.columns)
        self.assertGreater(featured["amount_ratio_3_10"].iloc[-1], 1.0)

    def test_bucket_diagnostics_find_concentrated_feature_effect(self):
        from app.evaluation.a_share_ml_effectiveness import bucket_feature_quality

        rows = []
        for date in ["2026-01-02", "2026-01-05", "2026-01-06"]:
            for idx in range(20):
                rows.append(
                    {
                        "date": date,
                        "symbol": f"600{idx:03d}",
                        "amount_ratio_5_20": idx / 20,
                        "future_return_10d_pct": 8.0 if idx >= 16 else -1.0,
                        "future_max_drawdown_10d_pct": -2.0,
                        "label_profit_quality_10d": 1 if idx >= 16 else 0,
                    }
                )

        report = bucket_feature_quality(
            pd.DataFrame(rows),
            feature="amount_ratio_5_20",
            label_col="label_profit_quality_10d",
            return_col="future_return_10d_pct",
            quantiles=5,
            round_trip_cost_pct=0.2,
        )

        self.assertEqual(report["feature"], "amount_ratio_5_20")
        self.assertGreater(report["monotonicity_score"], 0)
        self.assertGreater(report["buckets"][-1]["avg_return"], report["buckets"][0]["avg_return"])
        self.assertIn("top5_return_after_cost_when_sorted_by_feature", report)

    def test_market_regime_tags_offensive_defensive_and_liquidity(self):
        from app.evaluation.a_share_ml_effectiveness import add_market_regime_tags

        frame = pd.DataFrame(
            [
                {"date": "2026-01-02", "symbol": "600001", "return_5d_pct": 3.0, "amount_ratio_5_20": 1.3},
                {"date": "2026-01-02", "symbol": "600002", "return_5d_pct": 2.0, "amount_ratio_5_20": 1.2},
                {"date": "2026-01-03", "symbol": "600001", "return_5d_pct": -4.0, "amount_ratio_5_20": 0.7},
                {"date": "2026-01-03", "symbol": "600002", "return_5d_pct": -1.0, "amount_ratio_5_20": 0.8},
            ]
        )

        tagged = add_market_regime_tags(frame)

        self.assertEqual(tagged[tagged["date"] == "2026-01-02"]["market_regime"].iloc[0], "offensive")
        self.assertEqual(tagged[tagged["date"] == "2026-01-03"]["market_regime"].iloc[0], "defensive")
        self.assertEqual(tagged[tagged["date"] == "2026-01-02"]["liquidity_regime"].iloc[0], "liquidity_expansion")
        self.assertEqual(tagged[tagged["date"] == "2026-01-03"]["liquidity_regime"].iloc[0], "liquidity_contraction")

    def test_no_model_baseline_comparison_scores_daily_rankers(self):
        from app.evaluation.a_share_ml_effectiveness import compare_no_model_baselines

        rows = []
        for date in ["2026-01-02", "2026-01-05", "2026-01-06"]:
            for idx in range(30):
                rows.append(
                    {
                        "date": date,
                        "symbol": f"600{idx:03d}",
                        "return_20d_rank": idx / 30,
                        "amount_ratio_5_20": (30 - idx) / 30,
                        "future_return_10d_pct": 10.0 if idx >= 27 else -1.0,
                        "label_profit_quality_10d": 1 if idx >= 27 else 0,
                    }
                )

        report = compare_no_model_baselines(
            pd.DataFrame(rows),
            label_col="label_profit_quality_10d",
            return_col="future_return_10d_pct",
            baselines=["return_20d_rank_desc", "amount_ratio_5_20_desc"],
            round_trip_cost_pct=0.2,
        )

        self.assertGreater(report["return_20d_rank_desc"]["precision_at_5"], report["amount_ratio_5_20_desc"]["precision_at_5"])
        self.assertGreater(report["return_20d_rank_desc"]["top5_return"], 0)
        self.assertLess(report["return_20d_rank_desc"]["top5_return_after_cost"], report["return_20d_rank_desc"]["top5_return"])

    def test_effectiveness_summary_blocks_when_baselines_are_sufficient(self):
        from app.evaluation.a_share_ml_effectiveness import summarize_audit_decision

        decision = summarize_audit_decision(
            {
                "baseline_comparison": {
                    "random_daily_rank": {"top5_return_after_cost": -0.1, "precision_at_5": 0.1},
                    "return_20d_rank_desc": {"top5_return_after_cost": 2.0, "precision_at_5": 0.3},
                },
                "feature_group_quality": {
                    "amount_liquidity": {"best_top5_return_after_cost": 1.5, "accepted": True},
                    "ma_gap_ablation": {"best_top5_return_after_cost": -0.2, "accepted": False},
                },
                "label_quality": {
                    "label_profit_quality_10d": {"accepted": True},
                    "label_tp_before_sl_10d": {"accepted": False},
                },
            }
        )

        self.assertEqual(decision["outcome"], "prefer_rule_baseline_over_ml_for_now")
        self.assertIn("label_profit_quality_10d", decision["allowed_primary_labels"])
        self.assertIn("ma_gap_ablation", decision["feature_groups_blocked"])

    def test_cli_writes_audit_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.csv"
            out = root / "out"
            rows = []
            for day in range(40):
                date = f"2026-01-{(day % 28) + 1:02d}"
                split = "final_holdout" if day >= 30 else "train"
                for idx in range(30):
                    rows.append(
                        {
                            "date": date,
                            "symbol": f"600{idx:03d}",
                            "split": split,
                            "close": 10 + idx,
                            "amount": 100_000_000 + idx * 1_000_000,
                            "volume": 10_000_000,
                            "return_5d_pct": idx / 3,
                            "return_20d_rank": idx / 30,
                            "future_return_10d_pct": 8.0 if idx >= 27 else -1.0,
                            "future_excess_return_10d_pct": 6.0 if idx >= 27 else -1.0,
                            "future_max_drawdown_10d_pct": -3.0,
                            "future_return_20d_pct": 12.0 if idx >= 27 else -2.0,
                            "future_max_drawdown_20d_pct": -5.0,
                            "future_max_gain_20d_pct": 14.0 if idx >= 27 else 1.0,
                            "tradability_flag": True,
                        }
                    )
            pd.DataFrame(rows).to_csv(sample, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_a_share_ml_effectiveness_audit.py"),
                    "--sample-path",
                    str(sample),
                    "--output-dir",
                    str(out),
                    "--label-col",
                    "label_profit_quality_10d",
                    "--return-col",
                    "future_return_10d_pct",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out / "audit_summary.json").exists())
            self.assertTrue((out / "baseline_comparison.csv").exists())
            self.assertTrue((out / "audit_report.md").exists())
            payload = json.loads((out / "audit_summary.json").read_text(encoding="utf-8"))
            self.assertIn("baseline_comparison", payload)
            self.assertIn("decision", payload)


if __name__ == "__main__":
    unittest.main()
