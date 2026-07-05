import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.local_ml_v2 import V2_FEATURE_NAMES
from app.evaluation.local_ml_v2_1 import (
    V21_LABELS,
    build_v21_experiment_grid,
    feature_names_for_group,
    summarize_v21_results,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_sample_frame():
    rows = []
    dates = pd.date_range("2026-01-01", periods=140, freq="D").strftime("%Y-%m-%d")
    for day_idx, date in enumerate(dates):
        for symbol_idx in range(30):
            label = 1 if symbol_idx >= 27 else 0
            row = {
                "date": date,
                "symbol": f"600{symbol_idx:03d}",
                "name": f"样本{symbol_idx}",
                "future_return_10d_pct": 6.0 if label else -1.0,
                "label_rank_top10_10d": label,
                "label_alpha_top20_10d": 1 if symbol_idx >= 24 else 0,
                "label_trade_quality_10d": 1 if symbol_idx >= 28 else 0,
                "label_tp_before_sl_10d": 1 if symbol_idx >= 25 else 0,
            }
            for feature in V2_FEATURE_NAMES:
                row[feature] = float(symbol_idx + day_idx * 0.01)
            rows.append(row)
    return pd.DataFrame(rows)


class LocalMLV21ExperimentTests(unittest.TestCase):
    def test_experiment_grid_covers_labels_feature_groups_weights_and_seeds(self):
        grid = build_v21_experiment_grid(
            labels=["label_rank_top10_10d", "label_trade_quality_10d"],
            feature_groups=["v2_full", "v2_no_redundant"],
            weight_modes=["none", "date_stock_balanced"],
            stock_holdout_seeds=[1, 2],
        )

        self.assertEqual(len(grid), 16)
        self.assertEqual({item["label_col"] for item in grid}, {"label_rank_top10_10d", "label_trade_quality_10d"})
        self.assertEqual({item["feature_group"] for item in grid}, {"v2_full", "v2_no_redundant"})
        self.assertEqual({item["sample_weight_mode"] for item in grid}, {"none", "date_stock_balanced"})
        self.assertEqual({item["stock_holdout_seed"] for item in grid}, {1, 2})

    def test_redundant_feature_group_removes_pairs_from_diagnostics(self):
        reduced = feature_names_for_group("v2_no_redundant", V2_FEATURE_NAMES)

        self.assertNotIn("amount_log", reduced)
        self.assertNotIn("return_60d_pct", reduced)
        self.assertNotIn("volatility_20d", reduced)
        self.assertIn("amount_pct_rank", reduced)
        self.assertIn("return_60d_rank", reduced)
        self.assertIn("atr_14_pct", reduced)

    def test_summary_rejects_production_when_splits_do_not_improve_together(self):
        results = [
            {
                "experiment_id": "a",
                "label_col": "label_rank_top10_10d",
                "feature_group": "v2_full",
                "sample_weight_mode": "none",
                "stock_holdout_seed": 1,
                "best_model": "logistic_baseline",
                "metrics": {
                    "final_holdout": {"precision_at_5": 0.35, "topk_return": 2.0, "ndcg_at_10": 0.3},
                    "stock_holdout": {"precision_at_5": 0.12, "topk_return": -1.0, "ndcg_at_10": 0.12},
                    "walk_forward": {"precision_at_5": 0.18, "topk_return": -0.5, "ndcg_at_10": 0.18},
                },
            }
        ]

        summary = summarize_v21_results(results)

        self.assertFalse(summary["production_ready"])
        self.assertIn("stock_or_walk_forward_return_not_positive", summary["blocking_reasons"])

    def test_summary_prefers_return_positive_experiment_over_high_precision_loss(self):
        results = [
            {
                "experiment_id": "high_precision_loss",
                "label_col": "label_tp_before_sl_10d",
                "feature_group": "v2_full",
                "sample_weight_mode": "none",
                "stock_holdout_seed": 1,
                "best_model": "scorecard_baseline",
                "metrics": {
                    "final_holdout": {"precision_at_5": 0.48, "topk_return": 4.0, "ndcg_at_10": 0.4},
                    "stock_holdout": {"precision_at_5": 0.42, "topk_return": -0.4, "ndcg_at_10": 0.32},
                    "walk_forward": {"precision_at_5": 0.41, "topk_return": -0.2, "ndcg_at_10": 0.33},
                },
            },
            {
                "experiment_id": "lower_precision_profit",
                "label_col": "label_rank_top10_10d",
                "feature_group": "v2_no_redundant",
                "sample_weight_mode": "none",
                "stock_holdout_seed": 2,
                "best_model": "decision_tree_shallow",
                "metrics": {
                    "final_holdout": {"precision_at_5": 0.35, "topk_return": 4.4, "ndcg_at_10": 0.3},
                    "stock_holdout": {"precision_at_5": 0.20, "topk_return": 1.1, "ndcg_at_10": 0.2},
                    "walk_forward": {"precision_at_5": 0.21, "topk_return": 1.0, "ndcg_at_10": 0.21},
                },
            },
        ]

        summary = summarize_v21_results(results)

        self.assertEqual(summary["best_experiment"]["experiment_id"], "lower_precision_profit")

    def test_cli_runs_small_v21_matrix_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_path = root / "samples.csv"
            make_sample_frame().to_csv(sample_path, index=False)
            output_dir = root / "out"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_local_ml_v21_experiment.py"),
                    "--sample-path",
                    str(sample_path),
                    "--output-dir",
                    str(output_dir),
                    "--labels",
                    "label_rank_top10_10d,label_trade_quality_10d",
                    "--feature-groups",
                    "v2_no_redundant",
                    "--weight-modes",
                    "none",
                    "--stock-holdout-seeds",
                    "1",
                    "--max-experiments",
                    "2",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output_dir / "v21_experiment_summary.json").exists())
            self.assertTrue((output_dir / "v21_experiment_summary.md").exists())
            payload = json.loads((output_dir / "v21_experiment_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["experiment_count"], 2)
            self.assertFalse(payload["production_ready"])


if __name__ == "__main__":
    unittest.main()
