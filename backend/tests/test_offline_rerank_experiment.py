import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_enriched_candidates(date_count=6, rows_per_date=12):
    rows = []
    dates = pd.date_range("2026-01-02", periods=date_count, freq="B").strftime("%Y-%m-%d")
    for date in dates:
        for idx in range(rows_per_date):
            strong = idx >= rows_per_date - 3
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"600{idx:03d}",
                    "name": f"样本{idx}",
                    "rank_no": idx + 1,
                    "score": 100.0 - idx,
                    "strong_10d": strong,
                    "return_10d_pct": 9.0 if strong else -2.0,
                    "return_20d_pct": 20.0 if strong else -5.0,
                    "tradability_status": "tradable",
                    "incomplete_horizons": "[]",
                    "has_60d_lookback": True,
                    "return_60d_rank": idx / (rows_per_date - 1),
                    "return_20d_rank": idx / (rows_per_date - 1),
                    "amount_pct_rank": (rows_per_date - 1 - idx) / (rows_per_date - 1),
                    "macd_hist": float(idx),
                    "rsi": 45.0 + idx,
                }
            )
    return pd.DataFrame(rows)


class OfflineRerankExperimentTests(unittest.TestCase):
    def test_fixed_rerank_rules_use_only_pre_signal_feature_columns(self):
        from app.evaluation.offline_rerank_experiment import run_offline_rerank_experiment

        summary = run_offline_rerank_experiment(
            make_enriched_candidates(),
            horizon=10,
            train_ratio=0.5,
            round_trip_cost_pct=0.2,
        )

        self.assertEqual(summary["status"], "completed")
        self.assertFalse(summary["production_evidence"])
        self.assertFalse(summary["strategy_impact"])
        self.assertIn(summary["selected_rule"]["name"], summary["rules"])
        self.assertNotIn("return_10d_pct", summary["feature_columns_used"])
        self.assertNotIn("return_20d_pct", summary["feature_columns_used"])
        self.assertNotIn("strong_10d", summary["feature_columns_used"])
        self.assertGreater(
            summary["rules"]["return_60d_rank_desc"]["test"]["precision_at_5"],
            summary["rules"]["current_smartstock_rank"]["test"]["precision_at_5"],
        )
        self.assertGreater(
            summary["rules"]["combo_trend_macd"]["test"]["top5_return_after_cost"],
            summary["rules"]["current_smartstock_rank"]["test"]["top5_return_after_cost"],
        )

    def test_walk_forward_split_is_chronological_and_non_overlapping(self):
        from app.evaluation.offline_rerank_experiment import run_offline_rerank_experiment

        summary = run_offline_rerank_experiment(make_enriched_candidates(date_count=7), train_ratio=0.57)
        train_dates = summary["split"]["train_dates"]
        test_dates = summary["split"]["test_dates"]

        self.assertTrue(train_dates)
        self.assertTrue(test_dates)
        self.assertLess(max(train_dates), min(test_dates))
        self.assertFalse(set(train_dates).intersection(test_dates))
        self.assertEqual(summary["selected_rule"]["selected_from"], "train")

    def test_insufficient_walk_forward_sample_does_not_promote_production_evidence(self):
        from app.evaluation.offline_rerank_experiment import run_offline_rerank_experiment

        summary = run_offline_rerank_experiment(make_enriched_candidates(date_count=3), min_total_dates=4)

        self.assertEqual(summary["status"], "insufficient_sample")
        self.assertEqual(summary["decision"]["outcome"], "insufficient_walk_forward_sample")
        self.assertFalse(summary["production_evidence"])
        self.assertEqual(summary["decision"]["production_action"], "do_not_change_strategy")

    def test_custom_rule_using_forward_label_column_is_blocked(self):
        from app.evaluation.offline_rerank_experiment import run_offline_rerank_experiment

        summary = run_offline_rerank_experiment(
            make_enriched_candidates(),
            rules={
                "leaky_future_return": {
                    "kind": "column",
                    "column": "return_10d_pct",
                    "direction": "desc",
                    "feature_columns": ["return_10d_pct"],
                }
            },
        )

        self.assertEqual(summary["rules"]["leaky_future_return"]["status"], "blocked")
        self.assertEqual(summary["rules"]["leaky_future_return"]["missing_reason"], "forbidden_forward_feature_return_10d_pct")
        self.assertIn("return_10d_pct", summary["forbidden_forward_columns"])

    def test_artifact_writer_outputs_json_csv_and_markdown(self):
        from app.evaluation.offline_rerank_experiment import (
            run_offline_rerank_experiment,
            write_offline_rerank_artifacts,
        )

        summary = run_offline_rerank_experiment(make_enriched_candidates())

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_offline_rerank_artifacts(summary, tmp)
            self.assertTrue(Path(paths["summary"]).exists())
            self.assertTrue(Path(paths["rule_summary"]).exists())
            self.assertTrue(Path(paths["daily_metrics"]).exists())
            self.assertTrue(Path(paths["report"]).exists())
            payload = json.loads(Path(paths["summary"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["audit_type"], "offline_rerank_experiment")

    def test_cli_writes_offline_rerank_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature_path = root / "candidate_features.csv"
            output_dir = root / "out"
            make_enriched_candidates().to_csv(feature_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_offline_rerank_experiment.py"),
                    "--candidate-features-csv",
                    str(feature_path),
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
            self.assertTrue((output_dir / "offline_rerank_experiment.json").exists())
            self.assertTrue((output_dir / "offline_rerank_rule_summary.csv").exists())
            self.assertIn("offline_rerank_experiment_completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
