import unittest
import tempfile
from pathlib import Path

import pandas as pd

from app.evaluation.ranking_replay import (
    RankingReplayService,
    attach_forward_labels,
    normalize_candidate_row,
    replay_coverage_summary,
)
from app.services.coach_store import CoachStore


class FakeHistoryManager:
    def get_history_data(self, symbol, days=120):
        return pd.DataFrame(
            [
                {"date": "2026-01-05", "open": 10.0, "high": 10.6, "low": 9.9, "close": 10.4, "volume": 1000, "amount": 200000000},
                {"date": "2026-01-06", "open": 10.4, "high": 11.0, "low": 10.3, "close": 10.9, "volume": 1000, "amount": 210000000},
                {"date": "2026-01-07", "open": 10.9, "high": 11.3, "low": 10.8, "close": 11.2, "volume": 1000, "amount": 220000000},
                {"date": "2026-01-08", "open": 11.2, "high": 11.6, "low": 11.1, "close": 11.5, "volume": 1000, "amount": 230000000},
                {"date": "2026-01-09", "open": 11.5, "high": 12.0, "low": 11.4, "close": 11.9, "volume": 1000, "amount": 240000000},
            ]
        )


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def list_pick_snapshots(self, strategy_code, risk_level, trade_date):
        return self.rows.get(trade_date, [])


class RankingReplayTests(unittest.TestCase):
    def test_normalize_candidate_row_preserves_rank_and_factors(self):
        row = normalize_candidate_row(
            trade_date="2026-01-02",
            pick={
                "symbol": "000001",
                "name": "平安银行",
                "rank_no": 12,
                "score": 71.5,
                "ranking_score": 83.2,
                "swing_score": 76.0,
                "continuation_score": 65.0,
                "risk_control_score": 80.0,
                "leader_score": 70.0,
                "theme_rank_score": 61.0,
                "up_prob": 0.68,
                "dd_prob": 0.18,
                "expected_edge_pct": 6.2,
                "profit_factor_proxy": 1.4,
                "score_breakdown": {"total": 71.5, "trend": 69.0, "money_flow": 58.0, "turnover_liquidity": 77.0},
                "ranking_diagnostics": {"signal_features": {"volume_ratio_20": 1.8, "rsi": 55.0, "ma20_gap_pct": 3.2}},
            },
            market_state={"state_tag": "offensive", "state_score": 68.4},
            action={"action_type": "ignored", "created_at": "2026-01-02 10:10:00"},
            source="pick_history",
        )

        self.assertEqual(row["trade_date"], "2026-01-02")
        self.assertEqual(row["rank_no"], 12)
        self.assertEqual(row["market_state_tag"], "offensive")
        self.assertFalse(row["was_bought"])
        self.assertEqual(row["factor_ranking_score"], 83.2)
        self.assertEqual(row["factor_volume_ratio_20"], 1.8)
        self.assertEqual(row["factor_total_score"], 71.5)

    def test_replay_coverage_summary_blocks_when_no_dates_available(self):
        summary = replay_coverage_summary(requested_dates=["2026-01-02"], available_dates=[])

        self.assertEqual(summary["coverage_status"], "blocked")
        self.assertEqual(summary["covered_date_count"], 0)
        self.assertEqual(summary["requested_date_count"], 1)

    def test_replay_coverage_summary_marks_partial_coverage(self):
        summary = replay_coverage_summary(
            requested_dates=["2026-01-02", "2026-01-05"],
            available_dates=["2026-01-02"],
        )

        self.assertEqual(summary["coverage_status"], "partial")
        self.assertEqual(summary["missing_dates"], ["2026-01-05"])

    def test_attach_forward_labels_uses_future_history_only(self):
        rows = [{"trade_date": "2026-01-02", "symbol": "000001", "rank_no": 1}]

        labeled = attach_forward_labels(rows, FakeHistoryManager(), label_config={"horizons": [3, 5]})

        self.assertEqual(labeled[0]["tradability_status"], "tradable")
        self.assertIn("return_3d_pct", labeled[0])
        self.assertIn("strong_5d", labeled[0])
        self.assertGreater(labeled[0]["return_5d_pct"], 15.0)

    def test_replay_service_uses_store_snapshots_without_live_candidate_refresh(self):
        store = FakeStore(
            {
                "2026-01-02": [
                    {
                        "symbol": "000001",
                        "rank_no": 1,
                        "market_state": {"state_tag": "neutral"},
                        "user_action": {"action_type": "paper_buy", "created_at": "2026-01-02 09:40:00"},
                    }
                ]
            }
        )
        service = RankingReplayService(store=store, data_source_manager=FakeHistoryManager())

        result = service.replay(
            strategy_code="trend_breakout",
            risk_level="medium",
            start_date="2026-01-02",
            end_date="2026-01-03",
        )

        self.assertEqual(result["coverage"]["coverage_status"], "partial")
        self.assertEqual(len(result["rows"]), 1)
        self.assertTrue(result["rows"][0]["was_bought"])
        self.assertEqual(result["rows"][0]["source"], "pick_snapshot")

    def test_replay_service_reads_real_coach_store_snapshots_and_actions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CoachStore(str(Path(temp_dir) / "coach.sqlite3"))
            store.upsert_pick_snapshots(
                user_id="default",
                trade_date="2026-01-02",
                strategy_code="trend_breakout",
                picks=[
                    {
                        "pick_id": "pick-20260102-000001",
                        "symbol": "000001",
                        "name": "平安银行",
                        "rank_no": 4,
                        "score_breakdown": {"total": 72.0},
                    }
                ],
            )
            store.append_pick_action(
                {
                    "user_id": "default",
                    "pick_id": "pick-20260102-000001",
                    "symbol": "000001",
                    "action_type": "paper_buy",
                    "action_price": 10.1,
                    "action_qty": 100,
                    "note": "fixture buy",
                    "created_at": "2026-01-02 09:40:00",
                }
            )
            service = RankingReplayService(store=store, data_source_manager=FakeHistoryManager(), user_id="default")

            result = service.replay(
                strategy_code="trend_breakout",
                risk_level="medium",
                start_date="2026-01-02",
                end_date="2026-01-02",
            )

            self.assertEqual(result["coverage"]["coverage_status"], "complete")
            self.assertEqual(len(result["rows"]), 1)
            self.assertEqual(result["rows"][0]["pick_id"], "pick-20260102-000001")
            self.assertTrue(result["rows"][0]["was_bought"])
            self.assertEqual(result["rows"][0]["buy_action_time"], "2026-01-02 09:40:00")


if __name__ == "__main__":
    unittest.main()
