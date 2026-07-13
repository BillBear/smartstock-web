from __future__ import annotations

import math
import unittest

import pandas as pd

from app.evaluation.full_market_ml.decision_evaluator import evaluate_decision_policy


def policy_fixture(
    *, dates: int = 12, candidates: int = 6, score: float | None = None, net_return: float | None = None
) -> pd.DataFrame:
    sessions = pd.bdate_range("2025-01-02", periods=dates)
    rows = []
    for date_index, trade_date in enumerate(sessions):
        for rank in range(candidates):
            current_score = score if score is not None else 1.0 - rank * 0.1
            current_return = net_return if net_return is not None else 0.10 - rank * 0.04
            rows.append(
                {
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "symbol": f"{date_index:02d}{rank:04d}",
                    "score": current_score,
                    "risk": rank / 10.0,
                    "eligible_for_training_10d": True,
                    "entry_tradeable_10d": True,
                    "net_return_after_cost_10d": current_return,
                    "label_actionable_positive_10d": current_return >= 0.03,
                    "label_severe_negative_10d_v2": current_return <= -0.05,
                    "return_relevance_grade_10d_v2": 4 if current_return >= 0.08 else (2 if current_return >= 0.03 else 0),
                    "mfe_10d": max(current_return, 0.0) + 0.02,
                    "mae_10d": min(current_return, 0.0) - 0.01,
                }
            )
    return pd.DataFrame(rows)


class FullMarketMLDecisionEvaluatorTests(unittest.TestCase):
    def test_rolling_portfolio_never_exceeds_one_gross_exposure(self):
        result = evaluate_decision_policy(
            policy_fixture(), score_col="score", risk_col="risk", selection_threshold=None
        )

        self.assertLessEqual(result.rolling_portfolio["max_gross_exposure"], 1.0)
        self.assertGreater(result.rolling_portfolio["closed_trade_count"], 0)
        self.assertGreaterEqual(result.rolling_portfolio["minimum_cash_ratio"], 0.0)

    def test_selective_policy_can_abstain_without_counting_a_failed_pick(self):
        result = evaluate_decision_policy(
            policy_fixture(score=0.2),
            score_col="score",
            risk_col="risk",
            selection_threshold=0.9,
        )

        self.assertEqual(result.selective_topk["selected_date_count"], 0)
        self.assertEqual(result.selective_topk["coverage"], 0.0)
        self.assertEqual(result.rolling_portfolio["closed_trade_count"], 0)
        self.assertEqual(result.rolling_portfolio["cash_ratio"], 1.0)

    def test_forced_topk_selects_exactly_k_valid_rows_per_date(self):
        result = evaluate_decision_policy(
            policy_fixture(dates=3), score_col="score", risk_col="risk", selection_threshold=None
        )

        self.assertEqual(result.forced_topk["selected_date_count"], 3)
        self.assertEqual(result.forced_topk["selected_count"], 15)
        self.assertEqual(result.forced_topk["coverage"], 1.0)

    def test_forced_topk_rejects_a_date_with_too_few_valid_candidates(self):
        with self.assertRaisesRegex(ValueError, "fewer than top_k"):
            evaluate_decision_policy(
                policy_fixture(dates=2, candidates=4),
                score_col="score",
                risk_col="risk",
                selection_threshold=None,
            )

    def test_costed_returns_are_not_charged_twice(self):
        result = evaluate_decision_policy(
            policy_fixture(dates=1, candidates=5, net_return=0.10),
            score_col="score",
            risk_col="risk",
            selection_threshold=None,
        )

        self.assertAlmostEqual(result.non_overlapping_portfolio["total_return"], 0.10)
        self.assertAlmostEqual(result.rolling_portfolio["total_return"], 0.01)

    def test_ten_positive_cohorts_do_not_create_a_near_total_loss(self):
        result = evaluate_decision_policy(
            policy_fixture(dates=10, candidates=5, net_return=0.01),
            score_col="score",
            risk_col="risk",
            selection_threshold=None,
        )
        rolling = result.rolling_portfolio

        self.assertTrue(math.isfinite(rolling["total_return"]))
        self.assertGreater(rolling["total_return"], 0.0)
        self.assertGreater(rolling["maximum_drawdown"], -0.05)
        self.assertLessEqual(rolling["max_gross_exposure"], 1.0)

    def test_invalid_or_untradeable_rows_are_not_valid_candidates(self):
        rows = policy_fixture(dates=1, candidates=6)
        rows.loc[0, "entry_tradeable_10d"] = False
        rows.loc[1, "net_return_after_cost_10d"] = None

        with self.assertRaisesRegex(ValueError, "fewer than top_k"):
            evaluate_decision_policy(
                rows, score_col="score", risk_col="risk", selection_threshold=None
            )

    def test_duplicate_date_symbol_rows_are_rejected(self):
        rows = policy_fixture(dates=1, candidates=6)
        rows.loc[1, "symbol"] = rows.loc[0, "symbol"]

        with self.assertRaisesRegex(ValueError, "duplicate trade_date and symbol"):
            evaluate_decision_policy(
                rows, score_col="score", risk_col="risk", selection_threshold=None
            )

    def test_non_boolean_decision_labels_are_rejected(self):
        rows = policy_fixture(dates=1, candidates=6)
        rows["label_actionable_positive_10d"] = rows[
            "label_actionable_positive_10d"
        ].astype(object)
        rows.loc[0, "label_actionable_positive_10d"] = "False"

        with self.assertRaisesRegex(ValueError, "boolean decision labels"):
            evaluate_decision_policy(
                rows, score_col="score", risk_col="risk", selection_threshold=None
            )


if __name__ == "__main__":
    unittest.main()
