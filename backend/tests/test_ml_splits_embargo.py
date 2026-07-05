import unittest

import pandas as pd

from app.evaluation.ml_splits import build_ml_split_plan


class MLSplitEmbargoTests(unittest.TestCase):
    def test_final_holdout_and_walk_forward_apply_trading_day_embargo(self):
        dates = pd.date_range("2026-01-01", periods=90, freq="D").strftime("%Y-%m-%d")
        symbols = [f"600{idx:03d}" for idx in range(20)]
        rows = [{"date": date, "symbol": symbol} for date in dates for symbol in symbols]
        df = pd.DataFrame(rows)

        plan = build_ml_split_plan(
            df,
            final_holdout_months=1,
            stock_holdout_ratio=0.2,
            walk_forward_splits=3,
            label_horizon_days=5,
        )

        all_dates = sorted(set(dates))
        first_final_index = all_dates.index(plan["final_holdout"]["dates"][0])
        max_training_index = max(all_dates.index(date) for date in plan["training_dates"])
        self.assertLessEqual(max_training_index, first_final_index - 6)
        self.assertEqual(plan["embargo"]["label_horizon_days"], 5)
        self.assertTrue(plan["embargo"]["final_holdout_embargo_dates"])

        for window in plan["walk_forward"]["windows"]:
            first_validation_index = all_dates.index(window["validation_dates"][0])
            max_window_train_index = max(all_dates.index(date) for date in window["train_dates"])
            self.assertLessEqual(max_window_train_index, first_validation_index - 6)
            self.assertTrue(window["embargo_dates"])

    def test_stock_holdout_seed_changes_symbol_holdout_deterministically(self):
        dates = pd.date_range("2026-01-01", periods=140, freq="D").strftime("%Y-%m-%d")
        symbols = [f"600{idx:03d}" for idx in range(40)]
        rows = [{"date": date, "symbol": symbol} for date in dates for symbol in symbols]
        df = pd.DataFrame(rows)

        plan_a = build_ml_split_plan(df, stock_holdout_ratio=0.2, stock_holdout_seed=1)
        plan_b = build_ml_split_plan(df, stock_holdout_ratio=0.2, stock_holdout_seed=2)
        plan_a2 = build_ml_split_plan(df, stock_holdout_ratio=0.2, stock_holdout_seed=1)

        self.assertEqual(plan_a["stock_holdout"]["symbols"], plan_a2["stock_holdout"]["symbols"])
        self.assertNotEqual(plan_a["stock_holdout"]["symbols"], plan_b["stock_holdout"]["symbols"])


if __name__ == "__main__":
    unittest.main()
