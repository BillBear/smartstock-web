from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.decision_labels import (
    DecisionLabelContract,
    add_decision_labels,
    build_decision_label_report,
)


def decision_fixture(*, net, mae=None) -> pd.DataFrame:
    row_count = len(net)
    return pd.DataFrame(
        {
            "trade_date": ["2025-01-02"] * row_count,
            "symbol": [f"{index + 1:06d}" for index in range(row_count)],
            "eligible_for_training_10d": [True] * row_count,
            "entry_tradeable_10d": [True] * row_count,
            "net_return_after_cost_10d": net,
            "mae_10d": mae if mae is not None else [-0.01] * row_count,
            "sl_before_tp_10d": [False] * row_count,
            "path_ambiguous_10d": [False] * row_count,
            "future_limit_down_count_10d": [0] * row_count,
        }
    )


class FullMarketMLDecisionLabelTests(unittest.TestCase):
    def test_decision_labels_use_absolute_costed_outcomes(self):
        rows = decision_fixture(net=[0.03, 0.0299, -0.05], mae=[-0.06, -0.01, -0.02])

        labeled = add_decision_labels(rows, DecisionLabelContract())

        self.assertEqual(labeled["label_actionable_positive_10d"].tolist(), [True, False, False])
        self.assertEqual(labeled["label_severe_negative_10d_v2"].tolist(), [False, False, True])
        self.assertEqual(labeled["target_clipped_return_10d"].tolist(), [0.03, 0.0299, -0.05])

    def test_actionable_and_severe_labels_never_overlap(self):
        rows = decision_fixture(net=[0.08, 0.08, -0.10, 0.04])
        rows.loc[1, "sl_before_tp_10d"] = True
        rows.loc[2, "future_limit_down_count_10d"] = 1
        rows.loc[3, "path_ambiguous_10d"] = True

        labeled = add_decision_labels(rows, DecisionLabelContract())

        overlap = labeled["label_actionable_positive_10d"] & labeled["label_severe_negative_10d_v2"]
        self.assertFalse(bool(overlap.any()))
        self.assertEqual(labeled["label_actionable_positive_10d"].tolist(), [True, False, False, False])

    def test_return_relevance_uses_fixed_absolute_bins_and_preserves_missing(self):
        rows = decision_fixture(net=[-0.01, 0.01, 0.03, 0.05, 0.08, None])

        labeled = add_decision_labels(rows, DecisionLabelContract())

        self.assertEqual(labeled["return_relevance_grade_10d_v2"].tolist(), [0, 1, 2, 3, 4, pd.NA])
        self.assertTrue(pd.isna(labeled.loc[5, "target_clipped_return_10d"]))

    def test_untradeable_incomplete_and_ambiguous_rows_are_not_actionable(self):
        rows = decision_fixture(net=[0.10, None, 0.10])
        rows.loc[0, "entry_tradeable_10d"] = False
        rows.loc[1, "eligible_for_training_10d"] = False
        rows.loc[2, "path_ambiguous_10d"] = True

        labeled = add_decision_labels(rows, DecisionLabelContract())

        self.assertEqual(labeled["label_actionable_positive_10d"].tolist(), [False, False, False])
        self.assertEqual(labeled["label_severe_negative_10d_v2"].tolist(), [False, False, False])

    def test_missing_path_flags_are_reported_as_incomplete(self):
        rows = decision_fixture(net=[0.10])
        rows["sl_before_tp_10d"] = rows["sl_before_tp_10d"].astype("boolean")
        rows.loc[0, "sl_before_tp_10d"] = None

        labeled = add_decision_labels(rows, DecisionLabelContract())
        report = build_decision_label_report(labeled)

        self.assertFalse(bool(labeled.loc[0, "label_actionable_positive_10d"]))
        self.assertEqual(report["incomplete_count_10d"], 1)

    def test_unavailable_horizon_cannot_become_actionable_even_if_eligibility_is_inconsistent(self):
        rows = decision_fixture(net=[0.10])
        rows["horizon_available_10d"] = False

        labeled = add_decision_labels(rows, DecisionLabelContract())

        self.assertFalse(bool(labeled.loc[0, "label_actionable_positive_10d"]))
        self.assertEqual(labeled.attrs["decision_label_report"]["incomplete_count_10d"], 1)

    def test_missing_canonical_columns_are_rejected(self):
        rows = decision_fixture(net=[0.10]).drop(columns=["net_return_after_cost_10d"])

        with self.assertRaisesRegex(ValueError, "net_return_after_cost_10d"):
            add_decision_labels(rows, DecisionLabelContract())

    def test_distribution_report_exposes_daily_counts_class_absence_and_strata(self):
        rows = decision_fixture(net=[0.10, -0.10, 0.01, 0.02, None])
        rows["board"] = ["main", "main", "gem", "gem", "gem"]
        rows["industry_l1"] = ["bank", "bank", "tech", "tech", "tech"]
        rows["size_bucket"] = ["large", "large", "small", "small", "small"]
        rows["liquidity_bucket"] = ["high", "high", "low", "low", "low"]
        rows.loc[3, ["eligible_for_training_10d", "entry_tradeable_10d"]] = False
        rows.loc[4, "eligible_for_training_10d"] = False
        labeled = add_decision_labels(rows, DecisionLabelContract())

        report = build_decision_label_report(labeled)

        self.assertEqual(report["actionable_count_10d"], 1)
        self.assertEqual(report["severe_count_10d"], 1)
        self.assertEqual(report["neutral_count_10d"], 1)
        self.assertEqual(report["incomplete_count_10d"], 1)
        self.assertEqual(report["entry_untradeable_count_10d"], 1)
        self.assertEqual(report["overlap_count_10d"], 0)
        self.assertEqual(report["daily_distribution_10d"][0]["neutral_count"], 1)
        self.assertEqual(report["strata_distribution_10d"]["board"][0]["stratum"], "gem")
        self.assertEqual(labeled.attrs["decision_label_report"], report)


if __name__ == "__main__":
    unittest.main()
