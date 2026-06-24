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
        "display_mode": "paper_validate",
        "recommendation_schema_version": CoachService.RECOMMENDATION_SCHEMA_VERSION,
        "up_prob": 0.62,
        "dd_prob": 0.24,
        "expected_return_pct": 5.2,
        "entry_range": [10.0, 10.2],
        "take_profit": 11.4,
        "stop_loss": 9.3,
        "position_pct": 5.0,
        "score_breakdown": {"total": 82.0, "ranking_score": 82.0},
        "decision": {"grade": "B", "mode": "paper_only", "summary": "测试快照"},
        "probability_model": {"label": "规则代理概率", "calibrated": False},
        "evidence_summary": {"strategy_code": "trend_breakout", "state_tag": "neutral"},
    }


class NonTradingPreparationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CoachStore(str(Path(self.temp_dir.name) / "coach.sqlite3"))

        class TestCoachService(CoachService):
            recommendation_date = "2026-06-19"
            trading_days = set()

            def _recommendation_trade_date(self):
                return self.recommendation_date

            def _is_recommendation_trading_day(self, date_text):
                return date_text in self.trading_days

            def get_market_state_today(self):
                return {
                    "state_tag": "defensive",
                    "state_score": 45,
                    "summary": "测试市场状态",
                    "reasons": [],
                    "drivers": {},
                    "news_context": {},
                }

            def _build_feedback_adjustment(self, user_id="default"):
                return {"active": False, "reasons": []}

            def _build_feedback_learning_profile(self, user_id="default"):
                return {"active": False, "evaluation_count": 0}

            def _build_paper_probability_calibration(self, user_id="default"):
                return {"calibrated": False}

            def _apply_feedback_learning_to_picks(self, picks, profile):
                return None

            def _apply_paper_probability_calibration(self, picks, calibration):
                return None

            def _apply_holding_management_guard(self, picks, user_id="default"):
                return None

            def _attach_signal_metadata_and_performance(self, picks, trade_date, include_performance=False):
                return None

        self.service = TestCoachService(data_source_manager=None, store=self.store)

    def tearDown(self):
        self.temp_dir.cleanup()

    def save_snapshot(self, trade_date="2026-06-18"):
        self.store.upsert_pick_snapshots(
            user_id="default",
            trade_date=trade_date,
            strategy_code="trend_breakout",
            picks=[
                sample_pick(trade_date=trade_date, symbol="000001", rank_no=1),
                sample_pick(trade_date=trade_date, symbol="000333", rank_no=2),
            ],
        )

    def test_cached_only_non_trading_context_uses_previous_snapshot(self):
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
        self.assertFalse(context["actions"]["can_refresh"])
        self.assertFalse(context["actions"]["can_paper_buy"])
        self.assertTrue(context["actions"]["can_add_watch"])

    def test_smart_screen_summary_exposes_preparation_context(self):
        self.save_snapshot("2026-06-18")

        result = self.service.get_smart_screen_summary(
            user_id="default",
            risk_level="medium",
            requested_date="2026-06-19",
        )

        self.assertEqual(result["trade_date"], "2026-06-18")
        self.assertEqual(result["calendar_context"]["mode"], "preparation")
        self.assertEqual(result["top_picks"][0]["symbol"], "000001")

    def test_trading_day_without_current_snapshot_allows_refresh_but_blocks_stale_paper_buy(self):
        self.service.recommendation_date = "2026-06-22"
        self.service.trading_days = {"2026-06-22"}
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


if __name__ == "__main__":
    unittest.main()
