from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.shsz_h2_order_flow_evidence import (
    H2_CONTROL_FEATURES,
    H2_FEATURES,
    H2_MATRIX_FEATURES,
    SHSZH2OrderFlowEvidenceError,
    residualize_h2_order_flow_score,
)


class SHSZH2OrderFlowEvidenceTests(unittest.TestCase):
    def test_matrix_contract_contains_every_registered_diagnostic_baseline(self):
        self.assertIn("adjusted_return_60d", H2_MATRIX_FEATURES)
        self.assertIn("adjusted_return_20d", H2_MATRIX_FEATURES)
        self.assertIn("amount_log_rank", H2_MATRIX_FEATURES)

    def test_residualization_removes_a_score_explained_only_by_fixed_controls(self):
        rows = _synthetic_h2_rows()
        for feature in H2_FEATURES:
            rows[feature] = rows["total_mv_log_rank"]

        scored, diagnostics = residualize_h2_order_flow_score(rows)

        self.assertEqual(2, len(diagnostics))
        self.assertTrue(np.allclose(scored["h2_residual_score"].to_numpy(), 0.0, atol=1e-10))
        self.assertTrue((diagnostics["design_rank"] == len(H2_CONTROL_FEATURES) + 1).all())

    def test_residualization_preserves_independent_observed_flow_signal(self):
        rows = _synthetic_h2_rows()
        independent = np.tile(((np.arange(120) * 37) % 120) / 119.0, 2)
        for feature in H2_FEATURES:
            rows[feature] = rows["total_mv_log_rank"] + independent

        scored, _ = residualize_h2_order_flow_score(rows)

        self.assertGreater(float(scored["h2_residual_score"].std()), 0.1)
        self.assertGreater(float(np.corrcoef(scored["h2_residual_score"], independent)[0, 1]), 0.95)

    def test_residualization_rejects_a_rank_deficient_control_design(self):
        rows = _synthetic_h2_rows()
        rows["amount_log_rank"] = rows["total_mv_log_rank"]

        with self.assertRaisesRegex(SHSZH2OrderFlowEvidenceError, "rank deficient"):
            residualize_h2_order_flow_score(rows)


def _synthetic_h2_rows() -> pd.DataFrame:
    rows = []
    for day in ("2025-01-02", "2025-01-03"):
        for index in range(120):
            size = index / 119.0
            rows.append(
                {
                    "trade_date": day,
                    "symbol": f"{index:06d}",
                    "total_mv_log_rank": size,
                    "adjusted_return_20d_rank": ((index * 7) % 120) / 119.0,
                    "amount_log_rank": ((index * 13) % 120) / 119.0,
                    "turnover_rate_rank": ((index * 17) % 120) / 119.0,
                    **{feature: size for feature in H2_FEATURES},
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
