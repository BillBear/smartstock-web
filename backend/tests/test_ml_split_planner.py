import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.ml_splits import build_ml_split_plan


def sample_panel(symbol_count=10, start="2024-01-31", periods=10):
    dates = pd.date_range(start=start, periods=periods, freq="ME").strftime("%Y-%m-%d")
    rows = []
    for symbol_index in range(symbol_count):
        symbol = f"600{symbol_index:03d}"
        for date_text in dates:
            rows.append({"date": date_text, "symbol": symbol, "feature": symbol_index})
    return pd.DataFrame(rows)


class MLSplitPlannerTests(unittest.TestCase):
    def test_split_plan_isolates_final_time_and_stock_holdouts(self):
        df = sample_panel(symbol_count=10, periods=10)

        plan = build_ml_split_plan(
            df,
            final_holdout_months=3,
            stock_holdout_ratio=0.2,
            walk_forward_splits=3,
        )

        self.assertEqual(plan["method"], "walk_forward_plus_final_time_and_stock_holdout")
        self.assertEqual(plan["final_holdout"]["start_date"], "2024-08-31")
        self.assertEqual(plan["final_holdout"]["end_date"], "2024-10-31")
        self.assertEqual(plan["final_holdout"]["date_count"], 3)
        self.assertEqual(plan["stock_holdout"]["symbol_count"], 2)
        self.assertEqual(plan["stock_holdout"]["ratio"], 0.2)

        train_dates = set(plan["training_dates"])
        final_dates = set(plan["final_holdout"]["dates"])
        self.assertTrue(train_dates)
        self.assertTrue(final_dates)
        self.assertTrue(train_dates.isdisjoint(final_dates))

        train_symbols = set(plan["training_symbols"])
        holdout_symbols = set(plan["stock_holdout"]["symbols"])
        self.assertTrue(train_symbols)
        self.assertTrue(holdout_symbols)
        self.assertTrue(train_symbols.isdisjoint(holdout_symbols))

    def test_walk_forward_windows_use_complete_non_overlapping_dates_before_final_holdout(self):
        df = sample_panel(symbol_count=12, periods=12)

        plan = build_ml_split_plan(
            df,
            final_holdout_months=3,
            stock_holdout_ratio=0.25,
            walk_forward_splits=4,
        )

        final_dates = set(plan["final_holdout"]["dates"])
        previous_validation_end = ""
        for window in plan["walk_forward"]["windows"]:
            train_dates = set(window["train_dates"])
            validation_dates = set(window["validation_dates"])
            self.assertTrue(train_dates)
            self.assertTrue(validation_dates)
            self.assertTrue(train_dates.isdisjoint(validation_dates))
            self.assertTrue(final_dates.isdisjoint(train_dates))
            self.assertTrue(final_dates.isdisjoint(validation_dates))
            self.assertLess(max(window["train_dates"]), min(window["validation_dates"]))
            self.assertGreater(min(window["validation_dates"]), previous_validation_end)
            previous_validation_end = max(window["validation_dates"])

    def test_split_plan_rejects_insufficient_dates_for_requested_holdout(self):
        df = sample_panel(symbol_count=8, periods=3)

        with self.assertRaises(ValueError):
            build_ml_split_plan(
                df,
                final_holdout_months=3,
                stock_holdout_ratio=0.2,
                walk_forward_splits=2,
            )


if __name__ == "__main__":
    unittest.main()
