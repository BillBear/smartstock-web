import sys
import tempfile
import unittest
import importlib
import sqlite3
from pathlib import Path

from sqlalchemy import text

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

    def test_sqlite_to_postgres_migration_script_imports_without_psycopg2(self):
        module = importlib.import_module("scripts.migrate_sqlite_to_postgres")

        self.assertTrue(callable(module.migrate))
        self.assertTrue(callable(module.fetch_all))

    def test_existing_sqlite_pick_snapshots_schema_gets_risk_level_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "coach.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE pick_snapshots (
                    pick_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    name TEXT,
                    strategy_code TEXT,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            conn.close()

            store = CoachStore(str(db_path))
            with store.engine.connect() as conn:
                columns = [row._mapping["name"] for row in conn.execute(text("PRAGMA table_info(pick_snapshots)")).fetchall()]

            self.assertIn("risk_level", columns)

    def test_list_pick_snapshot_dates_returns_recent_distinct_dates(self):
        self.store.upsert_pick_snapshots(
            user_id="default",
            trade_date="2026-06-17",
            strategy_code="trend_breakout",
            risk_level="medium",
            picks=[
                {
                    "pick_id": "2026-06-17-000001-S1",
                    "symbol": "000001",
                    "name": "平安银行",
                    "rank_no": 1,
                }
            ],
        )
        self.store.upsert_pick_snapshots(
            user_id="default",
            trade_date="2026-06-18",
            strategy_code="trend_breakout",
            risk_level="medium",
            picks=[
                {
                    "pick_id": "2026-06-18-000001-S1",
                    "symbol": "000001",
                    "name": "平安银行",
                    "rank_no": 1,
                },
                {
                    "pick_id": "2026-06-18-000333-S1",
                    "symbol": "000333",
                    "name": "美的集团",
                    "rank_no": 2,
                },
            ],
        )

        dates = self.store.list_pick_snapshot_dates(user_id="default", limit=30)

        self.assertEqual(dates, ["2026-06-18", "2026-06-17"])


if __name__ == "__main__":
    unittest.main()
