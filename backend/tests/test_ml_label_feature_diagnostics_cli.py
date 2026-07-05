import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MLLabelFeatureDiagnosticsCliTests(unittest.TestCase):
    def test_cli_writes_json_and_markdown_reports(self):
        rows = []
        for day_idx, date in enumerate(pd.date_range("2026-01-01", periods=30).strftime("%Y-%m-%d")):
            split = "train" if day_idx < 18 else "final_holdout"
            if day_idx >= 24:
                split = "stock_holdout"
            for idx in range(20):
                label = 1 if idx >= 15 else 0
                rows.append(
                    {
                        "date": date,
                        "symbol": f"600{idx:03d}",
                        "name": f"样本{idx}",
                        "split": split,
                        "strong_feature": float(idx),
                        "weak_feature": float(idx % 3),
                        "label_top20_10d": label,
                        "future_return_10d_pct": 8.0 if label else -1.0,
                    }
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_path = root / "samples.csv"
            pd.DataFrame(rows).to_csv(sample_path, index=False)
            output_json = root / "diagnostics.json"
            output_md = root / "diagnostics.md"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_ml_label_feature_diagnostics.py"),
                    "--sample-path",
                    str(sample_path),
                    "--features",
                    "strong_feature,weak_feature",
                    "--label-col",
                    "label_top20_10d",
                    "--return-col",
                    "future_return_10d_pct",
                    "--min-daily-count",
                    "10",
                    "--min-full-market-daily-count",
                    "10",
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
            self.assertEqual(payload["label_sample_audit"]["summary"]["row_count"], len(rows))
            self.assertEqual(payload["feature_diagnostics"]["tree"]["status"], "trained")
            self.assertIn("strong_feature", output_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
