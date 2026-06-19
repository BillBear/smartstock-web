import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coach_service import CoachService
from app.services.coach_store import CoachStore


class DummyDataSourceManager:
    allow_mock_fallback = False


class BacktestReplayTests(unittest.TestCase):
    def build_service(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "coach.sqlite3"
        store = CoachStore(str(db_path))
        service = CoachService(DummyDataSourceManager(), store=store)
        self.addCleanup(temp_dir.cleanup)
        return service

    def test_monthly_returns_use_last_equity_value_for_each_month(self):
        service = self.build_service()
        equity_curve = [
            {"date": "2026-01-02", "value": 100.0},
            {"date": "2026-01-30", "value": 110.0},
            {"date": "2026-02-27", "value": 121.0},
            {"date": "2026-03-31", "value": 108.9},
        ]

        returns = service._build_monthly_returns(equity_curve)

        self.assertEqual(len(returns), 2)
        self.assertAlmostEqual(returns[0], 0.10)
        self.assertAlmostEqual(returns[1], -0.10)

    def test_credibility_assessment_requires_sample_and_quality_gates(self):
        service = self.build_service()

        credibility = service._assess_backtest_credibility(
            metrics={
                "sharpe": 0.8,
                "max_drawdown": 0.24,
                "win_rate": 0.50,
                "profit_loss_ratio": 1.10,
                "annual_return": 0.08,
            },
            diagnostics={
                "closed_roundtrips": 12,
                "calendar_days": 90,
                "valid_history_symbols": 30,
                "universe_size": 140,
            },
            config={"slippage": 0.001, "commission": 0.0003},
            by_state=[
                {"state": "bull", "sample_count": 6, "win_rate": 0.55},
                {"state": "bear", "sample_count": 6, "win_rate": 0.45},
            ],
            equity_curve=[
                {"date": "2026-01-31", "value": 1.0},
                {"date": "2026-02-28", "value": 1.02},
                {"date": "2026-03-31", "value": 0.98},
            ],
        )

        failed_keys = {item["key"] for item in credibility["failed_checks"]}

        self.assertFalse(credibility["live_ready"])
        self.assertIn("closed_roundtrips", failed_keys)
        self.assertIn("calendar_days", failed_keys)
        self.assertIn("valid_history_symbols", failed_keys)
        self.assertIn("max_drawdown", failed_keys)
        self.assertEqual(credibility["assumptions"]["buy_execution_model"], "T+1 next_open_with_slippage")
        self.assertTrue(credibility["assumptions"]["mock_fallback_disabled"])


if __name__ == "__main__":
    unittest.main()
