from __future__ import annotations

from app.evaluation.full_market_ml.evaluator import (
    bootstrap_uplift,
    evaluate_calibration,
    evaluate_ranking,
    simulate_daily_topk_portfolio,
)
from tests.full_market_ml_fixtures import (
    bootstrap_date_fixture,
    calibration_fixture,
    evaluator_daily_fixture,
    overlapping_portfolio_fixture,
    perfect_two_day_ranking_fixture,
)
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLEvaluatorTests(FullMarketMLTestCase):
    def test_perfect_daily_ranking_has_expected_metrics(self):
        result = evaluate_ranking(perfect_two_day_ranking_fixture(), score_col="score")

        self.assertEqual(result["precision_at_5"], 1.0)
        self.assertEqual(result["ndcg_at_10"], 1.0)
        self.assertEqual(result["mrr"], 1.0)

    def test_ranking_averages_daily_cross_sections_instead_of_pooling_rows(self):
        result = evaluate_ranking(evaluator_daily_fixture(), score_col="score")

        self.assertEqual(result["date_count"], 2)
        self.assertEqual(result["precision_at_5"], 0.5)
        self.assertEqual(result["ndcg_at_10"], 0.5)
        self.assertEqual(result["mrr"], 0.5)

    def test_calibration_uses_ten_equal_count_bins(self):
        result = evaluate_calibration(calibration_fixture(), score_col="score")

        self.assertEqual(result["bin_count"], 10)
        self.assertEqual([row["count"] for row in result["bins"]], [2] * 10)
        self.assertGreater(result["brier"], 0)

    def test_bootstrap_resamples_complete_trade_dates_not_individual_rows(self):
        result = bootstrap_uplift(
            bootstrap_date_fixture(),
            score_col="score",
            baseline_score_col="baseline_score",
            iterations=50,
            seed=17,
        )

        self.assertEqual(result["resample_unit"], "trade_date")
        self.assertEqual(result["source_date_count"], 2)
        self.assertLessEqual(result["precision_at_5_uplift_ci_low"], 0)
        self.assertGreaterEqual(result["precision_at_5_uplift_ci_high"], 0)

    def test_overlapping_top5_cohorts_apply_costs_on_entry_and_exit(self):
        gross = simulate_daily_topk_portfolio(overlapping_portfolio_fixture(), hold_days=2, commission=0.0, slippage=0.0)
        net = simulate_daily_topk_portfolio(overlapping_portfolio_fixture(), hold_days=2, commission=0.0003, slippage=0.001)

        self.assertEqual(net["cohort_count"], 2)
        self.assertEqual(net["closed_trade_count"], 10)
        self.assertLess(net["total_return"], gross["total_return"])
        self.assertAlmostEqual(gross["total_return"], 0.15, places=6)
        expected_net = (((110.0 / 100.0) * 0.999 / 1.001 * 0.9997**2 - 1.0) + ((120.0 / 100.0) * 0.999 / 1.001 * 0.9997**2 - 1.0)) / 2
        self.assertAlmostEqual(net["total_return"], expected_net, places=6)


if __name__ == "__main__":
    import unittest

    unittest.main()
