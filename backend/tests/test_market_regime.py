from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.market_regime import MarketRegimeError, build_market_regime_table


class MarketRegimeTests(unittest.TestCase):
    def test_future_market_history_cannot_change_prior_regime(self):
        rows = _rows(days=25)

        expected = build_market_regime_table(rows).set_index("trade_date")
        changed = pd.concat(
            [
                rows,
                _rows(days=1, start="2025-02-10", close_start=10_000.0),
            ],
            ignore_index=True,
        )
        observed = build_market_regime_table(changed).set_index("trade_date")

        self.assertEqual(
            expected.loc["2025-01-31", "market_regime"],
            observed.loc["2025-01-31", "market_regime"],
        )
        self.assertEqual(
            float(expected.loc["2025-01-31", "market_return_20d"]),
            float(observed.loc["2025-01-31", "market_return_20d"]),
        )

    def test_rejects_conflicting_index_close_within_a_trade_date(self):
        rows = _rows(days=21)
        rows.loc[rows.index[0], "market_index_close"] = 999.0

        with self.assertRaises(MarketRegimeError):
            build_market_regime_table(rows)

    def test_uses_only_valid_ohlc_rows_for_breadth_and_classifies_trend(self):
        rows = _rows(days=21)
        latest_date = rows["trade_date"].max()
        rows.loc[(rows["trade_date"] == latest_date) & (rows["symbol"] == "000001"), "adjusted_return_1d"] = 0.03
        rows.loc[(rows["trade_date"] == latest_date) & (rows["symbol"] == "000002"), "adjusted_return_1d"] = -0.01
        rows.loc[(rows["trade_date"] == latest_date) & (rows["symbol"] == "000003"), ["valid_ohlc", "adjusted_return_1d"]] = [False, 0.99]

        result = build_market_regime_table(rows).set_index("trade_date").loc[latest_date]

        self.assertTrue(bool(result["regime_history_complete"]))
        self.assertEqual("trend_up", result["market_regime"])
        self.assertAlmostEqual(0.5, float(result["market_positive_breadth_1d"]))


def _rows(*, days: int, start: str = "2025-01-02", close_start: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=days)
    rows = []
    for day_index, date in enumerate(dates):
        for symbol in ("000001", "000002", "000003"):
            rows.append(
                {
                    "trade_date": date.strftime("%Y-%m-%d"),
                    "symbol": symbol,
                    "market_index_close": close_start + day_index,
                    "adjusted_return_1d": 0.01 if symbol != "000003" else -0.01,
                    "price_to_sma_20d": 0.02 if symbol != "000003" else -0.02,
                    "at_up_limit": False,
                    "at_down_limit": False,
                    "valid_ohlc": True,
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
