from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.label_semantic_audit import LabelSemanticAuditError, audit_label_semantics


class LabelSemanticAuditTests(unittest.TestCase):
    def test_rejects_dates_outside_the_registered_development_period(self):
        rows = _rows()
        extra = rows.iloc[:10].copy()
        extra["trade_date"] = "2025-01-03"

        with self.assertRaisesRegex(LabelSemanticAuditError, "outside the registered development dates"):
            audit_label_semantics(pd.concat([rows, extra], ignore_index=True), development_dates=("2025-01-02",))

    def test_reconstructs_old_label_and_attributes_alpha_path_disagreement(self):
        result = audit_label_semantics(_rows(), development_dates=("2025-01-02",))

        self.assertEqual("complete", result["status"])
        self.assertEqual(0, result["old_label_reconstruction_mismatch_count"])
        self.assertEqual(1, result["overlap"]["old_strong_vs_alpha_top10"]["intersection_count"])
        self.assertEqual(1, result["disagreement_reasons"]["alpha_top10_not_old"]["exclusive_reason_counts"]["severe_override"])
        self.assertEqual(0, result["overlap"]["decision_actionable_vs_decision_severe"]["intersection_count"])

    def test_does_not_mutate_input_when_reconstructing_absolute_labels(self):
        rows = _rows()
        original_columns = rows.columns.tolist()

        audit_label_semantics(rows, development_dates=("2025-01-02",))

        self.assertEqual(original_columns, rows.columns.tolist())
        self.assertNotIn("label_actionable_positive_10d", rows)


def _rows() -> pd.DataFrame:
    values = []
    for index in range(10):
        net_return = 0.10 - index * 0.02
        severe = index in {1, 9}
        values.append(
            {
                "trade_date": "2025-01-02",
                "symbol": f"0000{index:02d}",
                "eligible_for_training_10d": True,
                "entry_tradeable_10d": True,
                "horizon_available_10d": True,
                "net_return_after_cost_10d": net_return,
                "mfe_10d": 0.10,
                "mae_10d": -0.02 if index != 9 else -0.10,
                "sl_before_tp_10d": index == 1,
                "path_ambiguous_10d": False,
                "future_limit_down_count_10d": 0,
                "label_strong_path_10d": index == 0,
                "label_severe_negative_10d": severe,
                "alpha_top10_10d": index in {0, 1},
                "severe_negative_10d": severe,
            }
        )
    return pd.DataFrame(values)


if __name__ == "__main__":
    unittest.main()
