import unittest

from app.evaluation.ranking_quality_experiments import run_ranking_experiments


def _row(trade_date, symbol, rank_no, dd_prob, risk_adjusted, return_10d, action="watch", source="TuShare"):
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "rank_no": rank_no,
        "dd_prob": dd_prob,
        "risk_adjusted": risk_adjusted,
        "action": action,
        "history_source": source,
        "tradable_label": "tradable",
        "future_return_5d": return_10d / 2,
        "future_return_10d": return_10d,
        "future_return_20d": return_10d * 1.5,
    }


class RankingQualityExperimentTests(unittest.TestCase):
    def test_experiment_c_applies_existing_veto_without_backfilling(self):
        rows = [
            _row("2026-07-01", "000001", 1, 0.50, 90, -12, action="buy"),
            _row("2026-07-01", "000002", 2, 0.20, 70, 8, action="watch"),
            _row("2026-07-01", "000003", 3, 0.25, 80, 6, action="watch"),
            _row("2026-07-02", "000004", 1, 0.45, 85, -10, action="buy"),
            _row("2026-07-02", "000005", 2, 0.20, 65, 9, action="watch"),
            _row("2026-07-02", "000006", 3, 0.25, 75, 7, action="watch", source="AKShare"),
        ]

        result = run_ranking_experiments(rows, dd_prob_veto_threshold=0.30, threshold_source="existing_medium_trend_breakout_buy_rule", bootstrap_iterations=100, bootstrap_seed=7)

        experiment_c = result["segments"]["all_sources"]["all_candidates"]["experiments"]["C_dd_prob_veto"]
        self.assertEqual(experiment_c["status"], "available")
        self.assertEqual(experiment_c["coverage"]["accepted_row_count"], 4)
        self.assertEqual(experiment_c["selection_by_date"]["2026-07-01"], ["000002", "000003"])
        self.assertEqual(experiment_c["metrics"]["10"]["top_k"]["3"]["candidate_count"], 2)
        self.assertGreater(experiment_c["paired_comparison"]["mean_daily_top5_return_difference"], 0)
        self.assertIn("tushare_only", result["segments"])

    def test_experiment_c_is_unavailable_without_a_single_existing_threshold(self):
        rows = [_row("2026-07-01", "000001", 1, 0.20, 70, 5)]

        result = run_ranking_experiments(rows, dd_prob_veto_threshold=None, threshold_source=None, bootstrap_iterations=20, bootstrap_seed=7)

        experiment_c = result["segments"]["all_sources"]["all_candidates"]["experiments"]["C_dd_prob_veto"]
        self.assertEqual(experiment_c["status"], "unavailable")
        self.assertIn("threshold", experiment_c["reason"])


if __name__ == "__main__":
    unittest.main()
