from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold
from app.evaluation.full_market_ml.train_only_scorecard_oof import _ALL_FEATURES, _REQUIRED_COLUMNS


class ContextScorecardAblationTests(unittest.TestCase):
    def test_compares_active_candidate_and_baseline_on_identical_fold_rows(self):
        from app.evaluation.full_market_ml.context_scorecard_ablation import (
            BASELINE_SCORECARD,
            CANDIDATE_SCORECARD,
            CONTEXT_ABLATION_FEATURES,
            run_context_scorecard_ablation_rows,
        )

        result = run_context_scorecard_ablation_rows(_rows(), _split(), bootstrap_iterations=3)

        self.assertEqual(result["input_summary"]["outer_test_aggregation_policy"], "fold_local_metrics_only")
        self.assertEqual(tuple(result["input_summary"]["context_features"]), CONTEXT_ABLATION_FEATURES)
        self.assertEqual(result["candidate_screen"]["status"], "exploratory_post_selection_only")
        for fold in (1, 2):
            directions = result["fold_directions"][fold - 1]
            self.assertEqual(set(directions["candidate_context_directions"]), set(CONTEXT_ABLATION_FEATURES))
            for quadrant in ("A_development_seen", "C_development_unseen"):
                key = f"fold_{fold}_{quadrant}"
                self.assertEqual(
                    set(result["fold_metrics"][key]),
                    {"baseline_momentum_60d", BASELINE_SCORECARD, CANDIDATE_SCORECARD},
                )
                self.assertIn(CANDIDATE_SCORECARD, result["fold_bootstrap"][key])
                self.assertIn(CANDIDATE_SCORECARD, result["fold_portfolios"][key])

        predictions = result["predictions"]
        self.assertFalse(predictions[f"score__{BASELINE_SCORECARD}"].isna().any())
        self.assertFalse(predictions[f"score__{CANDIDATE_SCORECARD}"].isna().any())

    def test_validation_label_mutation_cannot_change_prior_fold_context_directions(self):
        from app.evaluation.full_market_ml.context_scorecard_ablation import run_context_scorecard_ablation_rows

        original = _rows()
        mutated = original.copy()
        mask = mutated["trade_date"].eq("2025-01-06")
        mutated.loc[mask, "net_return_after_cost_10d"] *= -100.0

        before = run_context_scorecard_ablation_rows(original, _split(), bootstrap_iterations=2)
        after = run_context_scorecard_ablation_rows(mutated, _split(), bootstrap_iterations=2)

        self.assertEqual(
            before["fold_directions"][0]["candidate_context_directions"],
            after["fold_directions"][0]["candidate_context_directions"],
        )
        self.assertEqual(
            before["fold_directions"][0]["candidate_context_direction_evidence"],
            after["fold_directions"][0]["candidate_context_direction_evidence"],
        )

    def test_does_not_silently_drop_an_unstable_context_feature(self):
        from app.evaluation.full_market_ml.context_scorecard_ablation import (
            CANDIDATE_SCORECARD,
            run_context_scorecard_ablation_rows,
        )

        rows = _rows()
        rows["industry_limit_down_rate"] = 0.0
        result = run_context_scorecard_ablation_rows(rows, _split(), bootstrap_iterations=2)

        self.assertEqual(result["candidate_screen"]["status"], "exploratory_inactive")
        self.assertEqual(result["candidate_screen"]["production_integration_allowed"], False)
        self.assertNotIn(CANDIDATE_SCORECARD, result["fold_metrics"]["fold_1_A_development_seen"])
        self.assertEqual(result["fold_directions"][0]["candidate_status"], "inactive_missing_fold_local_context_direction")

    def test_rejects_final_holdout_rows_before_direction_fit(self):
        from app.evaluation.full_market_ml.context_scorecard_ablation import run_context_scorecard_ablation_rows

        rows = _rows()
        final = rows.iloc[:4].copy()
        final["trade_date"] = "2025-01-08"

        with self.assertRaises(PermissionError):
            run_context_scorecard_ablation_rows(pd.concat([rows, final], ignore_index=True), _split(), bootstrap_iterations=2)


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
        split_sha256="context-ablation-fixture",
    )


def _rows() -> pd.DataFrame:
    rows = []
    for date_index, trade_date in enumerate(("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07")):
        for symbol_index, symbol in enumerate(("000001", "000002", "000003", "000004"), start=1):
            forward_return = 0.01 * symbol_index + date_index / 10_000.0
            row = {
                "trade_date": trade_date,
                "symbol": symbol,
                "eligible_for_training_10d": True,
                "entry_tradeable_10d": True,
                "horizon_available_10d": True,
                "path_ambiguous_10d": False,
                "future_return_10d": forward_return,
                "net_return_after_cost_10d": forward_return,
                "relevance_grade_10d": 2 if symbol_index >= 3 else 0,
                "label_strong_path_10d": symbol_index >= 3,
                "label_severe_negative_10d": False,
                "entry_price_10d": 10.0,
                "exit_price_10d": 10.0 + symbol_index,
                "exit_trade_date_10d": "2025-01-20",
                "market_median_net_return_10d": 0.02,
                "industry_median_net_return_10d": 0.02,
                "stock_excess_vs_industry_5d": -float(symbol_index),
                "industry_limit_up_rate": -float(symbol_index) / 10.0,
                "industry_limit_down_rate": -float(symbol_index) / 100.0,
            }
            for group_index, feature in enumerate(_ALL_FEATURES, start=1):
                row[feature] = float(symbol_index * group_index + date_index)
            rows.append(row)
    frame = pd.DataFrame(rows)
    missing = (set(_REQUIRED_COLUMNS) | set(_ALL_FEATURES)) - set(frame.columns)
    if missing:
        raise AssertionError(f"fixture misses required columns: {sorted(missing)}")
    return frame


if __name__ == "__main__":
    unittest.main()
