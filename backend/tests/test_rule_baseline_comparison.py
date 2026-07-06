import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _candidate_rows():
    rows = []
    for date in ["2026-01-02", "2026-01-05"]:
        for idx in range(10):
            symbol = f"600{idx:03d}"
            strong = idx >= 7
            rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "rank_no": idx + 1,
                    "score": 90.0 - idx,
                    "strong_10d": strong,
                    "return_10d_pct": 12.0 if strong else -2.0,
                    "tradability_status": "tradable",
                    "incomplete_horizons": "[]",
                }
            )
    return rows


def _feature_rows():
    rows = []
    for date in ["2026-01-02", "2026-01-05"]:
        for idx in range(10):
            rows.append(
                {
                    "date": date,
                    "symbol": f"600{idx:03d}",
                    "return_60d_rank": idx / 9,
                    "return_20d_rank": idx / 9,
                    "amount_pct_rank": (9 - idx) / 9,
                    "macd_hist": float(idx),
                    "rsi": 45.0 + idx,
                }
            )
    return rows


class RuleBaselineComparisonTests(unittest.TestCase):
    def test_join_rule_features_aligns_date_and_symbol(self):
        from app.evaluation.rule_baseline_comparison import join_rule_features

        candidates = pd.DataFrame(
            [
                {"trade_date": "2026-01-02", "symbol": 1, "rank_no": 1, "strong_10d": True, "return_10d_pct": 8.0},
                {"trade_date": "2026-01-02", "symbol": "000002", "rank_no": 2, "strong_10d": False, "return_10d_pct": -1.0},
            ]
        )
        features = pd.DataFrame(
            [
                {"date": "2026-01-02", "symbol": "000001", "return_60d_rank": 0.9},
                {"date": "2026-01-02", "symbol": "000002", "return_60d_rank": 0.1},
            ]
        )

        joined, coverage = join_rule_features(candidates, features)

        self.assertEqual(coverage["candidate_row_count"], 2)
        self.assertEqual(coverage["joined_row_count"], 2)
        self.assertEqual(joined.loc[0, "symbol"], "000001")
        self.assertAlmostEqual(joined.loc[0, "return_60d_rank"], 0.9)

    def test_return_60d_rank_baseline_can_beat_current_smartstock_rank(self):
        from app.evaluation.rule_baseline_comparison import run_rule_baseline_comparison

        summary = run_rule_baseline_comparison(
            pd.DataFrame(_candidate_rows()),
            pd.DataFrame(_feature_rows()),
            horizon=10,
            round_trip_cost_pct=0.2,
            min_margin_pct=0.3,
        )

        current = summary["baseline_comparison"]["current_smartstock_rank"]
        return_60d = summary["baseline_comparison"]["return_60d_rank_desc"]
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(return_60d["status"], "ok")
        self.assertGreater(return_60d["precision_at_5"], current["precision_at_5"])
        self.assertGreater(return_60d["top5_return_after_cost"], current["top5_return_after_cost"])
        self.assertEqual(summary["decision"]["outcome"], "current_rank_lags_return_60d_baseline")

    def test_missing_return_60d_feature_blocks_direct_comparison(self):
        from app.evaluation.rule_baseline_comparison import run_rule_baseline_comparison

        feature_rows = [{key: value for key, value in row.items() if key != "return_60d_rank"} for row in _feature_rows()]

        summary = run_rule_baseline_comparison(
            pd.DataFrame(_candidate_rows()),
            pd.DataFrame(feature_rows),
            horizon=10,
        )

        self.assertEqual(summary["baseline_comparison"]["return_60d_rank_desc"]["status"], "missing")
        self.assertEqual(summary["decision"]["outcome"], "blocked_missing_return_60d_rank")
        self.assertFalse(summary["production_evidence"])

    def test_all_baselines_use_same_joined_overlap_sample(self):
        from app.evaluation.rule_baseline_comparison import run_rule_baseline_comparison

        partial_features = [row for row in _feature_rows() if row["symbol"] in {"600007", "600008", "600009"}]

        summary = run_rule_baseline_comparison(
            pd.DataFrame(_candidate_rows()),
            pd.DataFrame(partial_features),
            horizon=10,
        )

        current = summary["baseline_comparison"]["current_smartstock_rank"]
        return_60d = summary["baseline_comparison"]["return_60d_rank_desc"]
        self.assertEqual(summary["coverage"]["joined_row_count"], 6)
        self.assertEqual(current["row_count"], return_60d["row_count"])
        self.assertEqual(current["covered_date_count"], return_60d["covered_date_count"])

    def test_artifact_writer_outputs_json_csv_and_markdown(self):
        from app.evaluation.rule_baseline_comparison import run_rule_baseline_comparison, write_rule_comparison_artifacts

        summary = run_rule_baseline_comparison(pd.DataFrame(_candidate_rows()), pd.DataFrame(_feature_rows()), horizon=10)

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_rule_comparison_artifacts(summary, tmp)
            self.assertTrue(Path(paths["summary"]).exists())
            self.assertTrue(Path(paths["baseline_comparison"]).exists())
            self.assertTrue(Path(paths["report"]).exists())
            payload = json.loads(Path(paths["summary"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["audit_type"], "rule_baseline_comparison")

    def test_cli_writes_rule_baseline_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = root / "candidates.csv"
            feature_path = root / "features.csv"
            output_dir = root / "out"
            pd.DataFrame(_candidate_rows()).to_csv(candidate_path, index=False)
            pd.DataFrame(_feature_rows()).to_csv(feature_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_rule_baseline_comparison.py"),
                    "--candidate-csv",
                    str(candidate_path),
                    "--feature-sample-path",
                    str(feature_path),
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
            self.assertTrue((output_dir / "rule_baseline_comparison.json").exists())
            self.assertIn("current_rank_lags_return_60d_baseline", result.stdout)


if __name__ == "__main__":
    unittest.main()
