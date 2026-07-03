import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.ranking_latest import load_latest_ranking_summary


class RankingLatestTests(unittest.TestCase):
    def _ready_metrics(self):
        return {
            "evaluated_metric_row_count": 120,
            "precision_at_3": 0.67,
            "precision_at_5": 0.61,
            "precision_at_10": 0.58,
            "recall_at_10": 0.42,
            "ndcg_at_10": 0.55,
            "mrr": 0.48,
            "top_3_avg_return_pct": 1.2,
            "top_5_avg_return_pct": 1.0,
            "top_10_avg_return_pct": 0.8,
        }

    def _write_summary(self, root: Path, run_name: str, fixture, coverage=None, candidate_row_count=None):
        run_dir = root / run_name
        run_dir.mkdir(parents=True)
        payload = {
            "run_id": run_name,
            "coverage": coverage or ({"fixture": fixture} if fixture else {"coverage_status": "complete", "covered_date_count": 30}),
            "candidate_row_count": candidate_row_count if candidate_row_count is not None else (12 if fixture else 120),
        }
        path = run_dir / "ranking_summary.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_latest_summary_skips_smoke_fixture_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_summary(root, "smoke-run", "smoke")
            path = self._write_summary(root, "real-run", None)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["metrics"] = self._ready_metrics()
            path.write_text(json.dumps(payload), encoding="utf-8")

            summary = load_latest_ranking_summary(root, include_fixture=False)

        self.assertTrue(summary["available"])
        self.assertEqual(summary["run_id"], "real-run")
        self.assertEqual(summary["evidence_type"], "real")
        self.assertTrue(summary["production_evidence"])

    def test_latest_summary_reports_when_only_smoke_fixture_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_summary(root, "smoke-run", "smoke")

            summary = load_latest_ranking_summary(root, include_fixture=False)

        self.assertFalse(summary["available"])
        self.assertEqual(summary["evidence_type"], "smoke_only")
        self.assertFalse(summary["production_evidence"])
        self.assertEqual(summary["latest_smoke_run_id"], "smoke-run")

    def test_real_summary_with_partial_coverage_is_not_production_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_summary(
                root,
                "partial-real-run",
                None,
                coverage={
                    "coverage_status": "partial",
                    "covered_date_count": 8,
                    "requested_date_count": 45,
                },
                candidate_row_count=88,
            )

            summary = load_latest_ranking_summary(root, include_fixture=False)

        self.assertTrue(summary["available"])
        self.assertEqual(summary["run_id"], "partial-real-run")
        self.assertEqual(summary["evidence_type"], "real_insufficient")
        self.assertFalse(summary["production_evidence"])
        self.assertEqual(summary["evidence_readiness"]["status"], "insufficient")
        self.assertIn("coverage_status_partial", summary["evidence_readiness"]["blocking_reasons"])
        self.assertIn("covered_dates_below_30", summary["evidence_readiness"]["blocking_reasons"])

    def test_real_summary_with_complete_coverage_but_missing_metrics_is_not_production_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_summary(
                root,
                "complete-without-metrics",
                None,
                coverage={
                    "coverage_status": "complete",
                    "covered_date_count": 32,
                    "requested_date_count": 32,
                },
                candidate_row_count=320,
            )

            summary = load_latest_ranking_summary(root, include_fixture=False)

        self.assertEqual(summary["evidence_type"], "real_insufficient")
        self.assertFalse(summary["production_evidence"])
        self.assertIn("ranking_metrics_missing", summary["readiness_blockers"])

    def test_real_summary_with_complete_thirty_day_coverage_and_metrics_is_production_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._write_summary(
                root,
                "complete-real-run",
                None,
                coverage={
                    "coverage_status": "complete",
                    "covered_date_count": 32,
                    "requested_date_count": 32,
                },
                candidate_row_count=320,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["metrics"] = self._ready_metrics()
            path.write_text(json.dumps(payload), encoding="utf-8")

            summary = load_latest_ranking_summary(root, include_fixture=False)

        self.assertTrue(summary["available"])
        self.assertEqual(summary["evidence_type"], "real")
        self.assertTrue(summary["production_evidence"])
        self.assertEqual(summary["evidence_readiness"]["status"], "ready")

    def test_latest_summary_exposes_api_ready_metrics_and_coverage_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._write_summary(
                root,
                "api-contract-real-run",
                None,
                coverage={
                    "coverage_status": "partial",
                    "covered_date_count": 6,
                    "requested_date_count": 67,
                },
                candidate_row_count=103,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["metrics"] = {
                "precision_at_3": 0.027778,
                "precision_at_5": 0.016667,
                "ndcg_at_10": 0.061999,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            summary = load_latest_ranking_summary(root, include_fixture=False)

        self.assertTrue(summary["available"])
        self.assertEqual(summary["summary_metrics"]["precision_at_3"], 0.027778)
        self.assertEqual(summary["coverage_status"], "partial")
        self.assertEqual(summary["covered_date_count"], 6)
        self.assertEqual(summary["requested_date_count"], 67)
        self.assertEqual(summary["report_path"], str(path))
        self.assertIn("coverage_status_partial", summary["readiness_blockers"])


if __name__ == "__main__":
    unittest.main()
