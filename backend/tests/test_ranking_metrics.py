import unittest

from app.evaluation.ranking_metrics import evaluate_daily_ranking, rank_percentile_return_curve


class RankingMetricTests(unittest.TestCase):
    def test_precision_recall_ndcg_mrr_and_topk_return(self):
        rows = [
            {"symbol": "000001", "rank_no": 1, "strong_5d": False, "return_5d_pct": -2.0, "tradability_status": "tradable"},
            {"symbol": "000002", "rank_no": 2, "strong_5d": True, "return_5d_pct": 9.0, "tradability_status": "tradable"},
            {"symbol": "000003", "rank_no": 3, "strong_5d": False, "return_5d_pct": 1.0, "tradability_status": "tradable"},
            {"symbol": "000004", "rank_no": 11, "strong_5d": True, "return_5d_pct": 14.0, "tradability_status": "tradable"},
        ]

        metrics = evaluate_daily_ranking(rows, horizon=5)

        self.assertEqual(metrics["tradable_candidate_count"], 4)
        self.assertAlmostEqual(metrics["precision_at_3"], 1 / 3, places=6)
        self.assertAlmostEqual(metrics["precision_at_5"], 1 / 4, places=6)
        self.assertAlmostEqual(metrics["precision_at_10"], 1 / 4, places=6)
        self.assertAlmostEqual(metrics["recall_at_10"], 1 / 2, places=6)
        self.assertAlmostEqual(metrics["mrr"], 1 / 2, places=6)
        self.assertAlmostEqual(metrics["top_3_avg_return_pct"], (-2.0 + 9.0 + 1.0) / 3, places=6)
        self.assertGreater(metrics["ndcg_at_10"], 0)

    def test_no_strong_candidates_returns_zero_recall_and_mrr(self):
        rows = [
            {"symbol": "000001", "rank_no": 1, "strong_10d": False, "return_10d_pct": -1.0, "tradability_status": "tradable"},
            {"symbol": "000002", "rank_no": 2, "strong_10d": False, "return_10d_pct": 2.0, "tradability_status": "tradable"},
        ]

        metrics = evaluate_daily_ranking(rows, horizon=10)

        self.assertEqual(metrics["recall_at_10"], 0.0)
        self.assertEqual(metrics["mrr"], 0.0)
        self.assertEqual(metrics["strong_candidate_count"], 0)

    def test_untradable_candidates_are_excluded_by_default(self):
        rows = [
            {"symbol": "000001", "rank_no": 1, "strong_3d": True, "return_3d_pct": 12.0, "tradability_status": "limit_up_entry_blocked"},
            {"symbol": "000002", "rank_no": 2, "strong_3d": True, "return_3d_pct": 8.0, "tradability_status": "tradable"},
        ]

        metrics = evaluate_daily_ranking(rows, horizon=3)

        self.assertEqual(metrics["candidate_count"], 2)
        self.assertEqual(metrics["tradable_candidate_count"], 1)
        self.assertEqual(metrics["precision_at_3"], 1.0)
        self.assertEqual(metrics["mrr"], 1 / 2)

    def test_rank_percentile_return_curve_uses_decile_buckets(self):
        rows = [
            {"symbol": f"{idx:06d}", "rank_no": idx, "return_20d_pct": float(idx), "tradability_status": "tradable"}
            for idx in range(1, 11)
        ]

        curve = rank_percentile_return_curve(rows, horizon=20, buckets=5)

        self.assertEqual(len(curve), 5)
        self.assertEqual(curve[0]["bucket"], 1)
        self.assertEqual(curve[0]["row_count"], 2)
        self.assertAlmostEqual(curve[0]["avg_return_20d_pct"], 1.5)
        self.assertEqual(curve[-1]["row_count"], 2)
        self.assertAlmostEqual(curve[-1]["avg_return_20d_pct"], 9.5)

    def test_ndcg_at_10_does_not_credit_rank_outside_top_10(self):
        rows = [
            {"symbol": "000001", "rank_no": 1, "strong_5d": False, "return_5d_pct": 0.0, "tradability_status": "tradable"},
            {"symbol": "000002", "rank_no": 11, "strong_5d": True, "return_5d_pct": 30.0, "tradability_status": "tradable"},
        ]

        metrics = evaluate_daily_ranking(rows, horizon=5)

        self.assertEqual(metrics["recall_at_10"], 0.0)
        self.assertEqual(metrics["ndcg_at_10"], 0.0)


if __name__ == "__main__":
    unittest.main()
