from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.labels import (
    LabelDistributionError,
    assert_label_distribution_invariants,
    build_forward_labels,
    build_label_report,
    daily_relevance_distribution,
)
from tests.full_market_ml_fixtures import (
    corporate_action_fixture,
    eligible_cross_section_fixture,
    locked_limit_up_entry_fixture,
    next_open_gap_fixture,
    same_bar_tp_sl_fixture,
)
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLLabelTests(FullMarketMLTestCase):
    def test_return_uses_next_open_not_signal_close(self):
        labeled = build_forward_labels(
            self.config,
            next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20),
        )

        self.assertEqual(labeled.iloc[0]["future_return_10d"], 0.0)

    def test_split_or_dividend_does_not_create_false_return(self):
        labeled = build_forward_labels(self.config, corporate_action_fixture())

        self.assertLess(abs(labeled.iloc[0]["future_return_10d"]), 1e-12)

    def test_same_day_take_profit_and_stop_loss_is_ambiguous(self):
        labeled = build_forward_labels(self.config, same_bar_tp_sl_fixture())
        row = labeled.iloc[0]

        self.assertTrue(bool(row["path_ambiguous_10d"]))
        self.assertFalse(bool(row["tp_before_sl_10d"]))
        self.assertFalse(bool(row["sl_before_tp_10d"]))

    def test_locked_limit_up_next_open_is_not_trainable(self):
        labeled = build_forward_labels(self.config, locked_limit_up_entry_fixture())

        self.assertFalse(bool(labeled.iloc[0]["entry_tradeable"]))
        self.assertFalse(bool(labeled.iloc[0]["eligible_for_training"]))

    def test_unavailable_horizon_stays_null_instead_of_becoming_zero(self):
        labeled = build_forward_labels(self.config, next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20).iloc[:10])

        self.assertTrue(pd.isna(labeled.iloc[0]["future_return_10d"]))
        self.assertTrue(pd.isna(labeled.iloc[0]["relevance_grade_10d"]))
        self.assertTrue(pd.isna(labeled.iloc[0]["label_strong_path_10d"]))

    def test_adjusted_mfe_and_mae_include_entry_through_exit_window(self):
        fixture = next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20)
        fixture.loc[1, ["adjusted_high", "adjusted_low"]] = [24.0, 18.0]
        labeled = build_forward_labels(self.config, fixture)

        self.assertAlmostEqual(labeled.iloc[0]["mfe_10d"], 0.2)
        self.assertAlmostEqual(labeled.iloc[0]["mae_10d"], -0.1)

    def test_cross_section_medians_only_use_eligible_rows(self):
        labeled = build_forward_labels(self.config, eligible_cross_section_fixture())
        signal_rows = labeled[labeled["trade_date"] == "2025-01-02"]
        eligible = signal_rows[signal_rows["eligible_for_training"]]

        self.assertEqual(len(eligible), 4)
        self.assertAlmostEqual(eligible.iloc[0]["market_median_future_return_10d"], 0.015)
        self.assertTrue(pd.isna(signal_rows.loc[signal_rows["symbol"] == "999999", "market_median_future_return_10d"].item()))

    def test_report_exposes_distribution_and_path_ambiguity(self):
        labeled = build_forward_labels(self.config, eligible_cross_section_fixture())
        report = build_label_report(labeled)
        distribution = daily_relevance_distribution(labeled)

        self.assertIn("strong_label_rate_10d", report)
        self.assertIn("path_ambiguity_count_10d", report)
        self.assertEqual(distribution.iloc[0]["eligible_count"], 4)
        self.assertEqual(labeled.attrs["label_report"], report)

    def test_distribution_invariants_cap_daily_top_grades_and_validate_full_period_rate(self):
        rows = []
        for index in range(1000):
            rows.append(
                {
                    "trade_date": "2025-01-02",
                    "eligible_for_training": True,
                    "relevance_grade_10d": 4 if index < 51 else (3 if index < 101 else 2),
                    "label_strong_path_10d": index < 101,
                    "market_state_10d": "normal",
                }
            )
        with self.assertRaises(LabelDistributionError):
            assert_label_distribution_invariants(pd.DataFrame(rows), require_full_development_period=False)

        valid = pd.DataFrame(rows)
        valid.loc[50, "relevance_grade_10d"] = 3
        valid.loc[100, "relevance_grade_10d"] = 2
        valid.loc[100, "label_strong_path_10d"] = False
        assert_label_distribution_invariants(valid, require_full_development_period=True)


if __name__ == "__main__":
    unittest.main()
