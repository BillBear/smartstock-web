from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.point_in_time import asof_announcement_join


class PointInTimeJoinTests(unittest.TestCase):
    def test_report_is_invisible_before_announcement(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-04-20"}])
        reports = pd.DataFrame(
            [{"symbol": "000001", "ann_date": "2025-04-30", "end_date": "2025-03-31", "roe": 0.10}]
        )

        joined = asof_announcement_join(signals, reports)

        self.assertTrue(joined["roe"].isna().all())

    def test_restatement_does_not_rewrite_earlier_signal(self):
        signals = pd.DataFrame(
            [
                {"symbol": "000001", "trade_date": "2025-04-30"},
                {"symbol": "000001", "trade_date": "2025-06-01"},
            ]
        )
        reports = pd.DataFrame(
            [
                {"symbol": "000001", "ann_date": "2025-04-30", "end_date": "2025-03-31", "roe": 0.10},
                {"symbol": "000001", "ann_date": "2025-05-15", "end_date": "2025-03-31", "roe": 0.12},
            ]
        )

        joined = asof_announcement_join(signals, reports)

        self.assertEqual(joined.loc[joined.trade_date.eq("2025-04-30"), "roe"].item(), 0.10)
        self.assertEqual(joined.loc[joined.trade_date.eq("2025-06-01"), "roe"].item(), 0.12)

    def test_same_announcement_uses_latest_period_not_arbitrary_input_order(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-04-30"}])
        reports = pd.DataFrame(
            [
                {"symbol": "000001", "ann_date": "2025-04-30", "end_date": "2024-12-31", "roe": 0.08},
                {"symbol": "000001", "ann_date": "2025-04-30", "end_date": "2025-03-31", "roe": 0.10},
            ]
        )

        joined = asof_announcement_join(signals, reports)

        self.assertEqual(joined["roe"].item(), 0.10)
        self.assertEqual(joined["report_end_date"].item(), "2025-03-31")

    def test_old_period_restatement_does_not_displace_newer_report_period(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-06-01"}])
        reports = pd.DataFrame(
            [
                {"symbol": "000001", "ann_date": "2025-04-30", "end_date": "2025-03-31", "roe": 0.10},
                {"symbol": "000001", "ann_date": "2025-05-15", "end_date": "2024-12-31", "roe": 0.99},
            ]
        )

        joined = asof_announcement_join(signals, reports)

        self.assertEqual(joined["roe"].item(), 0.10)
        self.assertEqual(joined["report_end_date"].item(), "2025-03-31")

    def test_same_date_correction_uses_initial_disclosure_for_historical_signal(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-05-01"}])
        reports = pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "ann_date": "2025-04-30",
                    "end_date": "2025-03-31",
                    "update_flag": "0",
                    "roe": 0.10,
                },
                {
                    "symbol": "000001",
                    "ann_date": "2025-04-30",
                    "end_date": "2025-03-31",
                    "update_flag": "1",
                    "roe": 0.99,
                },
            ]
        )

        joined = asof_announcement_join(signals, reports)

        self.assertEqual(joined["roe"].item(), 0.10)


if __name__ == "__main__":
    unittest.main()
