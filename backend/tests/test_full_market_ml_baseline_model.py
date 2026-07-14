from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.baseline_model import RegisteredBaselineTrainer


class RegisteredBaselineTrainerTests(unittest.TestCase):
    def test_date_balanced_linear_baseline_ranks_validation_cross_sections(self):
        train = _rows(tuple(pd.bdate_range("2025-01-02", periods=30).strftime("%Y-%m-%d")))
        validation = _rows(tuple(pd.bdate_range("2025-03-03", periods=5).strftime("%Y-%m-%d")))

        predictions = RegisteredBaselineTrainer().fit_predict(train, validation, ("signal",))

        self.assertEqual(len(predictions), len(validation))
        self.assertEqual(set(predictions.columns), set(validation.columns) | {"score"})
        daily = predictions.groupby("trade_date").apply(
            lambda frame: frame["score"].corr(frame["alpha_target_10d"], method="spearman"),
            include_groups=False,
        )
        self.assertTrue(daily.gt(0.95).all())

    def test_schema_is_immutable_and_future_columns_are_rejected(self):
        rows = _rows(("2025-01-02", "2025-01-03"))

        with self.assertRaises(Exception):
            RegisteredBaselineTrainer().fit_predict(rows, rows, ("future_return_10d",))


def _rows(dates: tuple[str, ...]) -> pd.DataFrame:
    records = []
    for date_index, trade_date in enumerate(dates):
        for index in range(20):
            signal = float(index) / 20.0
            records.append(
                {
                    "trade_date": trade_date,
                    "symbol": f"{index + 1:06d}",
                    "signal": signal,
                    "noise": float(np.sin(index + date_index)),
                    "alpha_target_10d": signal / 10.0,
                    "alpha_top10_10d": index >= 18,
                    "alpha_relevance_grade_10d": 4 if index >= 19 else (3 if index >= 18 else 0),
                    "net_return_after_cost_10d": signal / 10.0,
                    "severe_negative_10d": index < 2,
                }
            )
    return pd.DataFrame(records)


if __name__ == "__main__":
    unittest.main()
