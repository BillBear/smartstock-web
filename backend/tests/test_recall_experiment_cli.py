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

    def test_cli_markdown_surfaces_incompatible_experiment_context(self):
        def write_summary(root, key, end_date="2026-07-03"):
            target = root / key
            target.mkdir()
            (target / "ranking_summary.json").write_text(
                json.dumps(
                    {
                        "strategy_code": "trend_breakout",
                        "risk_level": "medium",
                        "start_date": "2026-05-01",
                        "end_date": end_date,
                        "horizons": [3, 5, 10, 20],
                        "top_k_values": [3, 5, 10],
                        "execution_config": {"commission": 0.0003, "slippage": 0.001},
                        "candidate_row_count": 300,
                        "coverage": {"coverage_status": "complete", "covered_date_count": 32},
                        "metrics": {
                            "precision_at_3": 0.7,
                            "precision_at_5": 0.62,
                            "ndcg_at_10": 0.55,
                            "top_5_avg_return_pct": 0.08,
                            "max_drawdown": 0.06,
                        },
                        "production_evidence": True,
                    }
                ),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for key in [
                "baseline",
                "recall_220_deep_150",
                "recall_300_deep_300",
                "recall_500_deep_500",
                "multi_channel_union",
            ]:
                write_summary(root, key, end_date="2026-06-30" if key == "recall_300_deep_300" else "2026-07-03")
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
            markdown = output_md.read_text(encoding="utf-8")
            self.assertIn("incompatible_experiment_reports", markdown)
            self.assertIn("end_date_mismatch", markdown)


if __name__ == "__main__":
    unittest.main()
