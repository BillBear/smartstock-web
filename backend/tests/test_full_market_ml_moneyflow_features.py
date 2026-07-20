from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.features import build_cross_section_features, build_time_series_features
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

    def test_industry_relative_flow_uses_full_date_peer_set_across_symbol_shards(self):
        rows = _sharded_peer_fixture()
        dates = sorted(rows["trade_date"].unique().tolist())

        full = build_cross_section_features(
            None,
            {"full": build_time_series_features(None, rows, include_moneyflow=True, market_sessions=dates)},
            include_moneyflow=True,
        )["full"]
        sharded = build_cross_section_features(
            None,
            {
                "left": build_time_series_features(
                    None,
                    rows.loc[rows["symbol"].isin(("000001", "000002"))],
                    include_moneyflow=True,
                    market_sessions=dates,
                ),
                "right": build_time_series_features(
                    None,
                    rows.loc[rows["symbol"].isin(("000003", "000004"))],
                    include_moneyflow=True,
                    market_sessions=dates,
                ),
            },
            include_moneyflow=True,
        )
        actual = pd.concat(sharded.values(), ignore_index=True)

        expected = full.loc[full["trade_date"].eq(dates[-1]), ["symbol", "flow_minus_industry_median"]].sort_values("symbol")
        observed = actual.loc[actual["trade_date"].eq(dates[-1]), ["symbol", "flow_minus_industry_median"]].sort_values("symbol")
        pd.testing.assert_frame_equal(expected.reset_index(drop=True), observed.reset_index(drop=True))


def _sharded_peer_fixture() -> pd.DataFrame:
    rows = []
    for session_index, trade_date in enumerate(pd.bdate_range("2025-01-02", periods=5)):
        for symbol, industry, large_amount in (
            ("000001", "industry_a", 10.0),
            ("000002", "industry_b", 20.0),
            ("000003", "industry_a", 30.0),
            ("000004", "industry_b", 40.0),
        ):
            rows.append(
                {
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "symbol": symbol,
                    "industry_l1": industry,
                    "amount_cny": 1_000_000.0,
                    "adjusted_return_5d": 0.01,
                    "adjusted_return_20d": 0.02,
                    "adjusted_open": 10.0,
                    "adjusted_high": 10.1,
                    "adjusted_low": 9.9,
                    "adjusted_close": 10.0 + session_index * 0.1,
                    "volume_shares": 100_000.0,
                    "turnover_rate": 1.0,
                    "total_mv": 1_000_000_000.0,
                    "circ_mv": 800_000_000.0,
                    "pe": 10.0,
                    "pb": 1.0,
                    "ps": 1.0,
                    "net_mf_amount": 0.0,
                    "listing_age_trade_days": 500,
                    "valid_ohlc": True,
                    "at_up_limit": False,
                    "at_down_limit": False,
                    "buy_sm_amount": 1.0,
                    "sell_sm_amount": 0.0,
                    "buy_md_amount": 1.0,
                    "sell_md_amount": 0.0,
                    "buy_lg_amount": large_amount,
                    "sell_lg_amount": 0.0,
                    "buy_elg_amount": 0.0,
                    "sell_elg_amount": 0.0,
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
