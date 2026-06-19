import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["COACH_DB_URL"] = str(Path(_TEMP_DIR.name) / "coach.sqlite3")

from app.core.config import settings

settings.COACH_DB_URL = os.environ["COACH_DB_URL"]

from app.main import coach_ranking_evaluation_run
from app.models.schemas import CoachRankingEvaluationRunRequest


class RankingEvaluationApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_ranking_evaluation_run_fixture_returns_summary(self):
        with tempfile.TemporaryDirectory() as output_dir:
            response = await coach_ranking_evaluation_run(
                CoachRankingEvaluationRunRequest(
                    strategy_code="trend_breakout",
                    risk_level="medium",
                    start_date="2026-01-02",
                    end_date="2026-01-09",
                    horizons=[3, 5, 10, 20],
                    top_k=[3, 5, 10],
                    fixture="smoke",
                    output_dir=output_dir,
                )
            )

        self.assertEqual(response.code, 200)
        payload = response.data
        self.assertEqual(payload["strategy_code"], "trend_breakout")
        self.assertEqual(payload["coverage"]["coverage_status"], "complete")
        self.assertIn("precision_at_3", payload["metrics"])
        self.assertIn("diagnostics", payload)
        self.assertIn("ranking_summary.json", payload["artifacts"])

    async def test_ranking_evaluation_route_does_not_call_mutating_strategy_methods(self):
        with tempfile.TemporaryDirectory() as output_dir, patch(
            "app.main.coach_service.get_today_picks"
        ) as get_today_picks, patch("app.main.coach_service.apply_strategy_config") as apply_strategy_config:
            response = await coach_ranking_evaluation_run(
                CoachRankingEvaluationRunRequest(
                    strategy_code="trend_breakout",
                    risk_level="medium",
                    start_date="2026-01-02",
                    end_date="2026-01-09",
                    fixture="smoke",
                    output_dir=output_dir,
                )
            )

        self.assertEqual(response.code, 200)
        get_today_picks.assert_not_called()
        apply_strategy_config.assert_not_called()

    async def test_ranking_evaluation_rejects_non_fixture_when_replay_blocked(self):
        with tempfile.TemporaryDirectory() as output_dir:
            response = await coach_ranking_evaluation_run(
                CoachRankingEvaluationRunRequest(
                    strategy_code="trend_breakout",
                    risk_level="medium",
                    start_date="2026-01-02",
                    end_date="2026-01-02",
                    output_dir=output_dir,
                )
            )

        self.assertEqual(response.code, 200)
        self.assertEqual(response.data["coverage"]["coverage_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
