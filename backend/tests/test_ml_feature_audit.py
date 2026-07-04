import unittest

import pandas as pd

from app.evaluation.ml_feature_audit import audit_features


class MLFeatureAuditTests(unittest.TestCase):
    def test_audit_reports_feature_quality_metrics(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=40).strftime("%Y-%m-%d"),
                "good_feature": list(range(40)),
                "noisy_feature": [1, 0] * 20,
                "label_top20_10d": [0] * 30 + [1] * 10,
                "future_return_10d_pct": [-1.0] * 30 + [8.0] * 10,
            }
        )

        report = audit_features(
            df,
            feature_names=["good_feature", "noisy_feature"],
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
        )

        good = report["features"]["good_feature"]
        self.assertEqual(good["missing_rate"], 0.0)
        self.assertGreater(good["spearman"], 0.5)
        self.assertGreater(good["univariate_auc"], 0.5)
        self.assertTrue(good["buckets"])
        self.assertIn(good["classification"], {"core_candidate", "weak_or_unstable"})

    def test_audit_blocks_leakage_features(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=10).strftime("%Y-%m-%d"),
                "future_return_10d_pct": range(10),
                "label_debug": [0, 1] * 5,
                "label_top20_10d": [0, 1] * 5,
            }
        )

        report = audit_features(
            df,
            feature_names=["future_return_10d_pct", "label_debug"],
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
        )

        self.assertEqual(report["features"]["future_return_10d_pct"]["classification"], "leakage_blocked")
        self.assertEqual(report["features"]["label_debug"]["classification"], "leakage_blocked")
        self.assertEqual(set(report["leakage_violations"]), {"future_return_10d_pct", "label_debug"})

    def test_audit_marks_high_missing_features(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=10).strftime("%Y-%m-%d"),
                "sparse_feature": [None] * 8 + [1, 2],
                "label_top20_10d": [0, 1] * 5,
                "future_return_10d_pct": [0.0, 1.0] * 5,
            }
        )

        report = audit_features(
            df,
            feature_names=["sparse_feature"],
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
        )

        self.assertEqual(report["features"]["sparse_feature"]["classification"], "missing_too_high")


if __name__ == "__main__":
    unittest.main()
