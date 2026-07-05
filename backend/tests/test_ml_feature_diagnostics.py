import unittest

import pandas as pd

from app.evaluation.ml_feature_diagnostics import diagnose_feature_effectiveness


class MLFeatureDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_identifies_strong_feature_with_tree_and_permutation(self):
        rows = []
        dates = pd.date_range("2026-01-01", periods=30).strftime("%Y-%m-%d")
        for day_idx, date in enumerate(dates):
            split = "train" if day_idx < 18 else "final_holdout"
            if day_idx >= 24:
                split = "stock_holdout"
            for idx in range(20):
                strong = float(idx)
                label = 1 if idx >= 15 else 0
                rows.append(
                    {
                        "date": date,
                        "symbol": f"600{idx:03d}",
                        "name": f"样本{idx}",
                        "split": split,
                        "strong_feature": strong,
                        "weak_feature": float(idx % 3),
                        "label_top20_10d": label,
                        "future_return_10d_pct": 8.0 if label else -1.0,
                    }
                )
        df = pd.DataFrame(rows)

        report = diagnose_feature_effectiveness(
            df,
            feature_names=["strong_feature", "weak_feature"],
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
            max_depth=3,
            min_samples_leaf=10,
            random_state=7,
        )

        self.assertEqual(report["row_count"], len(df))
        self.assertEqual(report["tree"]["status"], "trained")
        self.assertIn("strong_feature", report["tree"]["rules"])
        self.assertGreater(report["tree"]["final_holdout"]["precision_at_5"], 0.0)
        top_permutation = report["permutation_importance"]["final_holdout"][0]
        self.assertEqual(top_permutation["feature"], "strong_feature")
        self.assertGreater(top_permutation["importance_mean"], 0.0)
        strong_daily = report["daily_univariate"]["strong_feature"]
        self.assertEqual(strong_daily["best_direction"], "descending")
        self.assertEqual(strong_daily["precision_at_5"], 1.0)

    def test_diagnostics_reports_empty_when_required_split_missing(self):
        df = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-02"],
                "symbol": ["600001", "600002"],
                "split": ["train", "train"],
                "feature": [1.0, 2.0],
                "label_top20_10d": [0, 1],
                "future_return_10d_pct": [0.0, 1.0],
            }
        )

        report = diagnose_feature_effectiveness(
            df,
            feature_names=["feature"],
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
        )

        self.assertEqual(report["tree"]["status"], "skipped")
        self.assertIn("missing_holdout_split", report["warnings"])


if __name__ == "__main__":
    unittest.main()
