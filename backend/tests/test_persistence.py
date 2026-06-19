import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coach_store import CoachStore


class CoachStorePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CoachStore(str(Path(self.temp_dir.name) / "coach.sqlite3"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_risk_profile_upsert_round_trips_normalized_values(self):
        saved = self.store.upsert_risk_profile(
            user_id="user-a",
            profile={
                "risk_level": "low",
                "horizon_days_min": "3",
                "horizon_days_max": "18",
                "max_position_pct": "8.5",
                "max_industry_pct": "25",
            },
            updated_at="2026-06-19 09:30:00",
        )

        loaded = self.store.get_risk_profile("user-a")

        self.assertEqual(saved["risk_level"], "low")
        self.assertEqual(loaded["risk_level"], "low")
        self.assertEqual(loaded["horizon_days_min"], 3)
        self.assertEqual(loaded["horizon_days_max"], 18)
        self.assertEqual(loaded["max_position_pct"], 8.5)
        self.assertEqual(loaded["max_industry_pct"], 25.0)

    def test_backtest_run_result_json_round_trips_through_store(self):
        result = {
            "run_id": "bt_contract",
            "status": "success",
            "metrics": {"annual_return": 0.12, "max_drawdown": 0.08},
            "trades": [{"symbol": "000001", "side": "buy"}],
        }

        self.store.save_backtest_run(
            run_id="bt_contract",
            user_id="user-a",
            strategy_code="trend_breakout",
            config={"risk_level": "medium"},
            result=result,
            status="success",
            started_at="2026-06-19 09:30:00",
            finished_at="2026-06-19 09:31:00",
        )

        loaded = self.store.get_backtest_run("bt_contract")
        listed = self.store.list_backtest_runs(user_id="user-a", strategy_code="trend_breakout")

        self.assertEqual(loaded, result)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["run_id"], "bt_contract")
        self.assertEqual(listed[0]["result"], result)


if __name__ == "__main__":
    unittest.main()
