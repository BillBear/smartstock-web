from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.ranking_labels import (
    add_cross_sectional_alpha_labels,
    audit_label_objective,
)


def cross_section(size: int = 100, trade_date: str = "2025-01-02", shift: float = 0.0) -> pd.DataFrame:
    returns = np.linspace(-0.10, 0.10, size) + shift
    return pd.DataFrame(
        {
            "trade_date": trade_date,
            "symbol": [f"{index:06d}" for index in range(size)],
            "industry_l1": ["large"] * max(0, size - 10) + ["small"] * min(10, size),
            "eligible_for_training": True,
            "net_return_after_cost_10d": returns,
            "mae_10d": -0.02,
            "sl_before_tp_10d": False,
            "future_limit_down_count_10d": 0,
        }
    )


class FullMarketMLRankingLabelTests(unittest.TestCase):
    def test_labels_use_market_and_only_sufficient_industry_peers(self):
        rows = cross_section(40)

        labeled = add_cross_sectional_alpha_labels(rows)

        market_median = rows["net_return_after_cost_10d"].median()
        large_median = rows.loc[rows["industry_l1"] == "large", "net_return_after_cost_10d"].median()
        large = labeled.iloc[0]
        small = labeled.iloc[-1]
        self.assertAlmostEqual(large["market_excess_10d"], large["net_return_after_cost_10d"] - market_median)
        self.assertAlmostEqual(large["industry_excess_10d"], large["net_return_after_cost_10d"] - large_median)
        self.assertAlmostEqual(small["industry_excess_10d"], small["market_excess_10d"])
        self.assertFalse(bool(large["industry_fallback_to_market_10d"]))
        self.assertTrue(bool(small["industry_fallback_to_market_10d"]))

    def test_percentiles_and_grades_are_daily_and_deterministic_under_ties(self):
        rows = cross_section(20)
        rows["net_return_after_cost_10d"] = 0.01
        rows = rows.sample(frac=1.0, random_state=7).reset_index(drop=True)

        first = add_cross_sectional_alpha_labels(rows).set_index("symbol")
        second = add_cross_sectional_alpha_labels(rows.iloc[::-1].reset_index(drop=True)).set_index("symbol")

        pd.testing.assert_series_equal(
            first["alpha_percentile_10d"].sort_index(),
            second["alpha_percentile_10d"].sort_index(),
        )
        self.assertEqual(first["alpha_relevance_grade_10d"].value_counts().to_dict(), {0: 10, 1: 6, 2: 2, 3: 1, 4: 1})
        self.assertEqual(first["alpha_top10_10d"].sum(), 2)

    def test_risk_is_separate_and_does_not_redefine_alpha_grade(self):
        rows = cross_section(100)
        top = rows["net_return_after_cost_10d"].idxmax()
        rows.loc[top, "mae_10d"] = -0.09

        labeled = add_cross_sectional_alpha_labels(rows)
        top_row = labeled.loc[top]

        self.assertEqual(top_row["alpha_relevance_grade_10d"], 4)
        self.assertTrue(bool(top_row["severe_negative_10d"]))
        self.assertTrue(bool(top_row["alpha_top10_10d"]))

    def test_untradeable_or_incomplete_rows_receive_no_alpha_label(self):
        rows = cross_section(20)
        rows.loc[0, "eligible_for_training"] = False
        rows.loc[1, "net_return_after_cost_10d"] = np.nan

        labeled = add_cross_sectional_alpha_labels(rows)

        self.assertTrue(pd.isna(labeled.loc[0, "alpha_target_10d"]))
        self.assertTrue(pd.isna(labeled.loc[1, "alpha_target_10d"]))
        self.assertFalse(bool(labeled.loc[0, "alpha_top10_10d"]))

    def test_objective_audit_accepts_stable_top10_and_reports_absolute_positive_rate(self):
        dates = pd.bdate_range("2025-01-02", periods=30)
        rows = pd.concat(
            [
                cross_section(1000, date.strftime("%Y-%m-%d"), shift=-0.05 + offset / 290.0)
                for offset, date in enumerate(dates)
            ],
            ignore_index=True,
        )
        labeled = add_cross_sectional_alpha_labels(rows)

        report = audit_label_objective(labeled)

        self.assertTrue(report["passed"])
        self.assertLessEqual(report["alpha_top10_prevalence_std"], 0.01)
        self.assertEqual(len(report["daily"]), 30)
        self.assertLess(report["daily"][0]["positive_net_return_rate"], report["daily"][-1]["positive_net_return_rate"])

    def test_objective_audit_rejects_too_few_independent_dates(self):
        labeled = add_cross_sectional_alpha_labels(cross_section(1000))

        report = audit_label_objective(labeled)

        self.assertFalse(report["passed"])
        self.assertIn("audited_date_count_below_30", report["failed_gates"])

    def test_grade_caps_do_not_exceed_contract_when_cross_section_is_not_divisible(self):
        labeled = add_cross_sectional_alpha_labels(cross_section(4944))
        eligible = labeled[labeled["eligible_for_training"]]

        self.assertLessEqual(eligible["alpha_relevance_grade_10d"].eq(4).mean(), 0.05)
        self.assertLessEqual(eligible["alpha_relevance_grade_10d"].ge(3).mean(), 0.10)
        self.assertLessEqual(eligible["alpha_top10_10d"].mean(), 0.10)

    def test_changing_same_date_peer_future_return_changes_alpha_not_signal_columns(self):
        rows = cross_section(40)
        before = add_cross_sectional_alpha_labels(rows)
        changed = rows.copy()
        changed.loc[1:, "net_return_after_cost_10d"] += 0.20
        after = add_cross_sectional_alpha_labels(changed)

        self.assertNotEqual(before.loc[0, "alpha_target_10d"], after.loc[0, "alpha_target_10d"])
        self.assertEqual(before.loc[0, "symbol"], after.loc[0, "symbol"])
        self.assertEqual(before.loc[0, "trade_date"], after.loc[0, "trade_date"])


if __name__ == "__main__":
    unittest.main()
