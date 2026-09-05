import unittest

from app.evaluation.paper_trade_review import summarize_paper_trades


class PaperTradeReviewTests(unittest.TestCase):
    def test_partial_sales_use_weighted_cost_not_winner_selection(self):
        rows = [
            {"id": 1, "symbol": "A", "side": "buy", "price": 10, "qty": 100, "fee": 0, "created_at": "2026-01-01"},
            {"id": 2, "symbol": "A", "side": "buy", "price": 20, "qty": 100, "fee": 0, "created_at": "2026-01-02"},
            {"id": 3, "symbol": "A", "side": "sell", "price": 18, "qty": 50, "fee": 0, "created_at": "2026-01-03"},
            {"id": 4, "symbol": "A", "side": "sell", "price": 12, "qty": 150, "fee": 0, "created_at": "2026-01-04"},
        ]
        result = summarize_paper_trades(rows, commission=0.001, slippage=0)
        self.assertEqual(result["matched_sale_event_count"], 2)
        self.assertEqual(result["completed_position_episode_count"], 1)
        self.assertEqual(result["recorded_gross_realized_pnl"], -300)
        self.assertAlmostEqual(result["estimated_cost_overlay_pnl"], -305.7)
        self.assertEqual(result["sale_events"][0]["cost_price"], 15)
        self.assertTrue(result["recorded_fees_all_zero"])

    def test_orphan_sales_are_reported_not_fabricated_profitable_trades(self):
        result = summarize_paper_trades([{"id": 1, "symbol": "A", "side": "sell", "price": 18, "qty": 50, "fee": 0, "created_at": "2026-01-03"}])
        self.assertEqual(result["matched_sale_event_count"], 0)
        self.assertEqual(len(result["unmatched_sales"]), 1)
        self.assertIsNone(result["recorded_gross_realized_pnl"])


if __name__ == "__main__":
    unittest.main()
