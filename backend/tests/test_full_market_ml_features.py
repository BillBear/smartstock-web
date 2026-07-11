from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.features import (
    CORE_FEATURE_SPECS,
    FEATURE_NAMES,
    FeatureLeakageError,
    assert_leak_free_schema,
    build_features_for_date,
)
from tests.test_full_market_ml_collector import FullMarketMLTestCase


def feature_fixture(*, sessions: int = 30, symbols: int = 4) -> pd.DataFrame:
    rows = []
    for symbol_index in range(symbols):
        symbol = f"{symbol_index + 1:06d}"
        for offset, trade_date in enumerate(pd.bdate_range("2024-12-02", periods=sessions)):
            close = 10.0 + symbol_index + offset * (0.04 + symbol_index * 0.005)
            rows.append({"trade_date": trade_date.strftime("%Y-%m-%d"), "symbol": symbol, "adjusted_open": close * 0.995, "adjusted_high": close * 1.015, "adjusted_low": close * 0.985, "adjusted_close": close, "volume_shares": 1_000_000 + symbol_index * 100_000 + offset * 1_000, "amount_cny": close * (1_000_000 + symbol_index * 100_000), "turnover_rate": 2.0 + symbol_index * 0.2, "total_mv": 10_000_000_000 + symbol_index * 1_000_000_000, "circ_mv": 8_000_000_000 + symbol_index * 800_000_000, "pe": 10.0 + symbol_index, "pb": 1.0 + symbol_index * 0.1, "ps": 2.0 + symbol_index * 0.1, "main_net_inflow_ratio": 0.01 * (symbol_index + 1), "net_mf_amount": 100_000 + symbol_index * 10_000, "industry_l1": "Industry A" if symbol_index % 2 == 0 else "Industry B", "listing_age_trade_days": 300 + offset, "valid_ohlc": True})
    return pd.DataFrame(rows)


def moneyflow_missing_fixture() -> pd.DataFrame:
    return feature_fixture().drop(columns=["main_net_inflow_ratio", "net_mf_amount"])


class FullMarketMLFeatureTests(FullMarketMLTestCase):
    def test_future_price_mutation_cannot_change_signal_day_features(self):
        original = feature_fixture()
        mutated = original.copy()
        mutated.loc[mutated.trade_date > "2025-01-10", ["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"]] *= 10

        left = build_features_for_date(self.config, original, "2025-01-10")
        right = build_features_for_date(self.config, mutated, "2025-01-10")

        pd.testing.assert_frame_equal(left[FEATURE_NAMES], right[FEATURE_NAMES])

    def test_next_day_tradeability_is_rejected_from_feature_schema(self):
        for name in ("entry_tradeable", "next_adjusted_open", "future_return_10d", "label_strong_path_10d", "relevance_grade_10d", "tp_before_sl_10d", "sl_before_tp_10d", "path_ambiguous_10d", "return_t+1", "entry_price_t_plus_1"):
            with self.subTest(name=name), self.assertRaises(FeatureLeakageError):
                assert_leak_free_schema(["adjusted_return_20d_rank", name])

    def test_panel_execution_metadata_is_not_a_model_feature(self):
        panel = feature_fixture()
        panel["entry_tradeable"] = True

        matrix = build_features_for_date(self.config, panel, "2025-01-10")

        self.assertNotIn("entry_tradeable", matrix.columns)

    def test_missing_flags_are_in_model_matrix(self):
        matrix = build_features_for_date(self.config, moneyflow_missing_fixture(), "2025-01-10")

        self.assertIn("main_net_inflow_ratio_missing", matrix.columns)
        self.assertTrue(matrix["main_net_inflow_ratio_missing"].eq(1).all())

    def test_feature_contract_has_explicit_bounded_core_dictionary(self):
        self.assertGreaterEqual(len(CORE_FEATURE_SPECS), 80)
        self.assertLessEqual(len(CORE_FEATURE_SPECS), 120)
        self.assertEqual(len(FEATURE_NAMES), len(CORE_FEATURE_SPECS))
        self.assertTrue(all(spec.formula and spec.source_endpoint and spec.missing_policy for spec in CORE_FEATURE_SPECS))

    def test_cross_section_uses_only_same_day_values_and_has_robust_values(self):
        matrix = build_features_for_date(self.config, feature_fixture(), "2025-01-10")

        self.assertIn("adjusted_return_20d_rank", matrix.columns)
        self.assertIn("adjusted_return_20d_robust_z", matrix.columns)
        self.assertTrue(matrix["adjusted_return_20d_rank"].between(0, 1).all())


if __name__ == "__main__":
    unittest.main()
