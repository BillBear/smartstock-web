import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.local_ml_v2_2_adjusted import (
    V22_ADJUSTED_FEATURE_NAMES,
    evaluate_v22_dataset_quality,
    prepare_v22_adjusted_dataset,
    run_v22_adjusted_experiment,
    validate_v22_split_integrity,
)
from app.evaluation.ml_splits import build_ml_split_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_candidate_panel(date_count: int = 90, symbol_count: int = 24) -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-01-02", periods=date_count, freq="D").strftime("%Y-%m-%d")
    for day_idx, date in enumerate(dates):
        for symbol_idx in range(symbol_count):
            base_signal = symbol_idx / max(1, symbol_count - 1)
            is_strong = int(symbol_idx >= symbol_count - 5)
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"{600000 + symbol_idx}.SH",
                    "name": f"样本{symbol_idx}",
                    "rank_no": symbol_idx + 1,
                    "score": round(50 + base_signal * 40, 4),
                    "strong_10d": is_strong,
                    "return_10d_pct": round(6.0 + base_signal * 8.0 + day_idx * 0.01, 4) if is_strong else round(-3.0 + base_signal, 4),
                    "return_60d_rank": round(base_signal, 6),
                    "return_20d_rank": round(base_signal * 0.8, 6),
                    "future_return_10d_pct": round(6.0 + base_signal * 8.0, 4) if is_strong else round(-3.0 + base_signal, 4),
                    "label_rank_top10_10d": is_strong,
                }
            )
    return pd.DataFrame(rows)


def make_enhanced_panel(date_count: int = 90, symbol_count: int = 24) -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-01-02", periods=date_count, freq="D").strftime("%Y%m%d")
    for day_idx, date in enumerate(dates):
        for symbol_idx in range(symbol_count):
            base_signal = symbol_idx / max(1, symbol_count - 1)
            rows.append(
                {
                    "trade_date": date,
                    "ts_code": f"{600000 + symbol_idx}.SH",
                    "adj_return_5d_rank": round(base_signal * 0.75 + day_idx * 0.0001, 6),
                    "adj_return_20d_rank": round(base_signal * 0.85 + day_idx * 0.0001, 6),
                    "adj_return_60d_rank": round(base_signal * 0.95 + day_idx * 0.0001, 6),
                    "adj_return_60d_pct": round(base_signal * 30.0, 6),
                    "turnover_rate_rank": round(1.0 - abs(0.65 - base_signal), 6),
                    "volume_ratio_rank": round(0.5 + base_signal * 0.4, 6),
                    "main_net_inflow_ratio_rank": round(0.4 + base_signal * 0.3, 6),
                    "limit_buyability_rank": round(0.9 - base_signal * 0.2, 6),
                }
            )
    return pd.DataFrame(rows)


class LocalMLV22AdjustedExperimentTests(unittest.TestCase):
    def test_prepare_v22_dataset_normalizes_keys_joins_features_and_rejects_forward_features(self):
        dataset, feature_names, report = prepare_v22_adjusted_dataset(
            make_candidate_panel(date_count=12, symbol_count=8),
            make_enhanced_panel(date_count=12, symbol_count=8),
        )

        self.assertIn("date", dataset.columns)
        self.assertTrue(dataset["symbol"].str.len().eq(6).all())
        self.assertIn("adj_return_60d_rank", feature_names)
        self.assertIn("adj_momentum_accel_20_60", feature_names)
        self.assertNotIn("return_10d_pct", feature_names)
        self.assertNotIn("future_return_10d_pct", feature_names)
        self.assertNotIn("strong_10d", feature_names)
        self.assertEqual(report["row_count"], len(dataset))
        self.assertFalse(report["strategy_impact"])
        self.assertFalse(report["production_enabled"])

    def test_quality_gate_blocks_small_dataset_before_training(self):
        dataset, feature_names, _ = prepare_v22_adjusted_dataset(
            make_candidate_panel(date_count=12, symbol_count=8),
            make_enhanced_panel(date_count=12, symbol_count=8),
        )

        quality = evaluate_v22_dataset_quality(
            dataset,
            feature_names,
            "strong_10d",
            "return_10d_pct",
            min_rows=9999,
            min_dates=30,
            min_symbols=100,
        )

        self.assertFalse(quality["ready_for_training"])
        self.assertFalse(quality["production_ready"])
        self.assertIn("row_count_below_minimum", quality["blocking_reasons"])
        self.assertIn("date_count_below_minimum", quality["blocking_reasons"])
        self.assertIn("symbol_count_below_minimum", quality["blocking_reasons"])

    def test_quality_gate_rejects_forbidden_forward_feature_names(self):
        dataset, feature_names, _ = prepare_v22_adjusted_dataset(
            make_candidate_panel(date_count=12, symbol_count=8),
            make_enhanced_panel(date_count=12, symbol_count=8),
        )

        quality = evaluate_v22_dataset_quality(
            dataset,
            [*feature_names, "future_return_10d_pct"],
            "strong_10d",
            "return_10d_pct",
            min_rows=10,
            min_dates=5,
            min_symbols=5,
        )

        self.assertFalse(quality["ready_for_training"])
        self.assertIn("forbidden_feature_leakage", quality["blocking_reasons"])

    def test_split_integrity_requires_time_and_stock_holdout_separation(self):
        dataset, feature_names, _ = prepare_v22_adjusted_dataset(make_candidate_panel(), make_enhanced_panel())
        quality = evaluate_v22_dataset_quality(dataset, feature_names, "strong_10d", "return_10d_pct", min_rows=500, min_dates=50, min_symbols=20)
        self.assertTrue(quality["ready_for_training"], quality["blocking_reasons"])

        split_plan = build_ml_split_plan(
            dataset,
            final_holdout_months=1,
            stock_holdout_ratio=0.20,
            walk_forward_splits=4,
            label_horizon_days=10,
            stock_holdout_seed=7,
        )
        integrity = validate_v22_split_integrity(dataset, split_plan)

        self.assertTrue(integrity["valid"], integrity)
        self.assertEqual(integrity["training_final_date_overlap_count"], 0)
        self.assertEqual(integrity["training_stock_holdout_symbol_overlap_count"], 0)
        self.assertGreater(integrity["walk_forward_window_count"], 0)

    def test_experiment_writes_quality_training_predictions_and_report_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"

            summary = run_v22_adjusted_experiment(
                make_candidate_panel(),
                make_enhanced_panel(),
                output_dir=output_dir,
                min_rows=500,
                min_dates=50,
                min_symbols=20,
                final_holdout_months=1,
                stock_holdout_seed=7,
            )

            self.assertFalse(summary["production_enabled"])
            self.assertFalse(summary["strategy_impact"])
            self.assertEqual(summary["production_action"], "do_not_change_strategy")
            self.assertTrue(summary["quality"]["ready_for_training"], summary["quality"]["blocking_reasons"])
            self.assertIn("training", summary)
            self.assertIn("baseline_metrics", summary)
            self.assertTrue((output_dir / "ml_v22_adjusted_dataset.csv").exists())
            self.assertTrue((output_dir / "ml_v22_adjusted_quality.json").exists())
            self.assertTrue((output_dir / "ml_v22_adjusted_predictions.csv").exists())
            self.assertTrue((output_dir / "ml_v22_adjusted_report.md").exists())

    def test_cli_runs_v22_experiment_and_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = root / "candidate.csv"
            enhanced_path = root / "enhanced.csv"
            output_dir = root / "out"
            make_candidate_panel().to_csv(candidate_path, index=False)
            make_enhanced_panel().to_csv(enhanced_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_local_ml_v22_adjusted_experiment.py"),
                    "--candidate-csv",
                    str(candidate_path),
                    "--enhanced-csv",
                    str(enhanced_path),
                    "--output-dir",
                    str(output_dir),
                    "--min-rows",
                    "500",
                    "--min-dates",
                    "50",
                    "--min-symbols",
                    "20",
                    "--final-holdout-months",
                    "1",
                    "--stock-holdout-seed",
                    "7",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["production_enabled"])
            self.assertTrue((output_dir / "ml_v22_adjusted_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
