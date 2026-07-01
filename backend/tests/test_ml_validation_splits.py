import unittest
from datetime import date, timedelta

import pandas as pd

from app.services.ml_model_service import MLModelService


def _dataset(days=80, symbols=10):
    rows = []
    start = date(2025, 1, 2)
    for day_index in range(days):
        current = start + timedelta(days=day_index)
        for symbol_index in range(symbols):
            rows.append(
                {
                    "date": current.strftime("%Y-%m-%d"),
                    "symbol": f"{symbol_index:06d}",
                    "label_up": int((day_index + symbol_index) % 3 == 0),
                    "label_dd": int((day_index + symbol_index) % 4 == 0),
                    "feature": float(day_index + symbol_index),
                }
            )
    return pd.DataFrame(rows)


class MLValidationSplitTests(unittest.TestCase):
    def test_walk_forward_splits_do_not_mix_trade_dates(self):
        df = _dataset(days=70, symbols=6)

        splits = MLModelService._grouped_time_series_splits(df, n_splits=4)

        self.assertEqual(len(splits), 4)
        for split in splits:
            train_dates = set(df.iloc[split["train_idx"]]["date"])
            test_dates = set(df.iloc[split["test_idx"]]["date"])
            self.assertTrue(train_dates)
            self.assertTrue(test_dates)
            self.assertTrue(train_dates.isdisjoint(test_dates))
            self.assertLess(max(train_dates), min(test_dates))
            self.assertEqual(split["train_end"], max(train_dates))
            self.assertEqual(split["test_start"], min(test_dates))

    def test_final_time_holdout_is_removed_from_training_frame(self):
        df = _dataset(days=130, symbols=5)

        train_df, holdout_df, meta = MLModelService._split_final_time_holdout(df, holdout_days=20)

        self.assertFalse(train_df.empty)
        self.assertFalse(holdout_df.empty)
        self.assertLess(train_df["date"].max(), holdout_df["date"].min())
        self.assertEqual(meta["holdout_days"], 20)
        self.assertEqual(meta["holdout_start"], holdout_df["date"].min())
        self.assertEqual(meta["holdout_end"], holdout_df["date"].max())

    def test_symbol_holdout_is_disjoint_and_deterministic(self):
        df = _dataset(days=12, symbols=20)

        split_a = MLModelService._split_symbol_holdout(df, holdout_ratio=0.2, random_state=7)
        split_b = MLModelService._split_symbol_holdout(df, holdout_ratio=0.2, random_state=7)

        self.assertEqual(split_a["holdout_symbols"], split_b["holdout_symbols"])
        self.assertTrue(set(split_a["train_symbols"]).isdisjoint(split_a["holdout_symbols"]))
        self.assertEqual(len(split_a["holdout_symbols"]), 4)
        self.assertEqual(len(split_a["train_symbols"]), 16)

    def test_training_validation_frames_exclude_time_and_symbol_holdouts(self):
        df = _dataset(days=140, symbols=20)

        fit_df, final_holdout_df, symbol_holdout_df, meta = MLModelService._build_training_validation_frames(
            df,
            final_holdout_days=30,
            symbol_holdout_ratio=0.2,
            random_state=11,
        )

        self.assertFalse(fit_df.empty)
        self.assertFalse(final_holdout_df.empty)
        self.assertFalse(symbol_holdout_df.empty)
        self.assertLess(fit_df["date"].max(), final_holdout_df["date"].min())
        self.assertTrue(set(fit_df["symbol"]).isdisjoint(set(symbol_holdout_df["symbol"])))
        self.assertEqual(meta["final_time_holdout"]["holdout_days"], 30)
        self.assertEqual(meta["symbol_holdout"]["holdout_ratio"], 0.2)
        self.assertEqual(meta["fit_rows"], len(fit_df))


if __name__ == "__main__":
    unittest.main()
