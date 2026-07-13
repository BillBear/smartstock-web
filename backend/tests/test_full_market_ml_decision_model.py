from __future__ import annotations

import unittest
from dataclasses import replace
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.decision_model import (
    LIGHTGBM_GRID,
    DecisionModelSpec,
    _fit_heads,
    run_nested_decision_oof,
)
from app.evaluation.full_market_ml.decision_policy import DecisionPolicySpec
from app.evaluation.full_market_ml.splits import SplitPlan
from tests.full_market_ml_fixtures import predictive_fixture, three_fold_split_fixture


def decision_fixture(*, random_labels: bool = False) -> tuple[pd.DataFrame, SplitPlan]:
    rows = predictive_fixture(symbols_per_date=80).copy()
    rows["label_actionable_positive_10d"] = rows["adjusted_return_20d"].ge(0.80)
    rows["label_severe_negative_10d_v2"] = rows["adjusted_return_20d"].le(0.10)
    rows["target_clipped_return_10d"] = rows["future_return_10d"].clip(-0.12, 0.20)
    rows["return_relevance_grade_10d_v2"] = pd.cut(
        rows["target_clipped_return_10d"],
        bins=[-np.inf, 0.0, 0.02, 0.04, 0.06, np.inf],
        labels=False,
    ).astype(int)
    rows["net_return_after_cost_10d"] = rows["target_clipped_return_10d"]
    rows["entry_tradeable_10d"] = True
    rows["eligible_for_training_10d"] = True
    rows["mfe_10d"] = rows["target_clipped_return_10d"].clip(lower=0)
    rows["mae_10d"] = rows["target_clipped_return_10d"].clip(upper=0)
    if random_labels:
        rng = np.random.default_rng(42)
        for column in (
            "label_actionable_positive_10d",
            "label_severe_negative_10d_v2",
            "target_clipped_return_10d",
            "return_relevance_grade_10d_v2",
            "net_return_after_cost_10d",
        ):
            rows[column] = rng.permutation(rows[column].to_numpy())

    base = three_fold_split_fixture()
    symbols = tuple(sorted(rows["symbol"].unique()))
    train_symbols, unseen_symbols = symbols[:64], symbols[64:]
    folds = tuple(replace(fold, training_symbols=train_symbols) for fold in base.walk_forward)
    split = SplitPlan(
        development_dates=base.development_dates,
        final_dates=base.final_dates,
        stock_holdout_symbols=unseen_symbols,
        A_dev_train_symbols=train_symbols,
        B_final_train_symbols=train_symbols,
        C_dev_unseen_symbols=unseen_symbols,
        D_final_unseen_symbols=unseen_symbols,
        walk_forward=folds,
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256="decision-fixture-split",
    )
    return rows, split


class FullMarketMLDecisionModelTests(unittest.TestCase):
    def _models(self):
        return (
            DecisionModelSpec(
                model_family="logistic",
                feature_schema=("adjusted_return_20d", "amount_log"),
                seeds=(17,),
            ),
        )

    def _policies(self):
        return (
            DecisionPolicySpec(score_mode="success"),
            DecisionPolicySpec(score_mode="return"),
            DecisionPolicySpec(score_mode="combined"),
        )

    def test_outer_fold_labels_never_reach_policy_selection(self):
        rows, split = decision_fixture()
        seen_dates: list[set[str]] = []
        from app.evaluation.full_market_ml import decision_model as module

        original = module.select_inner_policy

        def spy(inner_predictions, policy_specs):
            seen_dates.append(set(inner_predictions["trade_date"]))
            return original(inner_predictions, policy_specs)

        with patch.object(module, "select_inner_policy", side_effect=spy):
            run_nested_decision_oof(rows, split, self._models(), self._policies())

        calls_per_fold = 2  # the fixed logistic C grid
        self.assertEqual(len(seen_dates), len(split.walk_forward) * calls_per_fold)
        repeated_folds = [fold for fold in split.walk_forward for _ in range(calls_per_fold)]
        for seen, fold in zip(seen_dates, repeated_folds):
            self.assertTrue(seen.isdisjoint(fold.validation_dates))

    def test_three_heads_emit_a_and_c_predictions(self):
        rows, split = decision_fixture()

        report = run_nested_decision_oof(rows, split, self._models(), self._policies())

        for column in ("success_probability", "severe_probability", "return_prediction", "policy_score"):
            self.assertIn(column, report["a_predictions"])
            self.assertIn(column, report["c_predictions"])
        self.assertEqual(set(report["a_predictions"]["quadrant"]), {"A_time_oof"})
        self.assertEqual(set(report["c_predictions"]["quadrant"]), {"C_unseen_oof"})

    def test_probability_calibration_uses_only_prior_outer_folds(self):
        rows, split = decision_fixture()

        report = run_nested_decision_oof(rows, split, self._models(), self._policies())

        first, *later = report["model_selection"]
        self.assertIsNone(first["calibration_source_max_date"])
        for selection in later:
            self.assertLess(selection["calibration_source_max_date"], min(selection["outer_validation_dates"]))
        self.assertIn("probability_display_allowed", report["a_predictions"])

    def test_random_labels_do_not_pass_research_gate(self):
        rows, split = decision_fixture(random_labels=True)

        report = run_nested_decision_oof(rows, split, self._models(), self._policies())

        self.assertEqual(report["status"], "research_only_failed_gate")
        self.assertTrue(report["failed_gates"])

    def test_resume_reuses_completed_outer_fold_predictions(self):
        rows, split = decision_fixture()
        with tempfile.TemporaryDirectory() as directory:
            run_nested_decision_oof(
                rows,
                split,
                self._models(),
                self._policies(),
                checkpoint_dir=Path(directory),
            )
            with patch(
                "app.evaluation.full_market_ml.decision_model._fit_heads",
                side_effect=AssertionError("completed fold was retrained"),
            ):
                resumed = run_nested_decision_oof(
                    rows,
                    split,
                    self._models(),
                    self._policies(),
                    checkpoint_dir=Path(directory),
                    resume=True,
                )

        self.assertFalse(resumed["a_predictions"].empty)

    def test_resume_rejects_checkpoint_with_changed_model_contract(self):
        rows, split = decision_fixture()
        changed = (
            DecisionModelSpec(
                model_family="logistic",
                feature_schema=("adjusted_return_20d", "turnover_rate"),
                seeds=(17,),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            run_nested_decision_oof(
                rows,
                split,
                self._models(),
                self._policies(),
                checkpoint_dir=Path(directory),
            )
            with self.assertRaises(ValueError):
                run_nested_decision_oof(
                    rows,
                    split,
                    changed,
                    self._policies(),
                    checkpoint_dir=Path(directory),
                    resume=True,
                )

    def test_lightgbm_early_stopping_uses_inner_time_validation_only(self):
        rows, _ = decision_fixture()
        training = rows.loc[rows["trade_date"].isin(sorted(rows["trade_date"].unique())[:2])]
        validation = rows.loc[rows["trade_date"].eq(sorted(rows["trade_date"].unique())[2])]
        spec = DecisionModelSpec(
            model_family="lightgbm_shallow",
            feature_schema=("adjusted_return_20d", "amount_log"),
            seeds=(17,),
        )

        with patch("lightgbm.LGBMClassifier.fit", autospec=True) as classifier_fit, patch(
            "lightgbm.LGBMRegressor.fit", autospec=True
        ) as regressor_fit:
            _fit_heads(training, spec, LIGHTGBM_GRID[0], validation_rows=validation)

        self.assertEqual(classifier_fit.call_count, 2)
        self.assertEqual(regressor_fit.call_count, 1)
        for call in (*classifier_fit.call_args_list, *regressor_fit.call_args_list):
            self.assertIn("eval_set", call.kwargs)
            self.assertIn("callbacks", call.kwargs)


if __name__ == "__main__":
    unittest.main()
