from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.risk_model import apply_fixed_risk_gate, run_risk_oof
from tests.test_full_market_ml_ablation import _fixture


class FullMarketMLRiskModelTests(unittest.TestCase):
    def test_severe_risk_model_is_evaluated_separately_from_alpha_score(self):
        rows, plan = _fixture()
        rows["mae_10d"] = rows["severe_negative_10d"].map({True: -0.12, False: -0.01})

        result = run_risk_oof(rows, plan, ("signal",))

        self.assertGreater(result["metrics"]["A"]["auc"], 0.9)
        self.assertTrue(result["metrics"]["A"]["decile_monotonic"])
        self.assertIn("risk_probability", result["predictions"])
        self.assertNotIn("alpha_score", result["predictions"])
        self.assertIn("probability_calibrated", result)

    def test_fixed_risk_gate_is_identical_for_all_rankers(self):
        rows = pd.DataFrame(
            [
                {
                    "trade_date": "2025-01-02",
                    "symbol": f"{index + 1:06d}",
                    "risk_probability": index / 10.0,
                    "score_a": index,
                    "score_b": 10 - index,
                }
                for index in range(10)
            ]
        )

        gated = apply_fixed_risk_gate(rows, risk_score_col="risk_probability", keep_fraction=0.8)

        self.assertEqual(gated["risk_eligible"].sum(), 8)
        self.assertEqual(
            set(gated.loc[gated["risk_eligible"], "symbol"]),
            {f"{index + 1:06d}" for index in range(8)},
        )


if __name__ == "__main__":
    unittest.main()
