import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.ranking_latest import load_latest_ranking_summary


class RankingLatestTests(unittest.TestCase):
    def _write_summary(self, root: Path, run_name: str, fixture):
        run_dir = root / run_name
        run_dir.mkdir(parents=True)
        payload = {
            "run_id": run_name,
            "coverage": {"fixture": fixture} if fixture else {"coverage_status": "complete"},
            "candidate_row_count": 12 if fixture else 120,
        }
        path = run_dir / "ranking_summary.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_latest_summary_skips_smoke_fixture_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_summary(root, "smoke-run", "smoke")
            self._write_summary(root, "real-run", None)

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


if __name__ == "__main__":
    unittest.main()
