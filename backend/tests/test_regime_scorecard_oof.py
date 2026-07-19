from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.regime_scorecard_oof import run_regime_conditioned_scorecard_oof_rows
from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold
from app.evaluation.full_market_ml.train_only_scorecard_oof import PRE_REGISTERED_FEATURE_GROUPS


class RegimeScorecardOofTests(unittest.TestCase):
    def test_scores_each_fold_only_inside_its_frozen_market_regime(self):
        result = run_regime_conditioned_scorecard_oof_rows(
            _rows(),
            _split(),
            bootstrap_iterations=2,
            minimum_daily_ic_count=2,
            minimum_validation_dates=1,
        )

        self.assertEqual(
            {
                "fold_1_trend_up_A_development_seen",
                "fold_1_trend_up_C_development_unseen",
                "fold_2_trend_up_A_development_seen",
                "fold_2_trend_up_C_development_unseen",
            },
            set(result["fold_metrics"]),
        )
        self.assertTrue(result["predictions"]["market_regime"].eq("trend_up").all())
        self.assertEqual({1, 2}, set(result["predictions"]["fold"].dropna().astype(int)))
        self.assertTrue(result["fold_directions"][0]["directions"])
        self.assertEqual(
            "development_screen_failed",
            result["candidate_screen"]["trend_up"]["scorecard_combined_h1_h2_h3"]["status"],
        )

    def test_validation_labels_cannot_change_regime_scorecard_predictions(self):
        rows = _rows()
        changed = rows.copy()
        changed.loc[changed["trade_date"].isin(("2025-01-06", "2025-01-07")), "net_return_after_cost_10d"] = -1.0

        expected = run_regime_conditioned_scorecard_oof_rows(
            rows, _split(), bootstrap_iterations=2, minimum_daily_ic_count=2, minimum_validation_dates=1
        )
        observed = run_regime_conditioned_scorecard_oof_rows(
            changed, _split(), bootstrap_iterations=2, minimum_daily_ic_count=2, minimum_validation_dates=1
        )

        score_columns = [column for column in expected["predictions"] if column.startswith("score__")]
        self.assertTrue(
            expected["predictions"].sort_values(["fold", "trade_date", "symbol"])[score_columns].reset_index(drop=True).equals(
                observed["predictions"].sort_values(["fold", "trade_date", "symbol"])[score_columns].reset_index(drop=True)
            )
        )

    def test_does_not_evaluate_inactive_group_with_constant_scores(self):
        rows = _rows()
        for feature in PRE_REGISTERED_FEATURE_GROUPS["h1_momentum_trend"]:
            rows[feature] = 1.0

        result = run_regime_conditioned_scorecard_oof_rows(
            rows, _split(), bootstrap_iterations=2, minimum_daily_ic_count=2, minimum_validation_dates=1
        )

        metrics = result["fold_metrics"]["fold_1_trend_up_A_development_seen"]
        self.assertNotIn("scorecard_h1_momentum_trend", metrics)
        self.assertEqual(
            "inactive_no_train_only_direction",
            result["candidate_screen"]["trend_up"]["scorecard_h1_momentum_trend"]["status"],
        )


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
                "market_regime": "trend_up",
                "regime_history_complete": True,
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
