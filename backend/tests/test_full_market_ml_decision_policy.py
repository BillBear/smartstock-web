from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.decision_policy import (
    DecisionPolicySpec,
    apply_decision_policy,
    derive_confidence_threshold,
)


class FullMarketMLDecisionPolicyTests(unittest.TestCase):
    def _predictions(self) -> pd.DataFrame:
        rows = []
        for date_index, trade_date in enumerate(("2025-01-02", "2025-01-03")):
            for index in range(10):
                rows.append(
                    {
                        "trade_date": trade_date,
                        "symbol": f"{index + 1:06d}",
                        "success_probability": index / 10.0,
                        "severe_probability": (9 - index) / 10.0,
                        "return_prediction": index / 100.0,
                        "label_actionable_positive_10d": index >= 7,
                        "label_severe_negative_10d_v2": index <= 1,
                        "target_clipped_return_10d": (index - 4) / 100.0,
                        "return_relevance_grade_10d_v2": min(4, index // 2),
                        "amount_log": float((index + date_index * 3) % 10),
                    }
                )
        return pd.DataFrame(rows)

    def test_combined_score_uses_daily_ranks_and_rejects_highest_risk_thirty_percent(self):
        output = apply_decision_policy(
            self._predictions(),
            DecisionPolicySpec(score_mode="combined", risk_quantile_gate=0.70),
        )

        expected = 0.5 * output.groupby("trade_date")["return_prediction"].rank(pct=True) + 0.5 * output.groupby(
            "trade_date"
        )["success_probability"].rank(pct=True) - output.groupby("trade_date")["severe_probability"].rank(pct=True)
        first_date = output["trade_date"].eq("2025-01-02")
        pd.testing.assert_series_equal(
            output.loc[first_date, "policy_score"].reset_index(drop=True),
            expected.loc[first_date].reset_index(drop=True),
            check_names=False,
        )
        self.assertEqual(output.groupby("trade_date")["risk_eligible"].sum().tolist(), [7, 7])

    def test_confidence_threshold_is_absent_when_precision_gate_is_not_met(self):
        predictions = self._predictions()
        predictions["label_actionable_positive_10d"] = False
        predictions["policy_score"] = predictions["success_probability"]

        threshold = derive_confidence_threshold(predictions, score_col="policy_score")

        self.assertIsNone(threshold)

    def test_risk_gate_rejects_exact_tail_even_when_probabilities_tie(self):
        predictions = self._predictions()
        predictions["severe_probability"] = 0.5

        output = apply_decision_policy(
            predictions,
            DecisionPolicySpec(score_mode="success", risk_quantile_gate=0.70),
        )

        self.assertEqual(output.groupby("trade_date")["risk_eligible"].sum().tolist(), [7, 7])

    def test_policy_does_not_depend_on_input_dataframe_index_uniqueness(self):
        predictions = self._predictions()
        predictions.index = [0] * len(predictions)

        output = apply_decision_policy(predictions, DecisionPolicySpec(score_mode="combined"))

        self.assertEqual(output.groupby("trade_date")["risk_eligible"].sum().tolist(), [7, 7])


if __name__ == "__main__":
    unittest.main()
