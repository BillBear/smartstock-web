from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.interaction_features import build_interaction_features


class FullMarketMLInteractionFeatureTests(unittest.TestCase):
    def test_interactions_use_same_row_signal_features_and_fixed_u_shapes(self):
        rows = pd.DataFrame(
            {
                "trade_date": ["2025-01-02"] * 10,
                "symbol": [f"{index:06d}" for index in range(10)],
                "adjusted_return_5d": [index / 100 for index in range(10)],
                "adjusted_return_20d": [index / 50 for index in range(10)],
                "adjusted_return_60d": [index / 25 for index in range(10)],
                "amount_ratio_5d": [1.0 + index / 10 for index in range(10)],
                "turnover_rate_rank": [index / 9 for index in range(10)],
                "realized_volatility_20d": [0.02] * 10,
                "adjusted_close_to_high": [-0.01] * 10,
                "atr_pct_14d": [index / 100 for index in range(10)],
                "amount_log_rank": [index / 9 for index in range(10)],
            }
        )

        output = build_interaction_features(rows)

        self.assertAlmostEqual(output.loc[9, "return_5d_x_amount_ratio_5d"], 0.09 * 1.9)
        self.assertEqual(output.loc[0, "amount_rank_u_shape"], 1.0)
        self.assertEqual(output.loc[9, "amount_rank_u_shape"], 1.0)
        self.assertGreater(output["amount_turnover_joint_decile"].nunique(), 1)


if __name__ == "__main__":
    unittest.main()
