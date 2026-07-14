from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.amount_tail_audit import (
    build_amount_tail_scores,
    build_daily_metric_frame,
    build_quantile_curve,
    circular_block_metric_uplift,
    evaluate_amount_tail_gate,
    simulate_equal_exposure_lot_portfolio,
)


def _signal_rows() -> pd.DataFrame:
    rows = []
    industries = ("bank", "software", "medicine", "energy", "materials")
    for date_index, trade_date in enumerate(("2025-01-02", "2025-01-03")):
        for index in range(20):
            industry = industries[index % len(industries)]
            amount = 10_000_000.0 * (index + 1) * (date_index + 1)
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": f"{index + 1:06d}",
                    "industry_l1": industry,
                    "amount_cny": amount,
                    "circ_mv": 50_000.0 + index * 1_000.0,
                    "adjusted_close": 8.0 + index,
                    "median_amount_20d": amount / (1.0 + (index % 4) * 0.2),
                    "amount_ratio_5d": 1.0 + index / 20.0,
                    "amount_ratio_20d": 0.8 + index / 25.0,
                    "turnover_rate": 0.5 + index / 10.0,
                    "turnover_ratio_20d": 0.7 + index / 30.0,
                    "fold": 1,
                    "quadrant": "A",
                    "market_state": "balanced",
                    "alpha_relevance_grade_10d": 4 if index >= 18 else 0,
                    "alpha_top10_10d": index >= 18,
                    "net_return_after_cost_10d": 0.10 if index >= 18 else -0.01,
                    "severe_negative_10d": index < 2,
                    "mae_10d": -0.02 if index >= 18 else -0.05,
                }
            )
    return pd.DataFrame(rows)


class FullMarketMLAmountTailAuditTests(unittest.TestCase):
    def test_registered_scores_ignore_future_outcome_columns_and_diversify_top5(self):
        rows = _signal_rows()
        original = build_amount_tail_scores(rows)
        changed = rows.copy()
        changed["alpha_relevance_grade_10d"] = 4 - changed["alpha_relevance_grade_10d"]
        changed["net_return_after_cost_10d"] *= -100
        changed["severe_negative_10d"] = ~changed["severe_negative_10d"]

        mutated = build_amount_tail_scores(changed)

        score_columns = [column for column in original if column.startswith("score__")]
        pd.testing.assert_frame_equal(original[score_columns], mutated[score_columns])
        for _, daily in original.groupby("trade_date"):
            selected = daily.sort_values(
                ["score__neutral_amount_tail_diversified", "symbol"],
                ascending=[False, True],
            ).head(5)
            self.assertEqual(selected["industry_l1"].nunique(), 5)

    def test_quantile_curve_is_daily_cross_sectional_and_keeps_tail_direction(self):
        rows = build_amount_tail_scores(_signal_rows())

        curve = build_quantile_curve(
            rows,
            ("score__amount_raw", "score__amount_ratio_5d"),
            quantile_count=4,
        )

        self.assertEqual(set(curve["quantile"]), {1, 2, 3, 4})
        self.assertEqual(set(curve["score"]), {"amount_raw", "amount_ratio_5d"})
        raw = curve.loc[curve["score"].eq("amount_raw")].set_index("quantile")
        self.assertGreater(raw.loc[4, "top10_hit_rate"], raw.loc[1, "top10_hit_rate"])
        self.assertEqual(int(raw["row_count"].sum()), len(rows))

    def test_missing_industry_is_treated_as_an_explicit_diversification_bucket(self):
        rows = _signal_rows()
        rows.loc[rows["symbol"].eq("000020"), "industry_l1"] = pd.NA

        scored = build_amount_tail_scores(rows)

        self.assertTrue(scored["score__neutral_amount_tail_diversified"].notna().all())

    def test_daily_metrics_and_block_bootstrap_use_precomputed_dates(self):
        rows = build_amount_tail_scores(_signal_rows())
        rows["score__random"] = -rows["score__amount_raw"]
        daily = build_daily_metric_frame(
            rows,
            ("score__amount_raw", "score__random"),
        )

        uplift = circular_block_metric_uplift(
            daily,
            candidate="amount_raw",
            baseline="random",
            metric="precision_at_5",
            iterations=100,
            block_length=1,
            seed=17,
        )

        self.assertEqual(len(daily), 4)
        self.assertGreater(uplift["mean_uplift"], 0)
        self.assertGreater(uplift["ci_low"], 0)
        self.assertEqual(uplift["source_date_count"], 2)

    def test_equal_exposure_portfolio_opens_repeated_symbol_as_independent_lots(self):
        signals = pd.DataFrame(
            [
                {"trade_date": "2025-01-02", "symbol": "000001", "score": 1.0},
                {"trade_date": "2025-01-03", "symbol": "000001", "score": 1.0},
            ]
        )
        prices = pd.DataFrame(
            [
                {
                    "trade_date": date,
                    "symbol": "000001",
                    "adjusted_open": 100.0,
                    "adjusted_close": 100.0 + offset,
                    "is_suspended": False,
                    "at_up_limit_open": False,
                }
                for offset, date in enumerate(
                    ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08")
                )
            ]
        )

        result = simulate_equal_exposure_lot_portfolio(
            signals,
            prices,
            score_col="score",
            top_k=1,
            hold_sessions=3,
            commission=0.0,
            slippage=0.0,
            daily_cohort_fraction=0.5,
            per_stock_fraction=0.5,
        )

        self.assertEqual(result["opened_trade_count"], 2)
        self.assertEqual(result["duplicate_position_skip_count"], 0)
        self.assertEqual(result["complete_cohort_count"], 2)

    def test_gate_rejects_a_candidate_when_unseen_retention_fails(self):
        daily = []
        for quadrant, candidate_p5 in (("A", 0.50), ("C", 0.21)):
            for fold in range(1, 6):
                for date_index in range(3):
                    for score, p5, ndcg, value in (
                        ("neutral_amount_tail_diversified", candidate_p5, candidate_p5, candidate_p5),
                        ("amount_raw", 0.30, 0.30, 0.03),
                        ("adjusted_return_20d", 0.25, 0.31, -0.01),
                        ("random", 0.10, 0.10, 0.00),
                    ):
                        daily.append(
                            {
                                "trade_date": f"2025-{fold:02d}-{date_index + 1:02d}",
                                "fold": fold,
                                "quadrant": quadrant,
                                "market_state": "balanced",
                                "score": score,
                                "precision_at_5": p5,
                                "ndcg_at_10": ndcg,
                                "top_5_mean_return": value,
                            }
                        )
        decision = evaluate_amount_tail_gate(
            pd.DataFrame(daily),
            industry_concentration={
                "A": {"neutral_amount_tail_diversified": 0.20},
                "C": {"neutral_amount_tail_diversified": 0.20},
            },
            portfolios={
                "A": {
                    "neutral_amount_tail_diversified": {"maximum_drawdown": -0.05},
                    "amount_raw": {"maximum_drawdown": -0.06},
                },
                "C": {
                    "neutral_amount_tail_diversified": {"maximum_drawdown": -0.04},
                    "amount_raw": {"maximum_drawdown": -0.05},
                },
            },
            bootstrap_iterations=100,
        )

        self.assertEqual(decision["status"], "research_only_failed_gate")
        retention = next(gate for gate in decision["gates"] if gate["name"] == "unseen_stock_retention")
        self.assertFalse(retention["passed"])


if __name__ == "__main__":
    unittest.main()
