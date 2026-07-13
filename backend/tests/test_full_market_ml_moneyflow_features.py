from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.moneyflow_features import build_moneyflow_features


class FullMarketMLMoneyflowFeatureTests(unittest.TestCase):
    def test_detailed_flows_use_order_size_net_amounts_and_preserve_missing(self):
        rows = pd.DataFrame(
            {
                "trade_date": pd.bdate_range("2025-01-02", periods=5).strftime("%Y-%m-%d"),
                "symbol": ["000001"] * 5,
                "industry_l1": ["bank"] * 5,
                "amount_cny": [1_000_000.0] * 5,
                "adjusted_return_5d": [0.01] * 5,
                "adjusted_return_20d": [0.02] * 5,
                "buy_sm_amount": [10.0, 11.0, 12.0, 13.0, None],
                "sell_sm_amount": [5.0] * 5,
                "buy_md_amount": [20.0] * 5,
                "sell_md_amount": [10.0] * 5,
                "buy_lg_amount": [30.0] * 5,
                "sell_lg_amount": [15.0] * 5,
                "buy_elg_amount": [40.0] * 5,
                "sell_elg_amount": [20.0] * 5,
            }
        )

        output = build_moneyflow_features(rows)

        self.assertAlmostEqual(output.loc[0, "small_net_flow_ratio"], 0.05)
        self.assertAlmostEqual(output.loc[4, "large_net_flow_persistence_5d"], 0.15)
        self.assertTrue(pd.isna(output.loc[4, "small_net_flow_ratio"]))
        self.assertEqual(output.loc[4, "small_net_flow_missing"], 1)


if __name__ == "__main__":
    unittest.main()
