import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.schemas import CoachRankingEvaluationRunRequest


class RankingEvaluationRunTests(unittest.TestCase):
    def test_run_response_marks_smoke_fixture_as_non_production_evidence(self):
        from app import main as app_main

        request = CoachRankingEvaluationRunRequest(
            start_date="2026-05-01",
            end_date="2026-07-02",
            fixture="smoke",
            output_dir=tempfile.mkdtemp(),
        )
        fake_summary = {
            "run_id": "fixture_smoke",
            "coverage": {"fixture": "smoke", "coverage_status": "complete", "covered_date_count": 1},
            "candidate_row_count": 8,
        }

        with patch.object(app_main, "build_ranking_report", return_value=fake_summary):
            summary = app_main._run_ranking_evaluation_report(request)

        self.assertFalse(summary["production_evidence"])
        self.assertEqual(summary["evidence_type"], "smoke")
        self.assertEqual(summary["evidence_readiness"]["status"], "insufficient")
        self.assertIn("fixture_smoke", summary["evidence_readiness"]["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
