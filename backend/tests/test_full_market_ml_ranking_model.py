from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.ranking_model import (
    RankingModelSpec,
    build_fixed_baseline_predictions,
    run_nested_ranking_oof,
)
from app.evaluation.full_market_ml.research_contract import DEFAULT_BASELINE_DEFINITIONS
from tests.test_full_market_ml_ablation import _fixture


class FullMarketMLRankingModelTests(unittest.TestCase):
    def test_fixed_baselines_use_exact_registered_score_definitions(self):
        rows, _ = _fixture()
        sample = rows.head(60).copy()
        sample["adjusted_return_20d"] = sample["signal"]
        sample["adjusted_return_60d"] = sample["base"]
        sample["adjusted_return_20d_rank"] = sample["signal"]
        sample["amount_log"] = sample["noise"]

        first = build_fixed_baseline_predictions(sample, DEFAULT_BASELINE_DEFINITIONS)
        second = build_fixed_baseline_predictions(sample, DEFAULT_BASELINE_DEFINITIONS)

        pd.testing.assert_series_equal(first["score__random"], second["score__random"])
        self.assertTrue((first["score__amount_ascending"] == -first["score__amount_descending"]).all())
        self.assertTrue(np.allclose(first["score__registered_single_feature"], sample["signal"]))

    def test_nested_selection_uses_inner_dates_and_returns_outer_oof_only(self):
        rows, plan = _fixture()
        specs = (
            RankingModelSpec("strong_linear", "linear_scorecard", ("signal",)),
            RankingModelSpec("noise_linear", "linear_scorecard", ("noise",)),
        )

        result = run_nested_ranking_oof(rows, plan, specs)

        self.assertEqual(result["selected_spec"], "strong_linear")
        predictions = result["predictions"]
        expected_dates = {date for fold in plan.walk_forward for date in fold.validation_dates}
        self.assertEqual(set(predictions["trade_date"]), expected_dates)
        self.assertEqual(set(predictions["fold"]), {1, 2, 3, 4, 5})

    def test_mutating_outer_labels_cannot_change_inner_model_selection(self):
        rows, plan = _fixture()
        specs = (
            RankingModelSpec("strong_linear", "linear_scorecard", ("signal",)),
            RankingModelSpec("noise_linear", "linear_scorecard", ("noise",)),
        )
        before = run_nested_ranking_oof(rows, plan, specs)
        outer_dates = set(plan.walk_forward[-1].validation_dates)
        changed = rows.copy()
        mask = changed["trade_date"].isin(outer_dates)
        changed.loc[mask, "alpha_target_10d"] *= -1
        changed.loc[mask, "alpha_relevance_grade_10d"] = 0
        changed.loc[mask, "alpha_top10_10d"] = False

        after = run_nested_ranking_oof(changed, plan, specs)

        self.assertEqual(before["selected_spec"], after["selected_spec"])
        self.assertEqual(before["selection_evidence"], after["selection_evidence"])

    def test_bounded_lambdarank_runs_with_trade_date_groups(self):
        rows, plan = _fixture()
        spec = RankingModelSpec(
            "bounded_lambdarank",
            "lightgbm_lambdarank",
            ("signal", "noise"),
            parameters=(("n_estimators", 30), ("num_leaves", 7), ("max_depth", 3)),
        )

        result = run_nested_ranking_oof(rows, plan, (spec,))

        self.assertEqual(result["selected_family"], "lightgbm_lambdarank")
        self.assertGreaterEqual(result["fixed_iterations"], 1)
        self.assertEqual(set(result["predictions"]["fold"]), {1, 2, 3, 4, 5})


if __name__ == "__main__":
    unittest.main()
