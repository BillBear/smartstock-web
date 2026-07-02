import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RecallExperimentCliTests(unittest.TestCase):
    def test_cli_writes_json_and_markdown_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            baseline.mkdir()
            (baseline / "ranking_summary.json").write_text(
                json.dumps(
                    {
                        "candidate_row_count": 87,
                        "coverage": {"coverage_status": "partial", "covered_date_count": 5},
                        "metrics": {},
                        "production_evidence": False,
                    }
                ),
                encoding="utf-8",
            )
            output_json = root / "recall_experiment_report.json"
            output_md = root / "recall_experiment_report.md"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_recall_experiment.py"),
                    "--experiment-root",
                    str(root),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "blocked")
            self.assertFalse(payload["production_switch_ready"])
            self.assertIn("missing_experiment_reports", output_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
