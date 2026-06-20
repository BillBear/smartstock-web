import unittest

import pandas as pd

from app.evaluation.ranking_labels import DEFAULT_STRONG_LABEL_CONFIG, label_forward_performance


class RankingLabelTests(unittest.TestCase):
    def _frame(self, rows):
        return pd.DataFrame(rows)

    def test_strong_5d_when_return_threshold_and_drawdown_pass(self):
        history = self._frame(
            [
                {"date": "2026-01-02", "open": 10.0, "high": 10.4, "low": 9.8, "close": 10.2, "volume": 1000, "amount": 200000000},
                {"date": "2026-01-05", "open": 10.3, "high": 10.8, "low": 10.1, "close": 10.7, "volume": 1000, "amount": 210000000},
                {"date": "2026-01-06", "open": 10.7, "high": 11.1, "low": 10.6, "close": 11.0, "volume": 1000, "amount": 220000000},
                {"date": "2026-01-07", "open": 11.0, "high": 11.3, "low": 10.9, "close": 11.2, "volume": 1000, "amount": 230000000},
                {"date": "2026-01-08", "open": 11.2, "high": 11.8, "low": 11.1, "close": 11.7, "volume": 1000, "amount": 240000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertTrue(labels["strong_3d"])
        self.assertTrue(labels["strong_5d"])
        self.assertGreater(labels["return_5d_pct"], 8.0)
        self.assertEqual(labels["tp_sl_path"], "tp_before_sl")
        self.assertTrue(labels["tp_before_sl"])
        self.assertEqual(labels["tradability_status"], "tradable")
        self.assertGreater(labels["max_floating_profit_pct"], 15.0)
        self.assertGreater(labels["max_adverse_excursion_pct"], -10.0)

    def test_limit_up_entry_blocks_tradability(self):
        history = self._frame(
            [
                {"date": "2026-01-02", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000, "amount": 200000000, "pct_change": 10.0},
                {"date": "2026-01-05", "open": 11.1, "high": 11.2, "low": 10.8, "close": 11.0, "volume": 1000, "amount": 200000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertFalse(labels["limit_constraint_pass"])
        self.assertEqual(labels["tradability_status"], "limit_up_entry_blocked")
        self.assertFalse(labels["strong_3d"])

    def test_pct_chg_entry_limit_up_blocks_tradability(self):
        history = self._frame(
            [
                {"date": "2026-01-02", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000, "amount": 200000000, "pct_chg": 10.0},
                {"date": "2026-01-05", "open": 11.1, "high": 11.2, "low": 10.8, "close": 11.0, "volume": 1000, "amount": 200000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertFalse(labels["limit_constraint_pass"])
        self.assertEqual(labels["tradability_status"], "limit_up_entry_blocked")

    def test_same_day_take_profit_stop_loss_counts_stop_first(self):
        history = self._frame(
            [
                {"date": "2026-01-02", "open": 10.0, "high": 11.6, "low": 9.1, "close": 10.5, "volume": 1000, "amount": 200000000},
                {"date": "2026-01-05", "open": 10.5, "high": 10.8, "low": 10.2, "close": 10.7, "volume": 1000, "amount": 200000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertEqual(labels["tp_sl_path"], "both_same_day_stop_loss_first")
        self.assertTrue(labels["sl_before_tp"])
        self.assertFalse(labels["tp_before_sl"])

    def test_zero_volume_entry_blocks_tradability(self):
        history = self._frame(
            [
                {"date": "2026-01-02", "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.3, "volume": 0, "amount": 200000000},
                {"date": "2026-01-05", "open": 10.3, "high": 11.0, "low": 10.2, "close": 10.9, "volume": 1000, "amount": 210000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertEqual(labels["tradability_status"], "volume_or_amount_blocked")
        self.assertFalse(labels["volume_constraint_pass"])
        self.assertFalse(labels["strong_5d"])

    def test_missing_history_returns_missing_status(self):
        labels = label_forward_performance(self._frame([]), DEFAULT_STRONG_LABEL_CONFIG)

        self.assertEqual(labels["tradability_status"], "missing_history")
        self.assertFalse(labels["strong_3d"])
        self.assertEqual(labels["return_20d_pct"], 0.0)

    def test_incomplete_horizon_is_marked_missing_instead_of_reusing_last_close(self):
        history = self._frame(
            [
                {"date": "2026-01-02", "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.3, "volume": 1000, "amount": 200000000},
                {"date": "2026-01-05", "open": 10.3, "high": 11.0, "low": 10.2, "close": 10.9, "volume": 1000, "amount": 210000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertEqual(labels["return_3d_pct"], 0.0)
        self.assertFalse(labels["strong_3d"])
        self.assertIn(3, labels["incomplete_horizons"])

    def test_path_drawdown_uses_intraday_high_to_later_low(self):
        history = self._frame(
            [
                {"date": "2026-01-02", "open": 10.0, "high": 12.0, "low": 10.0, "close": 10.0, "volume": 1000, "amount": 200000000},
                {"date": "2026-01-05", "open": 10.0, "high": 10.2, "low": 9.0, "close": 10.0, "volume": 1000, "amount": 200000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertAlmostEqual(labels["path_max_drawdown_pct"], -25.0)

    def test_chinext_301_uses_twenty_percent_limit_band(self):
        history = self._frame(
            [
                {"symbol": "301001", "date": "2026-01-02", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000, "amount": 200000000, "pct_change": 10.0},
                {"symbol": "301001", "date": "2026-01-05", "open": 11.1, "high": 11.2, "low": 10.8, "close": 11.0, "volume": 1000, "amount": 200000000},
            ]
        )

        labels = label_forward_performance(history, DEFAULT_STRONG_LABEL_CONFIG)

        self.assertEqual(labels["tradability_status"], "tradable")
        self.assertTrue(labels["limit_constraint_pass"])


if __name__ == "__main__":
    unittest.main()
