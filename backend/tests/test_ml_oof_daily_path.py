from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.ml_oof_daily_path import reconstruct_selected_daily_paths


COMMISSION = 0.0003
SLIPPAGE = 0.001
DATES = (
    "2025-01-02",
    "2025-01-03",
    "2025-01-06",
    "2025-01-07",
    "2025-01-08",
    "2025-01-09",
    "2025-01-10",
    "2025-01-13",
    "2025-01-14",
    "2025-01-15",
    "2025-01-16",
)


class MLOofDailyPathTest(unittest.TestCase):
    def test_reconstructs_exact_costed_terminal_factor_for_selected_row(self):
        oof = _oof_rows()
        panel = _panel_rows()

        paths, report = reconstruct_selected_daily_paths(
            oof_rows=oof,
            panel_rows=panel,
            score_column="model_score",
            top_k=1,
        )

        expected_factor = _expected_terminal_factor()
        self.assertEqual("complete", report["status"])
        self.assertEqual(1, report["selected_row_count"])
        self.assertEqual(1, report["reconstructed_row_count"])
        self.assertEqual(0, report["rejected_row_count"])
        self.assertEqual(10, len(paths))
        self.assertEqual("2025-01-03", paths.iloc[0]["portfolio_mark_date"])
        self.assertEqual("2025-01-16", paths.iloc[-1]["portfolio_mark_date"])
        self.assertAlmostEqual(expected_factor, float(paths.iloc[-1]["cohort_net_factor"]), places=12)

    def test_rejects_selected_row_when_future_sessions_are_not_consecutive(self):
        panel = _panel_rows()
        panel.loc[panel["trade_date"].eq("2025-01-09"), "next_open_date"] = "2025-01-13"

        paths, report = reconstruct_selected_daily_paths(
            oof_rows=_oof_rows(),
            panel_rows=panel,
            score_column="model_score",
            top_k=1,
        )

        self.assertTrue(paths.empty)
        self.assertEqual("blocked", report["status"])
        self.assertEqual(1, report["rejected_row_count"])
        self.assertIn("nonconsecutive_future_session", report["rejection_codes"])

    def test_rejects_selected_row_when_terminal_label_does_not_match_rebuilt_path(self):
        oof = _oof_rows()
        oof.loc[0, "net_return_after_cost_10d"] += 0.01

        paths, report = reconstruct_selected_daily_paths(
            oof_rows=oof,
            panel_rows=_panel_rows(),
            score_column="model_score",
            top_k=1,
        )

        self.assertTrue(paths.empty)
        self.assertEqual("blocked", report["status"])
        self.assertEqual(1, report["terminal_mismatch_count"])
        self.assertIn("terminal_factor_mismatch", report["rejection_codes"])


def _oof_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fold": 1,
                "quadrant": "A",
                "trade_date": "2025-01-02",
                "symbol": "000001",
                "model_score": 0.9,
                "baseline_score": 0.4,
                "entry_tradeable": True,
                "horizon_available_10d": True,
                "path_ambiguous_10d": False,
                "net_return_after_cost_10d": _expected_terminal_factor() - 1.0,
            }
        ]
    )


def _panel_rows() -> pd.DataFrame:
    rows = []
    for index, trade_date in enumerate(DATES):
        rows.append(
            {
                "trade_date": trade_date,
                "symbol": "000001",
                "next_open_date": DATES[index + 1] if index + 1 < len(DATES) else None,
                "adjusted_open": 10.0,
                "adjusted_close": 12.0 if trade_date == DATES[-1] else 10.0,
                "valid_ohlc": True,
                "is_suspended": False,
                "at_up_limit_open": False,
            }
        )
    return pd.DataFrame(rows)


def _expected_terminal_factor() -> float:
    return (12.0 * (1.0 - SLIPPAGE)) / (10.0 * (1.0 + SLIPPAGE)) * (1.0 - COMMISSION) ** 2
