import unittest

import pandas as pd

from app.evaluation.local_ml_trainer import train_local_models
from app.evaluation.ml_splits import build_ml_split_plan


def make_training_frame():
    rows = []
    dates = pd.date_range("2025-01-01", periods=80, freq="D").strftime("%Y-%m-%d")
    symbols = [f"600{idx:03d}" for idx in range(12)]
    for date_idx, date in enumerate(dates):
        for symbol_idx, symbol in enumerate(symbols):
            strength = symbol_idx + date_idx * 0.02
            label = 1 if symbol_idx >= 9 else 0
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "feature_strength": strength,
                    "feature_noise": (symbol_idx % 3) - 1,
                    "label_top20_10d": label,
                    "future_return_10d_pct": 8.0 if label else -1.0,
                }
            )
    return pd.DataFrame(rows)


class LocalMLTrainerTests(unittest.TestCase):
    def test_trainer_preserves_final_time_and_stock_holdout_boundaries(self):
        df = make_training_frame()
        split_plan = build_ml_split_plan(df, final_holdout_months=1, stock_holdout_ratio=0.25, walk_forward_splits=3)

        result = train_local_models(
            df,
            feature_names=["feature_strength", "feature_noise"],
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
            split_plan=split_plan,
        )

        split = result["split_summary"]
        self.assertTrue(set(split["training_dates"]).isdisjoint(split["final_holdout_dates"]))
        self.assertTrue(set(split["training_symbols"]).isdisjoint(split["stock_holdout_symbols"]))
        self.assertFalse(result["production_enabled"])

    def test_trainer_runs_required_models_and_reports_metrics(self):
        df = make_training_frame()

        result = train_local_models(
            df,
            feature_names=["feature_strength", "feature_noise"],
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
            split_plan=build_ml_split_plan(df, final_holdout_months=1, stock_holdout_ratio=0.25, walk_forward_splits=3),
        )

        self.assertEqual(result["models"]["logistic_baseline"]["status"], "trained")
        self.assertEqual(result["models"]["sklearn_hist_gradient_boosting"]["status"], "trained")
        self.assertIn(result["models"]["xgboost_classifier"]["status"], {"trained", "skipped"})
        self.assertIn(result["models"]["lightgbm_classifier"]["status"], {"trained", "skipped"})
        metrics = result["models"][result["best_model"]]["final_holdout"]
        self.assertIn("precision_at_3", metrics)
        self.assertIn("precision_at_5", metrics)
        self.assertIn("precision_at_10", metrics)
        self.assertIn("ndcg_at_10", metrics)
        self.assertIn("mrr", metrics)
        self.assertIn("brier", metrics)
        self.assertIn("ece", metrics)
        self.assertIn("topk_return", metrics)
        self.assertTrue(metrics["bucket_hit_rates"])


if __name__ == "__main__":
    unittest.main()
