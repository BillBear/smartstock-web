from __future__ import annotations

import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from app.evaluation.full_market_ml.splits import FinalHoldoutAccessError
from tests.full_market_ml_fixtures import monotonic_fixture, three_fold_split_fixture


def context_fixture() -> pd.DataFrame:
    rows = monotonic_fixture().copy()
    symbol_index = rows["symbol"].str[-3:].astype(int)
    rows["valid_ohlc"] = True
    rows["industry_l1"] = pd.Series(symbol_index % 2, index=rows.index).map({0: "bank", 1: "tech"})
    rows["adjusted_return_1d"] = symbol_index / 10_000.0
    rows["adjusted_return_5d"] = symbol_index / 1_000.0
    rows["adjusted_return_20d"] = symbol_index / 500.0
    rows["price_to_sma_20d"] = rows["adjusted_return_5d"] - 0.005
    rows["amount_ratio_5d"] = 1.0 + symbol_index / 10.0
    rows["turnover_rate"] = symbol_index / 5.0
    rows["total_mv"] = symbol_index * 100.0
    rows["at_up_limit"] = False
    rows["at_down_limit"] = False
    rows["net_return_after_cost_10d"] = rows["future_return_10d"] - 0.002
    rows["label_severe_negative_10d"] = symbol_index.le(2)
    rows["eligible_for_training_10d"] = True
    rows["eligible_for_training"] = True
    return rows


class ContextFeatureAuditTests(unittest.TestCase):
    def test_builds_only_declared_row_aligned_context_features(self):
        from app.evaluation.full_market_ml.context_feature_audit import (
            CONTEXT_FEATURE_NAMES,
            build_context_feature_audit,
        )

        rows = context_fixture()
        result = build_context_feature_audit(rows, three_fold_split_fixture())

        self.assertEqual(tuple(result.context_features.columns), ("trade_date", "symbol", *CONTEXT_FEATURE_NAMES))
        self.assertEqual(len(result.context_features), len(rows))
        self.assertTrue(set(result.audit.ic["feature"]).issubset(CONTEXT_FEATURE_NAMES))
        self.assertIn("stock_excess_vs_industry_5d", set(result.audit.ic["feature"]))
        self.assertEqual(
            set(result.audit.ic["feature_group"]),
            {"industry_context"},
        )

    def test_future_outcome_mutation_does_not_change_context_feature_values(self):
        from app.evaluation.full_market_ml.context_feature_audit import build_context_feature_audit

        before = context_fixture()
        after = before.copy()
        after["future_return_10d"] = 999.0
        after["net_return_after_cost_10d"] = -999.0
        after["label_severe_negative_10d"] = ~after["label_severe_negative_10d"]

        left = build_context_feature_audit(before, three_fold_split_fixture()).context_features
        right = build_context_feature_audit(after, three_fold_split_fixture()).context_features

        assert_frame_equal(left, right)

    def test_rejects_final_holdout_rows_before_context_construction(self):
        from app.evaluation.full_market_ml.context_feature_audit import build_context_feature_audit

        rows = context_fixture()
        final = rows.iloc[[0]].copy()
        final["trade_date"] = "2025-02-03"

        with self.assertRaises(FinalHoldoutAccessError):
            build_context_feature_audit(pd.concat([rows, final], ignore_index=True), three_fold_split_fixture())

    def test_requires_valid_ohlc_source_contract(self):
        from app.evaluation.full_market_ml.context_feature_audit import ContextFeatureAuditError, build_context_feature_audit

        with self.assertRaises(ContextFeatureAuditError):
            build_context_feature_audit(context_fixture().drop(columns=["valid_ohlc"]), three_fold_split_fixture())


if __name__ == "__main__":
    unittest.main()
