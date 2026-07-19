import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coach_service import CoachService


class WatchlistRefreshTests(unittest.TestCase):
    def test_watchlist_refreshes_quotes_before_calculating_position_pnl(self):
        class StoreStub:
            def get_latest_pick_actions(self, user_id):
                return {
                    "2026-07-08-000001-S1": {
                        "pick_id": "2026-07-08-000001-S1",
                        "symbol": "000001",
                        "action_type": "paper_buy",
                        "action_price": 10.0,
                        "action_qty": 100.0,
                        "created_at": "2026-07-08 21:00:00",
                    }
                }

            def list_paper_trades(self, user_id, limit=500):
                return []

            def get_pick_snapshot(self, pick_id, user_id):
                return {"snapshot": {"name": "平安银行", "score_breakdown": {"total": 80.0}}}

            def list_open_positions(self, user_id):
                return [
                    {
                        "id": 1,
                        "symbol": "000001",
                        "name": "平安银行",
                        "qty": 100.0,
                        "avg_price": 10.0,
                        "cost_amount": 1000.0,
                        "market_value": 1000.0,
                        "status": "open",
                        "opened_at": "2026-07-08 21:00:00",
                        "updated_at": "2026-07-08 21:00:00",
                    }
                ]

            def list_pick_actions(self, user_id, limit=500):
                return list(self.get_latest_pick_actions(user_id).values())

            def update_position_mark(self, **kwargs):
                return None

            def get_active_strategy_profile(self, user_id):
                return None

        class DataSourceStub:
            def __init__(self):
                self.batch_calls = []

            def _get_cache(self, key):
                return []

            def get_realtime_quotes_batch(self, symbols):
                self.batch_calls.append(list(symbols))
                return {
                    "000001": {
                        "name": "平安银行",
                        "price": 12.0,
                        "update_time": "2026-07-19 15:00:00",
                    }
                }

        data_source = DataSourceStub()
        service = CoachService(data_source_manager=data_source, store=StoreStub())

        result = service.get_watchlist(user_id="default")

        self.assertEqual(data_source.batch_calls, [["000001"]])
        self.assertEqual(result["items"][0]["current_price"], 12.0)
        self.assertEqual(result["items"][0]["unrealized_pnl"], 200.0)
        self.assertEqual(result["portfolio_summary"]["total_unrealized_pnl"], 200.0)


if __name__ == "__main__":
    unittest.main()
