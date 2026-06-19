import unittest

from app.evaluation.ranking_diagnostics import build_ranking_diagnostics, factor_correlations


class RankingDiagnosticTests(unittest.TestCase):
    def test_identifies_late_winners_and_early_losers(self):
        rows = [
            {
                "trade_date": "2026-01-02",
                "symbol": "000001",
                "name": "平安银行",
                "rank_no": 1,
                "was_bought": True,
                "return_10d_pct": -6.0,
                "strong_10d": False,
                "tp_sl_path": "sl_before_tp",
                "market_state_tag": "neutral",
                "factor_ranking_score": 88,
            },
            {
                "trade_date": "2026-01-02",
                "symbol": "000002",
                "name": "万科A",
                "rank_no": 18,
                "was_bought": False,
                "return_10d_pct": 22.0,
                "strong_10d": True,
                "tp_sl_path": "tp_before_sl",
                "market_state_tag": "neutral",
                "factor_ranking_score": 62,
            },
        ]

        report = build_ranking_diagnostics(rows, horizon=10)

        self.assertEqual(report["late_winner_samples"][0]["symbol"], "000002")
        self.assertEqual(report["early_loser_samples"][0]["symbol"], "000001")
        self.assertEqual(report["unbought_strong_samples"][0]["symbol"], "000002")
        self.assertIn("neutral", report["market_state_breakdown"])

    def test_factor_correlations_include_pearson_and_spearman(self):
        rows = [
            {"return_5d_pct": 1.0, "factor_ranking_score": 10.0, "market_state_tag": "neutral"},
            {"return_5d_pct": 2.0, "factor_ranking_score": 20.0, "market_state_tag": "neutral"},
            {"return_5d_pct": 3.0, "factor_ranking_score": 30.0, "market_state_tag": "neutral"},
        ]

        correlations = factor_correlations(rows, horizon=5, factor_fields=["factor_ranking_score"])

        self.assertEqual(correlations[0]["factor"], "factor_ranking_score")
        self.assertAlmostEqual(correlations[0]["pearson"], 1.0)
        self.assertAlmostEqual(correlations[0]["spearman"], 1.0)

    def test_buy_trigger_conservatism_counts_unbought_strong_top_candidates(self):
        rows = [
            {"symbol": "000001", "rank_no": 3, "return_5d_pct": 12.0, "strong_5d": True, "was_bought": False, "market_state_tag": "offensive"},
            {"symbol": "000002", "rank_no": 4, "return_5d_pct": 10.0, "strong_5d": True, "was_bought": True, "market_state_tag": "offensive"},
            {"symbol": "000003", "rank_no": 15, "return_5d_pct": 14.0, "strong_5d": True, "was_bought": False, "market_state_tag": "offensive"},
        ]

        report = build_ranking_diagnostics(rows, horizon=5)

        conservatism = report["buy_trigger_conservatism"]
        self.assertEqual(conservatism["unbought_strong_top10_count"], 1)
        self.assertEqual(conservatism["bought_strong_count"], 1)
        self.assertEqual(conservatism["diagnostic_only"], True)


if __name__ == "__main__":
    unittest.main()
