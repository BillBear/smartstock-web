from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.fundamental_features import (
    FUNDAMENTAL_FEATURE_NAMES,
    build_point_in_time_fundamental_features,
)


class FundamentalFeatureTests(unittest.TestCase):
    def test_feature_schema_is_bounded_and_missing_sources_are_explicit(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-05-01"}])
        fina = pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "ann_date": "2025-04-30",
                    "end_date": "2025-03-31",
                    "roe": 10.0,
                    "grossprofit_margin": 30.0,
                    "netprofit_margin": 12.0,
                    "debt_to_assets": 40.0,
                    "current_ratio": 1.5,
                    "q_ocf_to_sales": 8.0,
                    "tr_yoy": 15.0,
                    "netprofit_yoy": 20.0,
                    "ocf_yoy": 18.0,
                }
            ]
        )

        features = build_point_in_time_fundamental_features(signals, fina)

        self.assertLessEqual(len(FUNDAMENTAL_FEATURE_NAMES), 25)
        self.assertEqual(features["fundamental_missing"].item(), 0.0)
        self.assertEqual(features["forecast_missing"].item(), 1.0)
        self.assertEqual(features["express_missing"].item(), 1.0)
        self.assertEqual(features["fundamental_days_since_announcement"].item(), 1.0)

    def test_future_report_mutation_cannot_change_signal_features(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-05-01"}])
        base = pd.DataFrame(
            [{"symbol": "000001", "ann_date": "2025-04-30", "end_date": "2025-03-31", "roe": 10.0}]
        )
        future = pd.concat(
            [
                base,
                pd.DataFrame(
                    [{"symbol": "000001", "ann_date": "2025-05-15", "end_date": "2025-03-31", "roe": 99.0}]
                ),
            ],
            ignore_index=True,
        )

        before = build_point_in_time_fundamental_features(signals, base)
        after = build_point_in_time_fundamental_features(signals, future)

        pd.testing.assert_frame_equal(before, after)

    def test_acceleration_uses_initial_value_when_prior_period_has_same_day_correction(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-05-01"}])
        fina = pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "ann_date": "2025-03-30",
                    "end_date": "2024-12-31",
                    "update_flag": "0",
                    "tr_yoy": 10.0,
                    "netprofit_yoy": 10.0,
                    "ocf_yoy": 10.0,
                },
                {
                    "symbol": "000001",
                    "ann_date": "2025-03-30",
                    "end_date": "2024-12-31",
                    "update_flag": "1",
                    "tr_yoy": 99.0,
                    "netprofit_yoy": 99.0,
                    "ocf_yoy": 99.0,
                },
                {
                    "symbol": "000001",
                    "ann_date": "2025-04-30",
                    "end_date": "2025-03-31",
                    "update_flag": "0",
                    "tr_yoy": 20.0,
                    "netprofit_yoy": 20.0,
                    "ocf_yoy": 20.0,
                },
            ]
        )

        features = build_point_in_time_fundamental_features(signals, fina)

        self.assertEqual(features["fundamental_revenue_yoy_acceleration"].item(), 10.0)

    def test_stale_fundamental_report_is_treated_as_missing(self):
        signals = pd.DataFrame([{"symbol": "000001", "trade_date": "2025-12-31"}])
        fina = pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "ann_date": "2025-01-01",
                    "end_date": "2024-12-31",
                    "roe": 10.0,
                }
            ]
        )

        features = build_point_in_time_fundamental_features(signals, fina)

        self.assertEqual(features["fundamental_missing"].item(), 1.0)
        self.assertTrue(pd.isna(features["fundamental_roe"].item()))
        self.assertEqual(features["point_in_time_coverage_flag"].item(), 0.0)

if __name__ == "__main__":
    unittest.main()
