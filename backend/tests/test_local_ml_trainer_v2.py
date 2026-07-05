import unittest

import pandas as pd

from app.evaluation.local_ml_trainer import daily_ranking_metrics, train_local_models
from app.evaluation.ml_splits import build_ml_split_plan


def make_training_frame():
    rows = []
    dates = pd.date_range("2026-01-01", periods=80, freq="D").strftime("%Y-%m-%d")
    symbols = [f"600{idx:03d}" for idx in range(20)]
    for date_idx, date in enumerate(dates):
        for symbol_idx, symbol in enumerate(symbols):
            label = 1 if symbol_idx >= 15 else 0
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "name": f"样本{symbol_idx}",
                    "feature_strength": float(symbol_idx + date_idx * 0.01),
                    "feature_noise": float((symbol_idx + date_idx) % 4),
                    "label_rank_top10_10d": label,
                    "future_return_10d_pct": 10.0 if label else -1.0,
                }
            )
    return pd.DataFrame(rows)


class LocalMLTrainerV2Tests(unittest.TestCase):
    def test_daily_ranking_metrics_average_each_trading_day_instead_of_global_topk(self):
        scored = pd.DataFrame(
            [
                {"date": "2026-01-01", "label": 1, "return": 5.0, "score": 0.99},
                {"date": "2026-01-01", "label": 1, "return": 4.0, "score": 0.98},
                {"date": "2026-01-01", "label": 1, "return": 3.0, "score": 0.97},
                {"date": "2026-01-02", "label": 0, "return": -2.0, "score": 0.96},
                {"date": "2026-01-02", "label": 0, "return": -1.0, "score": 0.95},
                {"date": "2026-01-02", "label": 1, "return": 6.0, "score": 0.10},
            ]
        )

        metrics = daily_ranking_metrics(scored, label_col="label", score_col="score", return_col="return", date_col="date")

        self.assertEqual(metrics["date_count"], 2)
        self.assertEqual(metrics["precision_at_1"], 0.5)
        self.assertAlmostEqual(metrics["precision_at_3"], 2 / 3, places=6)

    def test_trainer_runs_logistic_decision_tree_and_scorecard_candidates(self):
        df = make_training_frame()
        split_plan = build_ml_split_plan(
            df,
            final_holdout_months=1,
            stock_holdout_ratio=0.2,
            walk_forward_splits=3,
            label_horizon_days=5,
        )

        result = train_local_models(
            df,
            feature_names=["feature_strength", "feature_noise"],
            label_col="label_rank_top10_10d",
            return_col="future_return_10d_pct",
            split_plan=split_plan,
            candidate_set="core_v2",
        )

        self.assertEqual(result["models"]["logistic_baseline"]["status"], "trained")
        self.assertEqual(result["models"]["decision_tree_shallow"]["status"], "trained")
        self.assertEqual(result["models"]["scorecard_baseline"]["status"], "trained")
        best = result["models"][result["best_model"]]
        self.assertIn("date_count", best["final_holdout"])
        self.assertIn("feature_importance", best)
        self.assertFalse(result["production_enabled"])


if __name__ == "__main__":
    unittest.main()
