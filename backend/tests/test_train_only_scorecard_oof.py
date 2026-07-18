from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold
from app.evaluation.full_market_ml.train_only_scorecard_oof import (
    PRE_REGISTERED_COMPARATORS,
    PRE_REGISTERED_FEATURE_GROUPS,
    run_train_only_scorecard_oof_rows,
)


class TrainOnlyScorecardOofTests(unittest.TestCase):
    def test_runs_fold_local_a_and_c_without_pooling_overlapping_dates(self):
        rows = _rows()
        result = run_train_only_scorecard_oof_rows(rows, _split(), bootstrap_iterations=5)

        self.assertEqual(result["input_summary"]["outer_test_aggregation_policy"], "fold_local_metrics_only")
        self.assertEqual(set(result["fold_metrics"]), {"fold_1_A_development_seen", "fold_1_C_development_unseen", "fold_2_A_development_seen", "fold_2_C_development_unseen"})
        self.assertEqual(set(result["fold_metrics"]["fold_1_A_development_seen"]), set(PRE_REGISTERED_COMPARATORS))
        self.assertEqual(set(result["fold_bootstrap"]["fold_1_A_development_seen"]), set(PRE_REGISTERED_COMPARATORS) - {"baseline_momentum_60d"})
        self.assertEqual(result["predictions"].groupby(["fold", "trade_date"]).size().loc[(1, "2025-01-06")], 4)
        self.assertEqual(result["predictions"].groupby(["fold", "trade_date"]).size().loc[(2, "2025-01-06")], 4)

    def test_rejects_final_holdout_rows_before_training(self):
        rows = _rows()
        extra = rows.iloc[:4].copy()
        extra["trade_date"] = "2025-01-08"
        with self.assertRaises(PermissionError):
            run_train_only_scorecard_oof_rows(pd.concat([rows, extra], ignore_index=True), _split(), bootstrap_iterations=2)


def _split() -> SplitPlan:
    training_symbols = ("000001", "000002", "000003")
    unseen = ("000004",)
    folds = (
        WalkForwardFold(1, ("2025-01-02", "2025-01-03"), ("2025-01-06",), training_symbols, "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-06"),
        WalkForwardFold(2, ("2025-01-02", "2025-01-03"), ("2025-01-06", "2025-01-07"), training_symbols, "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"),
    )
    return SplitPlan(
        development_dates=("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"),
        final_dates=("2025-01-08",),
        stock_holdout_symbols=unseen,
        A_dev_train_symbols=training_symbols,
        B_final_train_symbols=(),
        C_dev_unseen_symbols=unseen,
        D_final_unseen_symbols=(),
        walk_forward=folds,
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256="fixture",
    )


def _rows() -> pd.DataFrame:
    values = []
    for date_index, trade_date in enumerate(("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07")):
        for symbol_index, symbol in enumerate(("000001", "000002", "000003", "000004"), start=1):
            row = {
                "trade_date": trade_date,
                "symbol": symbol,
                "eligible_for_training_10d": True,
                "entry_tradeable_10d": True,
                "horizon_available_10d": True,
                "path_ambiguous_10d": False,
                "future_return_10d": 0.01 * symbol_index,
                "net_return_after_cost_10d": 0.01 * symbol_index,
                "relevance_grade_10d": 2 if symbol_index >= 3 else 0,
                "label_strong_path_10d": symbol_index >= 3,
                "label_severe_negative_10d": False,
                "entry_price_10d": 10.0,
                "exit_price_10d": 10.0 + symbol_index,
                "exit_trade_date_10d": "2025-01-20",
                "market_median_net_return_10d": 0.02,
                "industry_median_net_return_10d": 0.02,
            }
            for group_index, features in enumerate(PRE_REGISTERED_FEATURE_GROUPS.values(), start=1):
                for feature_index, feature in enumerate(features, start=1):
                    row[feature] = float(symbol_index * feature_index + date_index * group_index)
            values.append(row)
    return pd.DataFrame(values)


if __name__ == "__main__":
    unittest.main()
