from __future__ import annotations

import pandas as pd
from unittest.mock import patch

from app.evaluation.full_market_ml import evaluator as evaluator_module
from app.evaluation.full_market_ml.evaluator import (
    bootstrap_uplift,
    evaluate_calibration,
    evaluate_ranking,
    simulate_daily_topk_portfolio,
    simulate_daily_mark_to_market_portfolio,
    validate_identical_comparison_rows,
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

    def test_ranking_can_use_an_explicit_alternative_label_contract(self):
        dataset = perfect_two_day_ranking_fixture()
        dataset["return_grade"] = dataset["relevance_grade_10d"]
        original_strong = dataset["label_strong_path_10d"].astype(bool)
        dataset["return_strong"] = ~original_strong
        dataset["return_grade"] = dataset["return_strong"].astype(int) * 4

        result = evaluate_ranking(
            dataset,
            score_col="score",
            grade_col="return_grade",
            strong_col="return_strong",
        )

        self.assertEqual(result["precision_at_5"], 0.0)
        self.assertLess(result["ndcg_at_10"], 1.0)

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
        self.assertEqual(result["bootstrap_method"], "circular_block")
        self.assertEqual(result["block_length"], 10)
        self.assertEqual(result["source_date_count"], 2)
        self.assertLessEqual(result["precision_at_5_uplift_ci_low"], 0)
        self.assertGreaterEqual(result["precision_at_5_uplift_ci_high"], 0)

    def test_bootstrap_uses_explicit_return_label_columns(self):
        dataset = bootstrap_date_fixture()
        dataset["return_relevance_grade_10d"] = [4 if index % 10 == 0 else 0 for index in range(len(dataset))]
        dataset["label_return_top10_10d"] = [index % 10 == 0 for index in range(len(dataset))]

        result = bootstrap_uplift(
            dataset,
            score_col="score",
            baseline_score_col="baseline_score",
            grade_col="return_relevance_grade_10d",
            strong_col="label_return_top10_10d",
            iterations=20,
            seed=17,
        )

        self.assertAlmostEqual(result["precision_at_5_uplift"], 0.2)
        self.assertGreater(result["precision_at_5_uplift_ci_low"], 0.0)

    def test_bootstrap_computes_each_daily_metric_once_before_resampling(self):
        original = evaluator_module._daily_ranking_metrics
        with patch.object(evaluator_module, "_daily_ranking_metrics", wraps=original) as daily_metrics:
            bootstrap_uplift(
                bootstrap_date_fixture(),
                score_col="score",
                baseline_score_col="baseline_score",
                iterations=50,
                seed=17,
            )

        self.assertEqual(daily_metrics.call_count, 4)

    def test_overlapping_top5_cohorts_apply_costs_on_entry_and_exit(self):
        gross = simulate_daily_topk_portfolio(overlapping_portfolio_fixture(), hold_days=2, commission=0.0, slippage=0.0)
        net = simulate_daily_topk_portfolio(overlapping_portfolio_fixture(), hold_days=2, commission=0.0003, slippage=0.001)

        self.assertEqual(net["cohort_count"], 2)
        self.assertEqual(net["closed_trade_count"], 10)
        self.assertLess(net["total_return"], gross["total_return"])
        self.assertAlmostEqual(gross["total_return"], 0.15, places=6)
        expected_net = (((110.0 / 100.0) * 0.999 / 1.001 * 0.9997**2 - 1.0) + ((120.0 / 100.0) * 0.999 / 1.001 * 0.9997**2 - 1.0)) / 2
        self.assertAlmostEqual(net["total_return"], expected_net, places=6)

    def test_portfolio_accepts_canonical_label_execution_fields(self):
        dataset = overlapping_portfolio_fixture().rename(
            columns={"adjusted_next_open": "entry_price", "adjusted_exit_close": "exit_price"}
        )
        dataset["path_ambiguous_10d"] = False

        result = simulate_daily_topk_portfolio(dataset, hold_days=2, commission=0.0, slippage=0.0)

        self.assertEqual(result["closed_trade_count"], 10)
        self.assertAlmostEqual(result["total_return"], 0.15, places=6)

    def test_portfolio_total_return_is_compounded_and_drawdown_is_realized(self):
        dataset = pd.DataFrame(
            [
                {"trade_date": "2025-01-02", "symbol": "000001", "score": 2.0, "entry_price": 100.0, "exit_price": 110.0, "exit_trade_date": "2025-01-03"},
                {"trade_date": "2025-01-03", "symbol": "000002", "score": 2.0, "entry_price": 100.0, "exit_price": 80.0, "exit_trade_date": "2025-01-04"},
            ]
        )

        result = simulate_daily_topk_portfolio(dataset, top_k=1, commission=0.0, slippage=0.0)

        self.assertAlmostEqual(result["total_return"], -0.12, places=6)
        self.assertAlmostEqual(result["maximum_drawdown"], -0.2, places=6)

    def test_ambiguous_or_untradeable_entries_are_not_counted_as_closed_trades(self):
        dataset = pd.DataFrame(
            [
                {"trade_date": "2025-01-02", "symbol": "000001", "score": 2.0, "entry_price": 100.0, "exit_price": 110.0, "exit_trade_date": "2025-01-03", "path_ambiguous_10d": True},
                {"trade_date": "2025-01-03", "symbol": "000002", "score": 2.0, "entry_price": 100.0, "exit_price": 110.0, "exit_trade_date": "2025-01-04", "entry_tradeable": False},
            ]
        )

        result = simulate_daily_topk_portfolio(dataset, top_k=1, commission=0.0, slippage=0.0)

        self.assertEqual(result["closed_trade_count"], 0)
        self.assertEqual(result["ambiguous_exit_count"], 1)
        self.assertEqual(result["untradeable_entry_count"], 1)

    def test_mark_to_market_drawdown_uses_intrahorizon_daily_prices(self):
        signals = pd.DataFrame(
            [{"trade_date": "2025-01-02", "symbol": "000001", "score": 1.0}]
        )
        prices = pd.DataFrame(
            [
                {"trade_date": "2025-01-02", "symbol": "000001", "adjusted_open": 100.0, "adjusted_close": 100.0, "is_suspended": False, "at_up_limit_open": False},
                {"trade_date": "2025-01-03", "symbol": "000001", "adjusted_open": 100.0, "adjusted_close": 100.0, "is_suspended": False, "at_up_limit_open": False},
                {"trade_date": "2025-01-06", "symbol": "000001", "adjusted_open": 50.0, "adjusted_close": 50.0, "is_suspended": False, "at_up_limit_open": False},
                {"trade_date": "2025-01-07", "symbol": "000001", "adjusted_open": 110.0, "adjusted_close": 110.0, "is_suspended": False, "at_up_limit_open": False},
            ]
        )

        result = simulate_daily_mark_to_market_portfolio(
            signals,
            prices,
            score_col="score",
            top_k=1,
            hold_sessions=3,
            commission=0.0,
            slippage=0.0,
            daily_cohort_fraction=1.0,
            per_stock_cap=1.0,
        )

        self.assertAlmostEqual(result["total_return"], 0.10, places=6)
        self.assertLessEqual(result["maximum_drawdown"], -0.49)

    def test_mark_to_market_portfolio_prevents_duplicate_simultaneous_positions(self):
        signals = pd.DataFrame(
            [
                {"trade_date": "2025-01-02", "symbol": "000001", "score": 1.0},
                {"trade_date": "2025-01-03", "symbol": "000001", "score": 1.0},
            ]
        )
        dates = ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08")
        prices = pd.DataFrame(
            [
                {"trade_date": date, "symbol": "000001", "adjusted_open": 100.0, "adjusted_close": 100.0, "is_suspended": False, "at_up_limit_open": False}
                for date in dates
            ]
        )

        result = simulate_daily_mark_to_market_portfolio(
            signals, prices, score_col="score", top_k=1, hold_sessions=3,
            commission=0.0, slippage=0.0, daily_cohort_fraction=0.5, per_stock_cap=0.5,
        )

        self.assertEqual(result["opened_trade_count"], 1)
        self.assertEqual(result["duplicate_position_skip_count"], 1)

    def test_controlled_comparison_rejects_different_rows_or_risk_masks(self):
        left = pd.DataFrame(
            [{"trade_date": "2025-01-02", "symbol": "000001", "risk_eligible": True}]
        )
        right = left.copy()
        right.loc[0, "risk_eligible"] = False

        with self.assertRaisesRegex(ValueError, "risk mask"):
            validate_identical_comparison_rows({"left": left, "right": right})


if __name__ == "__main__":
    import unittest

    unittest.main()
