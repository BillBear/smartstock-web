from __future__ import annotations

from app.evaluation.full_market_ml.feature_audit import audit_features
from app.evaluation.full_market_ml.splits import FinalHoldoutAccessError
from tests.full_market_ml_fixtures import (
    dataset_with_final_rows_exposed,
    monotonic_fixture,
    sealed_split_fixture,
    three_fold_split_fixture,
)
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLFeatureAuditTests(FullMarketMLTestCase):
    def test_monotonic_feature_has_positive_ic_and_bucket_spread(self):
        result = audit_features(monotonic_fixture(), three_fold_split_fixture())

        row = result.ic.query("feature == 'signal'").iloc[0]
        self.assertGreater(row["median_ic"], 0.5)
        self.assertEqual(row["sign_consistency"], 1.0)
        spread = result.bucket_returns.query("feature == 'signal'")["top_bottom_spread"].median()
        self.assertGreater(spread, 0)

    def test_feature_audit_never_reads_final_holdout(self):
        with self.assertRaises(FinalHoldoutAccessError):
            audit_features(dataset_with_final_rows_exposed(), sealed_split_fixture())

    def test_reports_high_correlation_psi_and_moneyflow_task_twelve_gate(self):
        result = audit_features(monotonic_fixture(), three_fold_split_fixture())

        self.assertTrue(
            result.correlation.query("feature_left == 'correlated_signal' and feature_right == 'signal'")["abs_correlation"].ge(0.95).all()
        )
        self.assertEqual(set(result.drift["fold"]), {1, 2, 3})
        self.assertEqual(set(result.group_eligibility.query("feature_group == 'moneyflow'")["fold"]), {1, 2, 3})
        moneyflow = result.group_eligibility.query("feature_group == 'moneyflow'").iloc[0]
        self.assertGreaterEqual(moneyflow["coverage"], 0.8)
        self.assertEqual(moneyflow["eligibility"], "pending_oof_group_comparison")


if __name__ == "__main__":
    import unittest

    unittest.main()
