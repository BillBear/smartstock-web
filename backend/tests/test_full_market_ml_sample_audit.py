from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.sample_audit import build_sample_audit


class FullMarketMLSampleAuditTests(unittest.TestCase):
    def test_audit_uses_historical_expected_universe_and_reports_coverage_loss(self):
        rows = []
        for trade_date, valid_count in (("2023-01-03", 95), ("2023-01-04", 94)):
            for index in range(100):
                rows.append(
                    {
                        "trade_date": trade_date,
                        "symbol": f"{index:06d}",
                        "valid_ohlc": index < valid_count,
                        "listing_age_trade_days": 200,
                        "eligible_signal_day": True,
                        "entry_tradeable": True,
                        "is_st": False,
                        "is_suspended": False,
                        "industry_l1": "fixture",
                        "total_mv": 100.0 + index,
                        "amount_cny": 10.0 + index,
                    }
                )
        expected = pd.DataFrame(
            {"trade_date": ["2023-01-03", "2023-01-04"], "expected_active_count": [100, 100]}
        )

        report = build_sample_audit(
            pd.DataFrame(rows), expected, minimum_coverage_ratio=0.95, modern_minimum_symbols=0
        )

        self.assertFalse(report["ready"])
        self.assertIn("historical_universe_coverage_below_0_95", report["blocking_codes"])
        self.assertEqual(report["daily"][0]["coverage_ratio"], 0.95)
        self.assertEqual(report["daily"][1]["coverage_ratio"], 0.94)
        self.assertIn("board", report["distributions"])
        self.assertIn("industry", report["distributions"])
        self.assertIn("size", report["distributions"])
        self.assertIn("liquidity", report["distributions"])
        self.assertIn("entry_tradeable", report["distributions"])
        self.assertIn("valid_ohlc", report["missingness"])

    def test_audit_recomputes_120_session_eligibility_instead_of_trusting_legacy_flag(self):
        panel = pd.DataFrame(
            {
                "trade_date": ["2025-01-02", "2025-01-02"],
                "symbol": ["000001", "000002"],
                "valid_ohlc": [True, True],
                "listing_age_trade_days": [119, 120],
                "eligible_signal_day": [True, True],
                "entry_tradeable": [True, True],
                "is_st": [False, False],
                "is_suspended": [False, False],
                "industry_l1": ["A", "A"],
                "total_mv": [100.0, 200.0],
                "amount_cny": [10.0, 20.0],
            }
        )
        expected = pd.DataFrame({"trade_date": ["2025-01-02"], "expected_active_count": [2]})

        report = build_sample_audit(
            panel, expected, minimum_coverage_ratio=0.95, modern_minimum_symbols=0
        )

        self.assertEqual(report["legacy_eligible_below_listing_minimum_count"], 1)
        self.assertEqual(report["eligible_under_contract_count"], 1)
        self.assertEqual(report["independent_evidence"]["signal_date_count"], 1)
        self.assertEqual(report["independent_evidence"]["non_overlapping_10d_block_count"], 0)


if __name__ == "__main__":
    unittest.main()
