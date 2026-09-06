import unittest

from app.evaluation.paper_trade_review import summarize_paper_trades


class PaperTradeReviewTests(unittest.TestCase):
    def test_execution_audit_keeps_recorded_flows_and_estimated_fees_separate(self):
        import copy
        import app.evaluation.paper_trade_review as module
        from tests.test_swing_replay import CONFIG
        rows = [dict(id=1,symbol='000001',side='buy',price=10,qty=200,fee=1,created_at='2026-07-01'),
                dict(id=2,symbol='000001',side='sell',price=11,qty=100,fee=1,created_at='2026-07-02'),
                dict(id=3,symbol='000002',side='sell',price=5,qty=100,fee=0,created_at='2026-07-03')]
        before = copy.deepcopy(rows)
        self.assertTrue(hasattr(module,'audit_paper_execution'))
        result = module.audit_paper_execution(rows,CONFIG,'default')
        self.assertEqual(rows,before)
        self.assertEqual(result['recorded']['trade_count'],3)
        self.assertEqual(result['recorded']['recorded_gross_realized_pnl'],100)
        self.assertEqual(result['recorded_cash_movement'],-402)
        self.assertEqual(result['recorded']['open_positions_at_cost']['000001']['qty'],100)
        self.assertIsNone(result['account_equity'])
        self.assertFalse(result['strategy_attributable'])
        self.assertLess(result['estimated_research_fee_net_realized_pnl'],98.5)
        self.assertEqual(len(result['fee_comparison']),3)
        with self.assertRaises(ValueError):
            module.audit_paper_execution([dict(rows[0],user_id='another')],CONFIG,'default')

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
