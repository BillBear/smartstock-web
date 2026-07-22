from __future__ import annotations

import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from app.evaluation.full_market_ml.shsz_market_state_audit import (
    SHSZMarketStateAuditError,
    build_shsz_market_state_table,
    validate_shsz_state_inputs,
)


class SHSZMarketStateAuditTests(unittest.TestCase):
    def test_input_binding_requires_the_frozen_panel_hash_and_shsz_universe(self):
        panel = {"universe_id": "shsz_a_share_v1", "allowed_exchanges": ["SH", "SZ"]}
        r2 = {
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
            "panel_manifest_sha256": "a" * 64,
        }

        validate_shsz_state_inputs(panel, r2, "a" * 64)
        with self.assertRaisesRegex(SHSZMarketStateAuditError, "panel manifest SHA256"):
            validate_shsz_state_inputs(panel, r2, "b" * 64)

    def test_builder_uses_full_shsz_breadth_and_one_index_close_per_date(self):
        state = build_shsz_market_state_table(_panel_rows(days=21), _r2_rows(days=21))

        latest = state.set_index("trade_date").iloc[-1]

        self.assertTrue(bool(latest["regime_history_complete"]))
        self.assertEqual("trend_up", latest["market_regime"])
        self.assertEqual(4_500, int(latest["valid_stock_count"]))
        self.assertAlmostEqual(1.0, float(latest["market_positive_breadth_1d"]))

    def test_builder_uses_limit_flags_from_certified_panel_not_r2(self):
        r2 = _r2_rows(days=21).drop(columns=["at_up_limit", "at_down_limit"])

        state = build_shsz_market_state_table(_panel_rows(days=21), r2)

        self.assertTrue(state["market_limit_up_rate"].eq(0.0).all())
        self.assertTrue(state["market_limit_down_rate"].eq(0.0).all())

    def test_future_rows_cannot_change_an_existing_state(self):
        expected = build_shsz_market_state_table(_panel_rows(days=25), _r2_rows(days=25))
        observed = build_shsz_market_state_table(_panel_rows(days=26), _r2_rows(days=26))

        assert_frame_equal(
            expected.reset_index(drop=True),
            observed.iloc[:-1].reset_index(drop=True),
        )

    def test_builder_rejects_low_coverage(self):
        with self.assertRaisesRegex(SHSZMarketStateAuditError, "fewer than 4500"):
            build_shsz_market_state_table(_panel_rows(days=21), _r2_rows(days=21, valid_count=4_499))

    def test_builder_rejects_bj_symbols_before_normalization(self):
        with self.assertRaisesRegex(SHSZMarketStateAuditError, "BJ"):
            build_shsz_market_state_table(
                _panel_rows(days=21),
                _r2_rows(days=21, first_symbol="430001.BJ"),
            )


def _panel_rows(*, days: int) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=days)
    symbols = [f"{index:06d}.SH" for index in range(4_500)]
    return pd.DataFrame(
        {
            "trade_date": date.strftime("%Y-%m-%d"),
            "symbol": symbol,
            "market_index_close": 100.0 + date_index,
            "at_up_limit": False,
            "at_down_limit": False,
        }
        for date_index, date in enumerate(dates)
        for symbol in symbols
    )


def _r2_rows(*, days: int, valid_count: int = 4_500, first_symbol: str | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=days)
    symbols = [f"{index:06d}.SZ" for index in range(valid_count)]
    if first_symbol is not None:
        symbols[0] = first_symbol
    rows = []
    for date in dates:
        rows.extend(
            {
                "trade_date": date.strftime("%Y-%m-%d"),
                "symbol": symbol,
                "valid_ohlc_flag": True,
                "adjusted_return_1d": 0.01,
                "price_to_sma_20d": 0.02,
                "at_up_limit": False,
                "at_down_limit": False,
            }
            for symbol in symbols
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
