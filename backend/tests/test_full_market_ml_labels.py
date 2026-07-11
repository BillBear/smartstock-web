from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.labels import (
    LabelDistributionError,
    aggregate_full_market_labels,
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
    def _calendar_exact(self, panel):
        result = panel.copy()
        result["next_open_date"] = pd.NA
        for _, rows in result.groupby("symbol", sort=False):
            indexes = rows.sort_values("trade_date", kind="stable").index.tolist()
            for current, following in zip(indexes, indexes[1:]):
                result.at[current, "next_open_date"] = result.at[following, "trade_date"]
        return result

    def _aggregate(self, *panels):
        raw_shards = {
            f"shard-{index}": build_forward_labels(self.config, self._calendar_exact(panel))
            for index, panel in enumerate(panels)
        }
        return aggregate_full_market_labels(self.config, raw_shards)

    def test_return_uses_next_open_not_signal_close(self):
        labeled = build_forward_labels(
            self.config,
            self._calendar_exact(next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20)),
        )

        self.assertEqual(labeled.iloc[0]["future_return_10d"], 0.0)

    def test_split_or_dividend_does_not_create_false_return(self):
        labeled = build_forward_labels(self.config, self._calendar_exact(corporate_action_fixture()))

        self.assertLess(abs(labeled.iloc[0]["future_return_10d"]), 1e-12)

    def test_same_day_take_profit_and_stop_loss_is_ambiguous(self):
        labeled = build_forward_labels(self.config, self._calendar_exact(same_bar_tp_sl_fixture()))
        row = labeled.iloc[0]

        self.assertTrue(bool(row["path_ambiguous_10d"]))
        self.assertFalse(bool(row["tp_before_sl_10d"]))
        self.assertFalse(bool(row["sl_before_tp_10d"]))

    def test_locked_limit_up_next_open_is_not_trainable(self):
        labeled = build_forward_labels(self.config, self._calendar_exact(locked_limit_up_entry_fixture()))

        self.assertFalse(bool(labeled.iloc[0]["entry_tradeable"]))
        self.assertFalse(bool(labeled.iloc[0]["eligible_for_training"]))

    def test_unavailable_horizon_stays_null_instead_of_becoming_zero(self):
        labeled = self._aggregate(next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20).iloc[:10])["shard-0"]

        self.assertTrue(pd.isna(labeled.iloc[0]["future_return_10d"]))
        self.assertTrue(pd.isna(labeled.iloc[0]["relevance_grade_10d"]))
        self.assertTrue(pd.isna(labeled.iloc[0]["label_strong_path_10d"]))

    def test_adjusted_mfe_and_mae_include_entry_through_exit_window(self):
        fixture = next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20)
        fixture.loc[1, ["adjusted_high", "adjusted_low"]] = [24.0, 18.0]
        labeled = build_forward_labels(self.config, self._calendar_exact(fixture))

        self.assertAlmostEqual(labeled.iloc[0]["mfe_10d"], 0.2)
        self.assertAlmostEqual(labeled.iloc[0]["mae_10d"], -0.1)

    def test_cross_section_medians_only_use_eligible_rows(self):
        labeled = self._aggregate(eligible_cross_section_fixture())["shard-0"]
        signal_rows = labeled[labeled["trade_date"] == "2025-01-02"]
        eligible = signal_rows[signal_rows["eligible_for_training"]]

        self.assertEqual(len(eligible), 4)
        self.assertAlmostEqual(eligible.iloc[0]["market_median_future_return_10d"], 0.015)
        self.assertTrue(pd.isna(signal_rows.loc[signal_rows["symbol"] == "999999", "market_median_future_return_10d"].item()))

    def test_report_exposes_distribution_and_path_ambiguity(self):
        labeled = self._aggregate(eligible_cross_section_fixture())["shard-0"]
        report = build_label_report(labeled)
        distribution = daily_relevance_distribution(labeled)

        self.assertIn("strong_label_rate_10d", report)
        self.assertIn("path_ambiguity_count_10d", report)
        self.assertEqual(distribution.iloc[0]["eligible_count"], 4)
        self.assertEqual(labeled.attrs["label_report"], report)

    def test_cross_shard_aggregation_is_required_for_full_market_medians_and_grades(self):
        panel = eligible_cross_section_fixture()
        left = panel[panel["symbol"].isin(["000001", "000002"])].reset_index(drop=True)
        right = panel[panel["symbol"].isin(["000003", "000004", "999999"])].reset_index(drop=True)
        raw_left = build_forward_labels(self.config, self._calendar_exact(left))
        raw_right = build_forward_labels(self.config, self._calendar_exact(right))

        self.assertNotIn("relevance_grade_10d", raw_left.columns)
        labeled = aggregate_full_market_labels(self.config, {"left": raw_left, "right": raw_right})
        signal = pd.concat(labeled.values(), ignore_index=True).query("trade_date == '2025-01-02'")

        self.assertAlmostEqual(signal.loc[signal["symbol"] == "000001", "market_median_future_return_10d"].item(), 0.015)
        self.assertEqual(signal.loc[signal["symbol"] == "000004", "future_return_percent_rank_10d"].item(), 0.25)

    def test_missing_calendar_session_nulls_instead_of_using_later_row(self):
        panel = self._calendar_exact(next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20))
        missing_date = panel.iloc[4]["trade_date"]
        panel = panel[panel["trade_date"] != missing_date].reset_index(drop=True)

        labeled = build_forward_labels(self.config, panel)

        self.assertFalse(bool(labeled.iloc[0]["horizon_available_10d"]))
        self.assertTrue(pd.isna(labeled.iloc[0]["future_return_10d"]))

    def test_future_limit_counts_and_limit_down_mark_severe_negative(self):
        panel = self._calendar_exact(next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20))
        panel["at_up_limit"] = False
        panel["at_down_limit"] = False
        panel.loc[2, "at_up_limit"] = True
        panel.loc[3, "at_down_limit"] = True

        labeled = self._aggregate(panel)["shard-0"]
        row = labeled.iloc[0]

        self.assertEqual(row["future_limit_up_count_10d"], 1)
        self.assertEqual(row["future_limit_down_count_10d"], 1)
        self.assertTrue(bool(row["label_severe_negative_10d"]))

    def test_mae_at_or_below_negative_eight_percent_is_severe_negative(self):
        panels = []
        for index in range(20):
            panel = next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20.0 * (0.80 + index * 0.02))
            panel["symbol"] = f"{index + 1:06d}"
            panel.loc[1:, "adjusted_low"] = 19.0
            panels.append(panel)
        panels[-1].loc[1, ["adjusted_high", "adjusted_low"]] = [22.0, 18.4]

        labeled = pd.concat(self._aggregate(pd.concat(panels, ignore_index=True)).values(), ignore_index=True)
        top = labeled[(labeled["trade_date"] == "2025-01-02") & (labeled["symbol"] == "000020")].iloc[0]

        self.assertAlmostEqual(top["mae_10d"], -0.08)
        self.assertTrue(bool(top["label_severe_negative_10d"]))
        self.assertEqual(top["relevance_grade_10d"], 0)

    def test_grade_thresholds_require_mfe_and_strong_equals_grade_three_or_higher(self):
        returns = [-0.20, -0.18, -0.16, -0.14, -0.12, -0.10, -0.08, -0.06, -0.04, -0.02, 0.00, 0.01, 0.02, 0.03, 0.04, 0.045, 0.05, 0.05, 0.06, 0.07]
        panels = []
        for index, future_return in enumerate(returns):
            panel = next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20.0 * (1.0 + future_return))
            panel["symbol"] = f"{index + 1:06d}"
            panel.loc[1:, "adjusted_low"] = 19.0
            panels.append(panel)

        labeled = pd.concat(self._aggregate(pd.concat(panels, ignore_index=True)).values(), ignore_index=True)
        signal = labeled.query("trade_date == '2025-01-02'").set_index("symbol")

        self.assertEqual(signal.loc["000020", "relevance_grade_10d"], 3)  # Top 5%, MFE 7%: below grade-4 8% gate.
        self.assertTrue(bool(signal.loc["000020", "label_strong_path_10d"]))
        self.assertEqual(signal.loc["000019", "relevance_grade_10d"], 3)  # Top 10%, MFE 6%.
        self.assertEqual(signal.loc["000018", "relevance_grade_10d"], 2)  # Top 20%, positive, but MFE below 6%.

    def test_percent_rank_grades_use_top5_top10_top20_and_median_bands(self):
        panels = []
        for index in range(20):
            panel = next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20.0 * (0.80 + index * 0.02))
            panel["symbol"] = f"{index + 1:06d}"
            panel["industry_l1"] = "Industry A"
            panel.loc[1:, "adjusted_low"] = 19.0
            panels.append(panel)

        labeled = pd.concat(self._aggregate(pd.concat(panels, ignore_index=True)).values(), ignore_index=True)
        signal = labeled.query("trade_date == '2025-01-02'")

        self.assertEqual(int(signal["relevance_grade_10d"].eq(4).sum()), 1)
        self.assertEqual(int(signal["relevance_grade_10d"].eq(3).sum()), 1)
        self.assertEqual(int(signal["relevance_grade_10d"].eq(2).sum()), 2)
        self.assertEqual(int(signal["relevance_grade_10d"].eq(1).sum()), 6)
        self.assertEqual(int(signal["relevance_grade_10d"].eq(0).sum()), 10)

    def test_grade_four_requires_mae_strictly_greater_than_negative_six_percent(self):
        panels = []
        for index in range(20):
            panel = next_open_gap_fixture(signal_close=10, next_open=20, day10_close=20.0 * (0.80 + index * 0.02))
            panel["symbol"] = f"{index + 1:06d}"
            panel.loc[1:, "adjusted_low"] = 19.0
            panels.append(panel)
        panels[-1].loc[1, "adjusted_low"] = 18.8

        labeled = pd.concat(self._aggregate(pd.concat(panels, ignore_index=True)).values(), ignore_index=True)
        top = labeled[(labeled["trade_date"] == "2025-01-02") & (labeled["symbol"] == "000020")].iloc[0]

        self.assertAlmostEqual(top["mae_10d"], -0.06)
        self.assertNotEqual(top["relevance_grade_10d"], 4)

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
