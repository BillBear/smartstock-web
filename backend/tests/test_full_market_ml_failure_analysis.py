from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.failure_analysis import build_failure_samples


class FullMarketMLFailureAnalysisTests(unittest.TestCase):
    def test_analysis_returns_ranked_losses_missed_leaders_and_concentration(self):
        rows = []
        for date in ("2025-01-02", "2025-01-03"):
            for rank in range(1, 121):
                rows.append(
                    {
                        "trade_date": date,
                        "symbol": f"{rank:06d}",
                        "fold": 1,
                        "quadrant": "A",
                        "industry_l1": "industry-a" if rank <= 5 else "industry-b",
                        "market_state": "balanced",
                        "alpha_target_10d": float(rank),
                        "alpha_relevance_grade_10d": 4 if rank > 108 else 0,
                        "alpha_top10_10d": rank > 108,
                        "net_return_after_cost_10d": -0.10 if rank <= 5 else 0.10,
                        "mae_10d": -0.12 if rank <= 5 else -0.01,
                        "severe_negative_10d": rank <= 5,
                        "score__fixture": float(121 - rank),
                    }
                )

        samples, summary = build_failure_samples(
            pd.DataFrame(rows), baselines=("fixture",), maximum_per_type=20
        )

        self.assertEqual(set(samples["sample_type"]), {"high_ranked_loss", "missed_future_leader"})
        self.assertGreater(summary["sample_type_counts"]["high_ranked_loss"], 0)
        self.assertEqual(summary["industry_concentration"]["A"]["fixture"]["top_industry"], "industry-a")


if __name__ == "__main__":
    unittest.main()
