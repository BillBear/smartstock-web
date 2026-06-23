import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coach_service import CoachService
from app.services.coach_store import CoachStore


def sample_pick(trade_date="2026-06-18", symbol="000001", rank_no=1):
    return {
        "pick_id": f"{trade_date}-{symbol}-S1",
        "symbol": symbol,
        "name": "平安银行" if symbol == "000001" else symbol,
        "rank_no": rank_no,
        "action": "buy",
        "up_prob": 0.62,
        "dd_prob": 0.24,
        "expected_return_pct": 5.2,
        "entry_range": [10.0, 10.2],
        "take_profit": 11.4,
        "stop_loss": 9.3,
        "position_pct": 5.0,
        "score_breakdown": {"total": 82.0},
        "decision": {"grade": "A", "mode": "paper_only", "summary": "测试快照"},
        "probability_model": {"label": "规则代理概率", "calibrated": False},
        "evidence_summary": {"strategy_code": "trend_breakout", "state_tag": "neutral"},
    }


class NonTradingPreparationModeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CoachStore(str(Path(self.temp_dir.name) / "coach.sqlite3"))
        self.service = CoachService(data_source_manager=None, store=self.store)

    def tearDown(self):
        self.temp_dir.cleanup()

    def save_snapshot(self, trade_date="2026-06-18"):
        self.store.upsert_pick_snapshots(
            user_id="default",
            trade_date=trade_date,
            strategy_code="trend_breakout",
            risk_level="medium",
            picks=[
                sample_pick(trade_date=trade_date, symbol="000001", rank_no=1),
                sample_pick(trade_date=trade_date, symbol="000333", rank_no=2),
            ],
        )

    def test_cached_only_uses_previous_snapshot_for_non_trading_preparation(self):
        self.save_snapshot("2026-06-18")

        result = self.service.get_cached_today_picks(
            max_count=5,
            user_id="default",
            requested_date="2026-06-19",
        )

        self.assertEqual(result["trade_date"], "2026-06-18")
        self.assertEqual([pick["symbol"] for pick in result["picks"]], ["000001", "000333"])
        self.assertEqual(result["snapshot_dates"], ["2026-06-18"])
        context = result["calendar_context"]
        self.assertEqual(context["mode"], "preparation")
        self.assertEqual(context["requested_date"], "2026-06-19")
        self.assertEqual(context["effective_trade_date"], "2026-06-18")
        self.assertFalse(context["is_trading_day"])
        self.assertEqual(context["signal_age_days"], 1)
        self.assertFalse(context["actions"]["can_refresh"])
        self.assertFalse(context["actions"]["can_paper_buy"])
        self.assertTrue(context["actions"]["can_add_watch"])

    def test_cached_only_historical_mode_reads_requested_snapshot_date(self):
        self.save_snapshot("2026-06-17")
        self.save_snapshot("2026-06-18")

        result = self.service.get_cached_today_picks(
            max_count=5,
            user_id="default",
            requested_date="2026-06-19",
            trade_date="20260617",
        )

        self.assertEqual(result["trade_date"], "2026-06-17")
        self.assertEqual(result["calendar_context"]["mode"], "historical")
        self.assertEqual(result["calendar_context"]["effective_trade_date"], "2026-06-17")
        self.assertEqual(result["snapshot_dates"], ["2026-06-18", "2026-06-17"])

    def test_cached_only_same_day_snapshot_keeps_trading_mode(self):
        self.save_snapshot("2026-06-18")

        result = self.service.get_cached_today_picks(
            max_count=5,
            user_id="default",
            requested_date="2026-06-18",
        )

        self.assertEqual(result["trade_date"], "2026-06-18")
        self.assertEqual(result["calendar_context"]["mode"], "trading")
        self.assertTrue(result["calendar_context"]["actions"]["can_refresh"])
        self.assertTrue(result["calendar_context"]["actions"]["can_paper_buy"])

    def test_cached_only_trading_day_without_current_snapshot_allows_refresh_but_blocks_stale_paper_buy(self):
        self.service._is_recommendation_trading_day = lambda date_text: date_text == "2026-06-22"
        self.save_snapshot("2026-06-17")

        result = self.service.get_cached_today_picks(
            max_count=5,
            user_id="default",
            requested_date="2026-06-22",
        )

        self.assertEqual(result["trade_date"], "2026-06-17")
        self.assertEqual([pick["symbol"] for pick in result["picks"]], ["000001", "000333"])
        context = result["calendar_context"]
        self.assertEqual(context["mode"], "trading")
        self.assertEqual(context["requested_date"], "2026-06-22")
        self.assertEqual(context["effective_trade_date"], "2026-06-22")
        self.assertEqual(context["snapshot_trade_date"], "2026-06-17")
        self.assertTrue(context["is_trading_day"])
        self.assertTrue(context["actions"]["can_refresh"])
        self.assertFalse(context["actions"]["can_paper_buy"])
        self.assertTrue(context["actions"]["can_add_watch"])

    def test_cached_only_without_snapshots_returns_empty_preparation_context(self):
        result = self.service.get_cached_today_picks(
            max_count=5,
            user_id="default",
            requested_date="2026-06-19",
        )

        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["picks"], [])
        self.assertEqual(result["snapshot_dates"], [])
        self.assertEqual(result["calendar_context"]["mode"], "preparation")
        self.assertIsNone(result["calendar_context"]["effective_trade_date"])
        self.assertIn("暂无候选池快照", result["calendar_context"]["message"])

    def test_smart_screen_summary_exposes_calendar_context_and_snapshot_dates(self):
        self.save_snapshot("2026-06-18")

        result = self.service.get_smart_screen_summary(
            user_id="default",
            risk_level="medium",
            requested_date="2026-06-19",
        )

        self.assertEqual(result["calendar_context"]["mode"], "preparation")
        self.assertEqual(result["snapshot_dates"], ["2026-06-18"])
        self.assertEqual(result["top_picks"][0]["symbol"], "000001")


class RefreshEndpointGuardTests(unittest.TestCase):
    def test_non_trading_refresh_is_rejected_without_generating_picks(self):
        os.environ["COACH_DB_URL"] = str(Path(tempfile.gettempdir()) / "smartstock-test-coach.sqlite3")
        from app.core.config import settings

        settings.COACH_DB_URL = os.environ["COACH_DB_URL"]
        from app import main as app_main

        class StubCoachService:
            def resolve_pick_calendar_context(self, **kwargs):
                return {
                    "mode": "preparation",
                    "requested_date": "2026-06-19",
                    "effective_trade_date": "2026-06-18",
                    "is_trading_day": False,
                    "signal_age_days": 1,
                    "message": "今日非交易日，展示最近有效交易日候选池，仅供观察准备。",
                    "actions": {
                        "can_refresh": False,
                        "can_paper_buy": False,
                        "can_add_watch": True,
                    },
                }

            def list_pick_snapshot_dates(self, **kwargs):
                return ["2026-06-18"]

            def get_today_picks(self, **kwargs):
                raise AssertionError("non-trading refresh must not generate picks")

        original_service = app_main.coach_service
        app_main.coach_service = StubCoachService()
        try:
            response = asyncio.run(
                app_main.coach_picks_refresh(
                    max_count=30,
                    risk_level="medium",
                    user_id="default",
                    requested_date="2026-06-19",
                )
            )
        finally:
            app_main.coach_service = original_service

        self.assertFalse(response.data["accepted"])
        self.assertEqual(response.data["reason"], "non_trading_day")
        self.assertEqual(response.data["calendar_context"]["mode"], "preparation")


if __name__ == "__main__":
    unittest.main()
