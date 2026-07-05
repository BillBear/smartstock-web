import unittest

import pandas as pd

from app.evaluation.local_ml_v2 import (
    V2_FEATURE_NAMES,
    add_local_core_v2_labels,
    build_local_core_v2_features,
    filter_daily_cross_section,
)


def make_panel(date_count=50, symbol_count=20):
    rows = []
    dates = pd.date_range("2026-01-01", periods=date_count, freq="D").strftime("%Y-%m-%d")
    for symbol_idx in range(symbol_count):
        symbol = f"600{symbol_idx:03d}"
        for day_idx, date in enumerate(dates):
            close = 10 + symbol_idx * 0.1 + day_idx * (0.02 + symbol_idx * 0.001)
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "name": f"样本{symbol_idx}",
                    "open": close * 0.99,
                    "high": close * (1.01 + symbol_idx * 0.0005),
                    "low": close * 0.98,
                    "close": close,
                    "volume": 100000 + symbol_idx * 1000 + day_idx * 100,
                    "amount": (100000 + symbol_idx * 1000 + day_idx * 100) * close,
                    "pct_change": 1.0,
                    "return_5d_pct": 0.0,
                    "return_20d_pct": 0.0,
                    "ma20_gap_pct": 0.0,
                    "ma60_gap_pct": 0.0,
                    "ma_alignment": 0.0,
                    "macd_hist": 0.0,
                    "rsi": 50.0,
                    "boll_position": 0.5,
                    "volume_ratio_5": 1.0,
                    "amount_yi": 0.1,
                    "money_flow_proxy_yi": 0.0,
                    "volatility_20d": 0.0,
                    "intraday_range_pct": 1.0,
                }
            )
    return pd.DataFrame(rows)


class LocalMLV2LabelsFeaturesTests(unittest.TestCase):
    def test_v2_labels_create_daily_top10_alpha_and_trade_quality_targets(self):
        labeled = add_local_core_v2_labels(make_panel(date_count=20, symbol_count=20), horizons=[3], primary_horizon=3)

        complete = labeled[labeled["future_return_3d_pct"].notna()].copy()
        counts = complete.groupby("date")["label_rank_top10_3d"].sum()
        self.assertTrue((counts == 2).all())
        self.assertIn("future_excess_return_3d_pct", labeled.columns)
        self.assertIn("label_alpha_top20_3d", labeled.columns)
        self.assertIn("label_drawdown_safe_3d", labeled.columns)
        self.assertIn("label_trade_quality_3d", labeled.columns)
        self.assertIn("label_tradeable_entry", labeled.columns)

    def test_filter_daily_cross_section_drops_sparse_dates_before_training(self):
        frame = make_panel(date_count=4, symbol_count=10)
        sparse = frame[~((frame["date"] == "2026-01-02") & (frame["symbol"].astype(str) >= "600005"))].copy()

        filtered, report = filter_daily_cross_section(sparse, min_daily_count=10)

        self.assertNotIn("2026-01-02", set(filtered["date"]))
        self.assertEqual(report["dropped_date_count"], 1)
        self.assertEqual(report["min_daily_count"], 5)

    def test_v2_features_add_distinct_behavioral_features_without_news_or_known_duplicates(self):
        featured, feature_specs = build_local_core_v2_features(make_panel(date_count=80, symbol_count=12))

        self.assertIn("return_20d_rank", featured.columns)
        self.assertIn("trend_slope_20d", featured.columns)
        self.assertIn("amount_pct_rank", featured.columns)
        self.assertIn("atr_14_pct", featured.columns)
        self.assertNotIn("news_total_score", V2_FEATURE_NAMES)
        self.assertNotIn("max_drawdown_20d", V2_FEATURE_NAMES)
        self.assertNotIn("from_20d_high_pct", V2_FEATURE_NAMES)
        self.assertEqual(set(V2_FEATURE_NAMES), {spec["name"] for spec in feature_specs})
        self.assertTrue(featured["return_20d_rank"].between(0, 1).all())


if __name__ == "__main__":
    unittest.main()
