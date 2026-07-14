from __future__ import annotations

from dataclasses import replace

from app.evaluation.full_market_ml.config import DatesConfig
from app.evaluation.full_market_ml.research_contract import RankingResearchContract
from app.evaluation.full_market_ml.splits import (
    FinalHoldoutAccessError,
    WalkForwardFold,
    build_inner_selection_split,
    build_split_plan,
)
from tests.full_market_ml_fixtures import (
    SPLIT_FIXTURE_DATES,
    SPLIT_HOLDOUT_END,
    SPLIT_HOLDOUT_START,
    long_calendar_fixture,
    stratified_panel_fixture,
)
from tests.test_full_market_ml_collector import FullMarketMLTestCase


def trading_day_distance(left: str, right: str) -> int:
    return SPLIT_FIXTURE_DATES.index(right) - SPLIT_FIXTURE_DATES.index(left)


class FullMarketMLSplitTests(FullMarketMLTestCase):
    def setUp(self):
        super().setUp()
        self.config = replace(
            self.config,
            dates=DatesConfig(
                signal_start=SPLIT_FIXTURE_DATES[0],
                signal_end=SPLIT_HOLDOUT_END,
                holdout_start=SPLIT_HOLDOUT_START,
                holdout_end=SPLIT_HOLDOUT_END,
            ),
        )

    def test_stock_holdout_is_absent_from_every_training_fold(self):
        plan = build_split_plan(self.config, stratified_panel_fixture())

        holdout = set(plan.stock_holdout_symbols)
        self.assertEqual(len(plan.walk_forward), 5)
        for fold in plan.walk_forward:
            self.assertTrue(holdout.isdisjoint(fold.training_symbols))
            self.assertTrue(set(fold.training_symbols).issubset(plan.A_dev_train_symbols))

    def test_embargo_is_twenty_trading_days(self):
        plan = build_split_plan(self.config, long_calendar_fixture())

        for fold in plan.walk_forward:
            self.assertGreaterEqual(
                trading_day_distance(fold.train_end, fold.validation_start),
                21,
            )

    def test_final_rows_are_sealed_until_freeze_manifest_exists(self):
        plan = build_split_plan(self.config, stratified_panel_fixture())

        with self.assertRaises(FinalHoldoutAccessError):
            plan.load_quadrant("B", frozen_model_sha=None)
        sealed = plan.seal_final_holdout("model-sha-256")
        self.assertEqual(sealed.load_quadrant("B", frozen_model_sha="model-sha-256"), plan.B_final_train_symbols)

    def test_plan_has_deterministic_stratification_hash_and_quadrant_gates(self):
        dataset = stratified_panel_fixture()
        first = build_split_plan(self.config, dataset)
        second = build_split_plan(self.config, dataset.sample(frac=1.0, random_state=7))

        self.assertEqual(first.split_sha256, second.split_sha256)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(sum(first.stratum_counts_before.values()), 30)
        self.assertEqual(sum(first.stratum_counts_after.values()), len(first.stock_holdout_symbols))
        self.assertTrue(set(first.A_dev_train_symbols).isdisjoint(first.C_dev_unseen_symbols))
        self.assertTrue(set(first.B_final_train_symbols).isdisjoint(first.D_final_unseen_symbols))
        self.assertEqual(first.development_dates[-1] < first.final_dates[0], True)
        with self.assertRaises(FinalHoldoutAccessError):
            first.load_quadrant("D", frozen_model_sha=None)

    def test_inner_fit_early_stop_and_selection_roles_are_disjoint_and_ordered(self):
        dates = tuple(f"2025-{index // 28 + 1:02d}-{index % 28 + 1:02d}" for index in range(120))
        outer = tuple(f"2026-01-{index + 1:02d}" for index in range(20))
        fold = WalkForwardFold(1, dates, outer, ("000001",), dates[0], dates[-1], outer[0], outer[-1])
        contract = RankingResearchContract(
            dataset_id="fixture",
            run_id="fixture",
            feature_blocks=(("momentum", ("adjusted_return_20d",)),),
        )

        split = build_inner_selection_split(contract, fold)

        self.assertEqual(len(split.fit_dates), 80)
        self.assertEqual(len(split.early_stop_dates), 20)
        self.assertEqual(len(split.selection_dates), 20)
        self.assertLess(max(split.fit_dates), min(split.early_stop_dates))
        self.assertLess(max(split.early_stop_dates), min(split.selection_dates))
        self.assertLess(max(split.selection_dates), min(fold.validation_dates))


if __name__ == "__main__":
    import unittest

    unittest.main()
