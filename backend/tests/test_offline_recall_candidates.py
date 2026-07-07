import unittest

from app.evaluation.offline_recall_candidates import (
    generate_offline_recall_rows,
    offline_recall_coverage,
)


class SnapshotStoreStub:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.calls = []

    def get_latest_valid_market_snapshot_items(self, trade_date=None, min_count=500):
        self.calls.append({"trade_date": trade_date, "min_count": min_count})
        return self.snapshots.get(trade_date)


def _row(symbol, *, name=None, price=10.0, pct_change=2.0, amount=500_000_000, turnover=4.0, high=10.5, low=9.8, industry="测试"):
    return {
        "symbol": symbol,
        "name": name or f"样本{symbol}",
        "price": price,
        "open": price * 0.98,
        "high": high,
        "low": low,
        "pct_change": pct_change,
        "amount": amount,
        "turnover_rate": turnover,
        "industry": industry,
    }


class OfflineRecallCandidateTests(unittest.TestCase):
    def test_generates_rows_from_same_day_persisted_market_snapshot_only(self):
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": 3,
                    "quality_status": "ok",
                    "items": [
                        _row("000001", amount=900_000_000, turnover=5.0, industry="银行"),
                        _row("000002", name="ST样本", amount=900_000_000, turnover=5.0),
                        _row("900001", amount=900_000_000, turnover=5.0),
                    ],
                }
            }
        )

        result = generate_offline_recall_rows(
            store=store,
            experiment_key="recall_220_deep_150",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-03",
        )

        self.assertEqual(result["coverage"]["requested_dates"], ["2026-07-02", "2026-07-03"])
        self.assertEqual(result["coverage"]["available_dates"], ["2026-07-02"])
        self.assertEqual(result["coverage"]["missing_dates"], ["2026-07-03"])
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["symbol"], "000001")
        self.assertEqual(result["rows"][0]["source"], "offline_recall:recall_220_deep_150")
        self.assertEqual(result["rows"][0]["experiment_key"], "recall_220_deep_150")
        self.assertEqual(result["rows"][0]["rank_no"], 1)
        self.assertGreater(result["rows"][0]["factor_total_score"], 0)

    def test_experiment_size_controls_output_count_without_changing_production(self):
        items = [
            _row("000001", amount=900_000_000, turnover=5.0, industry="银行"),
            _row("000002", amount=800_000_000, turnover=4.0, industry="家电"),
            _row("000003", amount=700_000_000, turnover=3.0, industry="医药"),
            _row("000004", amount=600_000_000, turnover=2.0, industry="科技"),
        ]
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": len(items),
                    "quality_status": "ok",
                    "items": items,
                }
            }
        )

        small = generate_offline_recall_rows(
            store=store,
            experiment_key="recall_220_deep_150",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=2,
        )
        large = generate_offline_recall_rows(
            store=store,
            experiment_key="recall_500_deep_500",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=4,
        )

        self.assertEqual(len(small["rows"]), 2)
        self.assertEqual(len(large["rows"]), 4)
        self.assertEqual(small["experiment"]["recall_size"], 220)
        self.assertEqual(large["experiment"]["recall_size"], 500)

    def test_offline_candidate_rows_include_funnel_layer(self):
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": 1,
                    "quality_status": "ok",
                    "items": [_row("000001", amount=900_000_000, turnover=5.0, industry="银行")],
                }
            }
        )

        result = generate_offline_recall_rows(
            store=store,
            experiment_key="recall_220_deep_150",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
        )

        self.assertEqual(result["rows"][0]["funnel_layer"], "deep_analysis")
        self.assertEqual(result["rows"][0]["recall_channels"], ["production_pre_score"])

    def test_offline_generation_returns_funnel_audit_rows_for_layers(self):
        items = [
            _row("000001", amount=900_000_000, turnover=5.0, industry="银行"),
            _row("000002", amount=800_000_000, turnover=4.0, industry="家电"),
            _row("000003", amount=700_000_000, turnover=3.0, industry="医药"),
        ]
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": len(items),
                    "quality_status": "ok",
                    "items": items,
                }
            }
        )

        result = generate_offline_recall_rows(
            store=store,
            experiment_key="recall_220_deep_150",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=2,
        )

        audit_rows = result["funnel_audit_rows"]
        layer_counts = {}
        for row in audit_rows:
            layer_counts[row["funnel_layer"]] = layer_counts.get(row["funnel_layer"], 0) + 1
        self.assertEqual(layer_counts["prefilter"], 3)
        self.assertEqual(layer_counts["recall"], 3)
        self.assertEqual(layer_counts["deep_analysis"], 2)
        self.assertEqual(result["coverage"]["funnel_summary"]["funnel_audit_row_count"], 8)

    def test_production_cap_recall_reports_industry_cap_losses(self):
        chip_rows = [
            _row(f"000{i:03d}", amount=(2_500_000_000 - i * 10_000_000), turnover=6.0, industry="芯片")
            for i in range(1, 18)
        ]
        other_rows = [
            _row("300101", amount=400_000_000, turnover=3.0, industry="医药"),
            _row("600101", amount=350_000_000, turnover=3.0, industry="银行"),
        ]
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": len(chip_rows) + len(other_rows),
                    "quality_status": "ok",
                    "items": chip_rows + other_rows,
                }
            }
        )

        capped = generate_offline_recall_rows(
            store=store,
            experiment_key="production_cap_240",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
        )
        uncapped = generate_offline_recall_rows(
            store=store,
            experiment_key="no_industry_cap_240",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
        )

        self.assertNotIn("000017", {row["symbol"] for row in capped["rows"]})
        self.assertIn("000017", {row["symbol"] for row in uncapped["rows"]})
        self.assertEqual(capped["coverage"]["funnel_summary"]["industry_cap_rejected_count"], 1)
        self.assertEqual(capped["coverage"]["funnel_summary"]["topn_rejected_count"], 0)
        self.assertEqual(uncapped["coverage"]["funnel_summary"]["industry_cap_rejected_count"], 0)

    def test_multi_channel_union_can_recall_pullback_candidate_not_in_pre_score_top_slice(self):
        items = [
            _row("000001", pct_change=2.5, amount=900_000_000, turnover=7.0, high=10.9, low=9.7, industry="强势"),
            _row("000002", pct_change=2.3, amount=850_000_000, turnover=6.5, high=10.8, low=9.7, industry="强势"),
            _row("000003", pct_change=-1.8, amount=450_000_000, turnover=3.0, high=10.2, low=9.7, industry="修复"),
        ]
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": len(items),
                    "quality_status": "ok",
                    "items": items,
                }
            }
        )

        pre_score = generate_offline_recall_rows(
            store=store,
            experiment_key="recall_220_deep_150",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=2,
        )
        union = generate_offline_recall_rows(
            store=store,
            experiment_key="multi_channel_union",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=3,
        )

        self.assertNotIn("000003", {row["symbol"] for row in pre_score["rows"]})
        self.assertIn("000003", {row["symbol"] for row in union["rows"]})
        recalled = next(row for row in union["rows"] if row["symbol"] == "000003")
        self.assertIn("pullback_repair", recalled["recall_channels"])

    def test_weighted_channel_rerank_promotes_multi_channel_strength_over_single_pre_score(self):
        items = [
            _row("000001", pct_change=2.5, amount=2_000_000_000, turnover=10.0, high=10.5, low=9.5, industry="高预评"),
            _row("000002", pct_change=6.0, amount=1_500_000_000, turnover=8.0, high=10.5, low=9.5, industry="量价主题"),
        ]
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": len(items),
                    "quality_status": "ok",
                    "items": items,
                }
            }
        )

        union = generate_offline_recall_rows(
            store=store,
            experiment_key="multi_channel_union",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=2,
        )
        reranked = generate_offline_recall_rows(
            store=store,
            experiment_key="rerank_channel_blend_balanced",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=2,
        )

        self.assertEqual([row["symbol"] for row in union["rows"]], ["000001", "000002"])
        self.assertEqual([row["symbol"] for row in reranked["rows"]], ["000002", "000001"])
        leader = reranked["rows"][0]
        self.assertEqual(leader["experiment_key"], "rerank_channel_blend_balanced")
        self.assertGreater(leader["factor_continuation_score"], reranked["rows"][1]["factor_continuation_score"])
        self.assertGreater(leader["factor_theme_rank_score"], reranked["rows"][1]["factor_theme_rank_score"])

    def test_medium_recall_keeps_formerly_hard_filtered_boundary_candidates(self):
        items = [
            _row("000101", amount=60_000_000, turnover=2.4, pct_change=3.2, price=12.0, industry="低成交"),
            _row("000102", amount=500_000_000, turnover=0.3, pct_change=2.6, price=10.0, industry="低换手"),
            _row("000103", amount=1_200_000_000, turnover=30.0, pct_change=5.5, price=20.0, industry="高换手"),
            _row("000104", amount=800_000_000, turnover=6.0, pct_change=18.0, price=18.0, industry="强波动"),
            _row("000105", amount=700_000_000, turnover=4.0, pct_change=4.0, price=1.2, industry="低价"),
            _row("000106", name="ST风险样本", amount=900_000_000, turnover=4.0, pct_change=2.0, price=8.0),
        ]
        store = SnapshotStoreStub(
            {
                "2026-07-02": {
                    "trade_date": "2026-07-02",
                    "source": "a_share_snapshot",
                    "snapshot_count": len(items),
                    "quality_status": "ok",
                    "items": items,
                }
            }
        )

        result = generate_offline_recall_rows(
            store=store,
            experiment_key="recall_220_deep_150",
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-07-02",
            end_date="2026-07-02",
            max_rows_per_day=10,
        )

        symbols = {row["symbol"] for row in result["rows"]}
        self.assertTrue({"000101", "000102", "000103", "000104", "000105"}.issubset(symbols))
        self.assertNotIn("000106", symbols)

    def test_offline_recall_coverage_requires_same_day_market_snapshot(self):
        coverage = offline_recall_coverage(
            requested_dates=["2026-07-02", "2026-07-03"],
            available_dates=["2026-07-02"],
        )

        self.assertEqual(coverage["coverage_status"], "partial")
        self.assertEqual(coverage["missing_dates"], ["2026-07-03"])


if __name__ == "__main__":
    unittest.main()
