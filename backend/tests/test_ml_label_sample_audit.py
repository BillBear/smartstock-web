import unittest

import pandas as pd

from app.evaluation.ml_label_sample_audit import audit_label_sample_quality


class MLLabelSampleAuditTests(unittest.TestCase):
    def test_audit_flags_fragmented_daily_cross_section_missing_names_and_embargo_overlap(self):
        df = pd.DataFrame(
            [
                {"date": "2026-03-28", "symbol": "600001", "name": "600001", "split": "train", "label_top20_10d": 1, "future_return_10d_pct": 10.0},
                {"date": "2026-03-28", "symbol": "600002", "name": "600002", "split": "train", "label_top20_10d": 0, "future_return_10d_pct": -1.0},
                {"date": "2026-04-01", "symbol": "600001", "name": "600001", "split": "final_holdout", "label_top20_10d": 0, "future_return_10d_pct": 1.0},
                {"date": "2026-04-01", "symbol": "600002", "name": "600002", "split": "final_holdout", "label_top20_10d": 1, "future_return_10d_pct": 8.0},
                {"date": "2026-04-02", "symbol": "600001", "name": "600001", "split": "final_holdout", "label_top20_10d": 0, "future_return_10d_pct": 0.0},
            ]
        )

        report = audit_label_sample_quality(
            df,
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
            horizon_days=10,
            min_daily_count=3,
            min_full_market_daily_count=5000,
            expected_label_rate=0.2,
        )

        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("daily_cross_section_below_minimum", codes)
        self.assertIn("not_full_market_cross_section", codes)
        self.assertIn("name_missing_or_symbol_only", codes)
        self.assertIn("final_holdout_embargo_overlap", codes)
        self.assertEqual(report["summary"]["row_count"], 5)
        self.assertEqual(report["summary"]["symbol_count"], 2)
        self.assertFalse(report["safe_for_model_promotion"])

    def test_audit_accepts_clean_minimal_panel(self):
        rows = []
        for day_idx, date in enumerate(pd.date_range("2026-01-01", periods=20).strftime("%Y-%m-%d")):
            split = "train" if day_idx < 8 else "unused_or_gap"
            if day_idx >= 10:
                split = "final_holdout"
            for idx in range(10):
                rows.append(
                    {
                        "date": date,
                        "symbol": f"600{idx:03d}",
                        "name": f"样本{idx}",
                        "split": split,
                        "label_top20_10d": 1 if idx < 2 else 0,
                        "future_return_10d_pct": 10.0 if idx < 2 else -1.0,
                    }
                )
        df = pd.DataFrame(rows)

        report = audit_label_sample_quality(
            df,
            label_col="label_top20_10d",
            return_col="future_return_10d_pct",
            horizon_days=2,
            min_daily_count=10,
            min_full_market_daily_count=10,
            expected_label_rate=0.2,
        )

        self.assertEqual(report["findings"], [])
        self.assertTrue(report["safe_for_model_promotion"])


if __name__ == "__main__":
    unittest.main()
