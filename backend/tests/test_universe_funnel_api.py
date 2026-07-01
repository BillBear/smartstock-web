import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["COACH_DB_URL"] = str(Path(_TEMP_DIR.name) / "coach.sqlite3")

from app.core.config import settings

settings.COACH_DB_URL = os.environ["COACH_DB_URL"]

from app.main import coach_store, coach_universe_funnel_diagnostics


class UniverseFunnelApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_universe_funnel_route_reads_persisted_snapshot(self):
        coach_store.save_market_snapshot(
            trade_date="2026-07-01",
            source="unit-test",
            items=[
                {
                    "symbol": "000001",
                    "name": "平安银行",
                    "price": 11,
                    "amount": 90_000_000,
                    "pct_change": 1.2,
                    "industry": "银行",
                    "trend_strength": 70,
                    "momentum_score": 62,
                    "drawdown_pct": 2.0,
                },
                {
                    "symbol": "000002",
                    "name": "ST测试",
                    "price": 5,
                    "amount": 60_000_000,
                    "pct_change": 0.5,
                },
                {
                    "symbol": "000003",
                    "name": "强势测试",
                    "price": 18,
                    "amount": 180_000_000,
                    "pct_change": 5.1,
                    "trend_strength": 86,
                    "momentum_score": 80,
                    "volume_ratio": 2.4,
                },
            ],
            min_reliable_count=3,
            created_at="2026-07-01 10:30:00",
        )

        response = await coach_universe_funnel_diagnostics(trade_date="2026-07-01", min_full_universe_count=3)

        self.assertEqual(response.code, 200)
        payload = response.data
        self.assertEqual(payload["snapshot"]["trade_date"], "2026-07-01")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["counts"]["full_market"], 3)
        self.assertEqual(payload["coverage"]["status"], "ok")
        self.assertIn("st_or_delisting", payload["rejection_reason_counts"])
        self.assertIn("trend_breakout", payload["channel_counts"])

    async def test_universe_funnel_route_requires_exact_requested_snapshot_date(self):
        coach_store.save_market_snapshot(
            trade_date="2026-07-31",
            source="unit-test",
            items=[
                {"symbol": "000001", "name": "平安银行", "price": 11, "amount": 90_000_000, "pct_change": 1.2},
            ],
            min_reliable_count=1,
            created_at="2026-07-31 10:30:00",
        )

        response = await coach_universe_funnel_diagnostics(trade_date="2026-08-01", min_full_universe_count=1)

        self.assertEqual(response.code, 200)
        payload = response.data
        self.assertFalse(payload["available"])
        self.assertEqual(payload["coverage"]["status"], "missing_snapshot")
        self.assertEqual(payload["snapshot"]["trade_date"], "2026-08-01")
        self.assertEqual(payload["snapshot"]["latest_available_trade_date"], "2026-07-31")


if __name__ == "__main__":
    unittest.main()
