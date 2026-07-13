from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.feature_selection import evaluate_feature_blocks
from tests.full_market_ml_fixtures import monotonic_fixture, three_fold_split_fixture


class FullMarketMLFeatureSelectionTests(unittest.TestCase):
    def test_fundamental_block_requires_seventy_percent_field_coverage(self):
        rows = monotonic_fixture()
        rows["fundamental_roe"] = 10.0
        rows.loc[rows.index[: int(len(rows) * 0.32)], "fundamental_roe"] = None

        decision = evaluate_feature_blocks(
            rows,
            three_fold_split_fixture(),
            {"fundamental_quality": ("fundamental_roe",)},
        )[0]

        self.assertEqual(decision.status, "rejected")
        self.assertIn("coverage_below_0_70", decision.reasons)

    def test_stable_negative_return_feature_is_not_misclassified_as_useless(self):
        dataset = monotonic_fixture()
        dataset["inverse_signal"] = -dataset["signal"]

        decision = evaluate_feature_blocks(
            dataset,
            three_fold_split_fixture(),
            {"reversal": ("inverse_signal",)},
        )[0]

        self.assertEqual(decision.status, "accepted")
        self.assertEqual(decision.return_fold_directions, (-1, -1, -1))

    def test_drifting_feature_requires_normalization_or_rejection(self):
        dataset = monotonic_fixture()
        date_number = {date: index for index, date in enumerate(sorted(dataset["trade_date"].unique()))}
        dataset["raw_market_vol"] = dataset["trade_date"].map(date_number) * 100.0 + dataset["signal"]

        decision = evaluate_feature_blocks(
            dataset,
            three_fold_split_fixture(),
            {"market": ("raw_market_vol",)},
        )[0]

        self.assertNotEqual(decision.status, "accepted")
        self.assertIn("psi_above_0_50", decision.reasons)

    def test_drift_in_one_feature_cannot_be_hidden_by_block_averaging(self):
        dataset = monotonic_fixture()
        date_number = {date: index for index, date in enumerate(sorted(dataset["trade_date"].unique()))}
        dataset["drifting_feature"] = dataset["trade_date"].map(date_number) * 100.0 + dataset["signal"]
        dataset["large_stable_feature"] = dataset["signal"] * 1_000_000_000.0

        decision = evaluate_feature_blocks(
            dataset,
            three_fold_split_fixture(),
            {"mixed": ("drifting_feature", "large_stable_feature")},
        )[0]

        self.assertNotEqual(decision.status, "accepted")
        self.assertIn("psi_above_0_50", decision.reasons)

    def test_low_coverage_moneyflow_is_diagnostic_only(self):
        dataset = monotonic_fixture()
        dataset["detailed_flow"] = dataset["signal"]
        dataset.loc[dataset.index % 5 == 0, "detailed_flow"] = None

        decision = evaluate_feature_blocks(
            dataset,
            three_fold_split_fixture(),
            {"moneyflow_detailed": ("detailed_flow",)},
        )[0]

        self.assertEqual(decision.status, "diagnostic_only")
        self.assertIn("coverage_below_0_90", decision.reasons)

    def test_final_holdout_rows_are_rejected(self):
        dataset = monotonic_fixture()
        extra = dataset.iloc[[0]].copy()
        extra["trade_date"] = "2025-02-03"

        with self.assertRaises(PermissionError):
            evaluate_feature_blocks(
                pd.concat([dataset, extra], ignore_index=True),
                three_fold_split_fixture(),
                {"signal": ("signal",)},
            )


if __name__ == "__main__":
    unittest.main()
