import unittest

import pandas as pd


class FakeTuShareClient:
    def daily_basic(self, **kwargs):
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260701",
                    "turnover_rate": 2.1,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        raise RuntimeError("permission denied")

    def suspend_d(self, **kwargs):
        return pd.DataFrame()


class TuShareEnhancedFeatureAuditTests(unittest.TestCase):
    def test_endpoint_availability_records_available_error_and_empty_status(self):
        from app.evaluation.tushare_enhanced_feature_audit import audit_tushare_endpoint_availability

        summary = audit_tushare_endpoint_availability(
            FakeTuShareClient(),
            sample_date="2026-07-01",
            endpoints=["daily_basic", "adj_factor", "suspend_d"],
        )

        self.assertEqual(summary["sample_date"], "2026-07-01")
        self.assertEqual(summary["endpoints"]["daily_basic"]["status"], "available")
        self.assertEqual(summary["endpoints"]["daily_basic"]["row_count"], 1)
        self.assertIn("turnover_rate", summary["endpoints"]["daily_basic"]["columns"])
        self.assertEqual(summary["endpoints"]["adj_factor"]["status"], "error")
        self.assertIn("permission denied", summary["endpoints"]["adj_factor"]["error"])
        self.assertEqual(summary["endpoints"]["suspend_d"]["status"], "empty")


if __name__ == "__main__":
    unittest.main()
