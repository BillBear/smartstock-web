import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UniverseFunnelAuditTests(unittest.TestCase):
    def test_marks_missing_candidate_strong_stock_as_recall_failure(self):
        from app.evaluation.universe_funnel_audit import audit_universe_funnel

        universe = pd.DataFrame(
            [
                {"trade_date": "2026-01-02", "symbol": "000001", "name": "强势股", "return_10d_pct": 15, "strong_10d": True},
                {"trade_date": "2026-01-02", "symbol": "000002", "name": "普通股", "return_10d_pct": -2, "strong_10d": False},
            ]
        )
        candidates = pd.DataFrame(
            [
                {"trade_date": "2026-01-02", "symbol": "000002", "rank_no": 1},
            ]
        )

        report = audit_universe_funnel(universe, candidates, horizon=10)
        row = report["items"][report["items"]["symbol"] == "000001"].iloc[0]

        self.assertEqual(row["last_layer"], "full_market")
        self.assertEqual(row["failure_type"], "recall_miss_strong_stock")
        self.assertFalse(row["kept_final"])
        self.assertEqual(report["summary"]["recall_miss_strong_stock_count"], 1)

    def test_marks_late_strong_and_top_weak_candidates(self):
        from app.evaluation.universe_funnel_audit import audit_universe_funnel

        universe = pd.DataFrame(
            [
                {"trade_date": "2026-01-02", "symbol": "000001", "name": "弱票", "return_10d_pct": -4, "strong_10d": False},
                {"trade_date": "2026-01-02", "symbol": "000002", "name": "靠后强票", "return_10d_pct": 12, "strong_10d": True},
            ]
        )
        candidates = pd.DataFrame(
            [
                {"trade_date": "2026-01-02", "symbol": "000001", "rank_no": 1},
                {"trade_date": "2026-01-02", "symbol": "000002", "rank_no": 12},
            ]
        )

        report = audit_universe_funnel(universe, candidates, horizon=10, top_rank_cutoff=10)
        items = report["items"].set_index("symbol")

        self.assertEqual(items.loc["000001", "failure_type"], "top_rank_weak_stock")
        self.assertEqual(items.loc["000002", "failure_type"], "ranking_late_strong_stock")
        self.assertEqual(report["summary"]["top_rank_weak_stock_count"], 1)
        self.assertEqual(report["summary"]["ranking_late_strong_stock_count"], 1)

    def test_cli_writes_funnel_audit_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature_path = root / "features.csv"
            label_path = root / "labels.csv"
            candidate_path = root / "candidates.csv"
            output_dir = root / "out"
            pd.DataFrame(
                [
                    {"trade_date": "2026-01-02", "symbol": "000001", "name": "强势股", "return_60d_rank": 0.9},
                    {"trade_date": "2026-01-02", "symbol": "000002", "name": "弱票", "return_60d_rank": 0.2},
                ]
            ).to_csv(feature_path, index=False)
            pd.DataFrame(
                [
                    {"trade_date": "2026-01-02", "symbol": "000001", "return_10d_pct": 15, "strong_10d": True},
                    {"trade_date": "2026-01-02", "symbol": "000002", "return_10d_pct": -2, "strong_10d": False},
                ]
            ).to_csv(label_path, index=False)
            pd.DataFrame(
                [
                    {"trade_date": "2026-01-02", "symbol": "000002", "rank_no": 1},
                ]
            ).to_csv(candidate_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "audit_universe_funnel.py"),
                    "--feature-panel",
                    str(feature_path),
                    "--label-panel",
                    str(label_path),
                    "--candidate-features",
                    str(candidate_path),
                    "--output-dir",
                    str(output_dir),
                    "--horizon",
                    "10",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output_dir / "universe_funnel_items.csv").exists())
            self.assertTrue((output_dir / "universe_funnel_summary.json").exists())
            payload = json.loads((output_dir / "universe_funnel_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["recall_miss_strong_stock_count"], 1)
            self.assertIn("completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
