import unittest

import pandas as pd

from app.evaluation.local_ml_labels import add_local_core_labels


def make_panel():
    rows = []
    close_paths = {
        "000001": [10, 11, 12, 11],
        "000002": [10, 10, 10, 10],
        "000003": [10, 9, 8, 8],
        "000004": [10, 10.5, 11, 13],
        "000005": [10, 10.1, 10.2, 10.3],
    }
    dates = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    for symbol, closes in close_paths.items():
        for date, close in zip(dates, closes):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close": close,
                    "high": close * 1.03,
                    "low": close * 0.97,
                    "open": close,
                    "volume": 1000,
                    "amount": 100000,
                }
            )
    return pd.DataFrame(rows)


class LocalMLLabelsTests(unittest.TestCase):
    def test_top20_label_is_cross_sectional_by_trade_date(self):
        labeled = add_local_core_labels(make_panel(), horizons=[1, 2], primary_horizon=2)
        first_date = labeled[labeled["date"] == "2026-01-01"]

        winners = first_date[first_date["label_top20_2d"] == 1]["symbol"].tolist()

        self.assertEqual(winners, ["000001"])
        self.assertEqual(int(first_date["label_top20_2d"].sum()), 1)

    def test_multi_horizon_return_gain_and_drawdown_columns_exist(self):
        labeled = add_local_core_labels(make_panel(), horizons=[1, 2], primary_horizon=2)

        self.assertIn("future_return_1d_pct", labeled.columns)
        self.assertIn("future_return_2d_pct", labeled.columns)
        self.assertIn("future_max_gain_2d_pct", labeled.columns)
        self.assertIn("future_max_drawdown_2d_pct", labeled.columns)
        self.assertIn("label_tp_before_sl_2d", labeled.columns)

    def test_missing_or_zero_volume_rows_are_not_tradable(self):
        panel = make_panel()
        panel.loc[(panel["date"] == "2026-01-01") & (panel["symbol"] == "000001"), "volume"] = 0

        labeled = add_local_core_labels(panel, horizons=[1, 2], primary_horizon=2)
        row = labeled[(labeled["date"] == "2026-01-01") & (labeled["symbol"] == "000001")].iloc[0]

        self.assertFalse(bool(row["tradability_flag"]))


if __name__ == "__main__":
    unittest.main()
