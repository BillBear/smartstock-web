import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RankingEvaluationCliTests(unittest.TestCase):
    def test_smoke_fixture_writes_summary_and_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_ranking_evaluation.py",
                    "--strategy-code",
                    "trend_breakout",
                    "--risk-level",
                    "medium",
                    "--start-date",
                    "2026-01-02",
                    "--end-date",
                    "2026-01-09",
                    "--horizons",
                    "3,5,10,20",
                    "--top-k",
                    "3,5,10",
                    "--commission",
                    "0.0003",
                    "--slippage",
                    "0.001",
                    "--output-dir",
                    tmp,
                    "--fixture",
                    "smoke",
                ],
                cwd=".",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary_path = Path(tmp) / "ranking_summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["strategy_code"], "trend_breakout")
            self.assertEqual(summary["risk_level"], "medium")
            self.assertEqual(summary["coverage"]["coverage_status"], "complete")
            self.assertIn("ranking_daily_metrics.csv", summary["artifacts"])
            self.assertTrue((Path(tmp) / "ranking_daily_metrics.csv").exists())
            self.assertTrue((Path(tmp) / "ranking_item_labels.csv").exists())
            self.assertTrue((Path(tmp) / "ranking_diagnostics.json").exists())
            self.assertIn("Precision@3", result.stdout)

    def test_cli_rejects_invalid_date_range_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_ranking_evaluation.py",
                    "--strategy-code",
                    "trend_breakout",
                    "--risk-level",
                    "medium",
                    "--start-date",
                    "2026-01-09",
                    "--end-date",
                    "2026-01-02",
                    "--output-dir",
                    tmp,
                    "--fixture",
                    "smoke",
                ],
                cwd=".",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("start-date must be on or before end-date", result.stderr)
            self.assertFalse((Path(tmp) / "ranking_summary.json").exists())

    def test_custom_top_k_is_reflected_in_summary_and_daily_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_ranking_evaluation.py",
                    "--strategy-code",
                    "trend_breakout",
                    "--risk-level",
                    "medium",
                    "--start-date",
                    "2026-01-02",
                    "--end-date",
                    "2026-01-09",
                    "--horizons",
                    "5",
                    "--top-k",
                    "1",
                    "--output-dir",
                    tmp,
                    "--fixture",
                    "smoke",
                ],
                cwd=".",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((Path(tmp) / "ranking_summary.json").read_text(encoding="utf-8"))
            daily_header = (Path(tmp) / "ranking_daily_metrics.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("precision_at_1", summary["metrics"])
            self.assertIn("top_1_avg_return_pct", summary["metrics"])
            self.assertIn("precision_at_1", daily_header)
            self.assertIn("top_1_avg_return_pct", daily_header)


if __name__ == "__main__":
    unittest.main()
