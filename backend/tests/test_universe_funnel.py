import unittest

from app.evaluation.universe_funnel import build_universe_funnel_report


def _stock(symbol, **overrides):
    row = {
        "symbol": symbol,
        "name": f"股票{symbol}",
        "price": 12.0,
        "amount": 120_000_000,
        "pct_change": 1.8,
        "turnover_rate": 4.2,
        "volume_ratio": 1.6,
        "industry": "测试行业",
        "industry_pct_change": 2.1,
        "momentum_score": 68,
        "trend_strength": 72,
        "drawdown_pct": 4.0,
        "money_flow_score": 58,
        "pre_score": 55,
    }
    row.update(overrides)
    return row


class UniverseFunnelTests(unittest.TestCase):
    def test_sparse_full_market_snapshot_blocks_trade_plan(self):
        report = build_universe_funnel_report([_stock("000001")], min_full_universe_count=5000)

        self.assertEqual(report["coverage"]["status"], "insufficient_coverage")
        self.assertFalse(report["coverage"]["can_generate_trade_plan"])
        self.assertEqual(report["counts"]["full_market"], 1)
        self.assertEqual(report["counts"]["basic_filter_pass"], 1)

    def test_funnel_records_layer_counts_and_rejection_reasons(self):
        items = [
            _stock("000001", name="平安银行"),
            _stock("000002", name="ST测试"),
            _stock("000003", price=0.8),
            _stock("000004", amount=2_000_000),
            _stock("000005", pct_change=10.0),
            _stock("000006", trend_strength=84, pct_change=5.2, volume_ratio=2.5),
            _stock("000007", drawdown_pct=1.0, pct_change=0.8, momentum_score=62),
        ]

        report = build_universe_funnel_report(items, min_full_universe_count=5)

        self.assertEqual(report["coverage"]["status"], "ok")
        self.assertTrue(report["coverage"]["can_generate_trade_plan"])
        self.assertEqual(report["counts"]["full_market"], 7)
        self.assertEqual(report["counts"]["basic_filter_pass"], 3)
        self.assertGreaterEqual(report["counts"]["multi_channel_recall"], 2)
        self.assertIn("st_or_delisting", report["rejection_reason_counts"])
        self.assertIn("price_abnormal", report["rejection_reason_counts"])
        self.assertIn("amount_too_low", report["rejection_reason_counts"])
        self.assertIn("limit_move_not_buyable", report["rejection_reason_counts"])
        self.assertIn("trend_breakout", report["channel_counts"])
        self.assertIn("low_drawdown_stable", report["channel_counts"])

    def test_multi_channel_recall_keeps_candidates_not_top_by_single_prescore(self):
        items = [
            _stock("000001", pre_score=95, trend_strength=20, momentum_score=20, amount=80_000_000),
            _stock("000002", pre_score=20, trend_strength=88, momentum_score=82, pct_change=6.0, volume_ratio=3.0),
            _stock("000003", pre_score=18, drawdown_pct=0.5, momentum_score=66, pct_change=0.6),
        ]

        report = build_universe_funnel_report(items, min_full_universe_count=3)
        recalled_symbols = {row["symbol"] for row in report["samples"]["recalled"]} | set(report["diagnostics_by_symbol"].keys())

        self.assertIn("000002", recalled_symbols)
        self.assertIn("000003", recalled_symbols)
        self.assertGreaterEqual(report["counts"]["multi_channel_recall"], 2)


if __name__ == "__main__":
    unittest.main()
