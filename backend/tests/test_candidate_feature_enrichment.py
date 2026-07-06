import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_history_panel(symbol_count=8, date_count=90):
    rows = []
    dates = pd.date_range("2026-01-01", periods=date_count, freq="D").strftime("%Y-%m-%d")
    for symbol_idx in range(symbol_count):
        for day_idx, date in enumerate(dates):
            close = 10 + symbol_idx * 0.2 + day_idx * (0.02 + symbol_idx * 0.004)
            volume = 1_000_000 + symbol_idx * 20_000 + day_idx * 1_000
            rows.append(
                {
                    "date": date,
                    "symbol": f"600{symbol_idx:03d}",
                    "name": f"样本{symbol_idx}",
                    "open": close * 0.99,
                    "high": close * 1.02,
                    "low": close * 0.98,
                    "close": close,
                    "volume": volume,
                    "amount": volume * close,
                    "pct_change": 0.5,
                }
            )
    return pd.DataFrame(rows)


def make_candidates():
    rows = []
    for date in ["2026-03-12", "2026-03-20"]:
        for idx in range(8):
            strong = idx >= 6
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"600{idx:03d}",
                    "name": f"样本{idx}",
                    "rank_no": 8 - idx,
                    "score": 70 + idx,
                    "strong_10d": strong,
                    "return_10d_pct": 10.0 if strong else -1.0,
                    "tradability_status": "tradable",
                    "incomplete_horizons": "[]",
                }
            )
    return pd.DataFrame(rows)


class CandidateFeatureEnrichmentTests(unittest.TestCase):
    def test_enriches_all_candidate_rows_with_v2_rule_features(self):
        from app.evaluation.candidate_feature_enrichment import enrich_candidate_features

        result = enrich_candidate_features(
            make_candidates(),
            history_panel_df=make_history_panel(),
            min_history_rows=60,
        )

        enriched = result["candidate_features"]
        self.assertEqual(result["summary"]["candidate_row_count"], 16)
        self.assertEqual(result["summary"]["feature_complete_row_count"], 16)
        self.assertIn("return_60d_rank", enriched.columns)
        self.assertIn("return_20d_rank", enriched.columns)
        self.assertIn("macd_hist", enriched.columns)
        self.assertIn("rsi", enriched.columns)
        self.assertTrue(enriched["has_60d_lookback"].all())
        self.assertGreater(enriched["return_60d_rank"].max(), enriched["return_60d_rank"].min())

    def test_marks_rows_without_60d_lookback_as_incomplete(self):
        from app.evaluation.candidate_feature_enrichment import enrich_candidate_features

        result = enrich_candidate_features(
            make_candidates(),
            history_panel_df=make_history_panel(date_count=45),
            min_history_rows=60,
        )

        enriched = result["candidate_features"]
        self.assertEqual(result["summary"]["feature_complete_row_count"], 0)
        self.assertFalse(enriched["has_60d_lookback"].any())
        self.assertTrue(enriched["return_60d_rank"].isna().all())

    def test_history_provider_frames_without_symbol_are_assigned_requested_symbol(self):
        from app.evaluation.candidate_feature_enrichment import fetch_candidate_history_panel

        class Provider:
            def get_history_data_range(self, symbol, start_date, end_date):
                frame = make_history_panel(symbol_count=1, date_count=5)
                return frame.drop(columns=["symbol"])

        panel = fetch_candidate_history_panel(
            symbols=["600123"],
            history_provider=Provider(),
            start_date="2026-01-01",
            end_date="2026-01-05",
        )

        self.assertFalse(panel.empty)
        self.assertEqual(set(panel["symbol"]), {"600123"})

    def test_cli_writes_enriched_features_and_baseline_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = root / "candidates.csv"
            history_path = root / "history.csv"
            output_dir = root / "out"
            make_candidates().to_csv(candidate_path, index=False)
            make_history_panel().to_csv(history_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_candidate_feature_enrichment.py"),
                    "--candidate-csv",
                    str(candidate_path),
                    "--history-panel-path",
                    str(history_path),
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
            self.assertTrue((output_dir / "candidate_features.csv").exists())
            self.assertTrue((output_dir / "feature_enrichment_summary.json").exists())
            self.assertTrue((output_dir / "rule_baseline_comparison.json").exists())
            payload = json.loads((output_dir / "feature_enrichment_summary.json").read_text(encoding="utf-8"))
            comparison = json.loads((output_dir / "rule_baseline_comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["feature_complete_row_count"], 16)
            self.assertEqual(comparison["baseline_comparison"]["return_60d_rank_desc"]["status"], "ok")
            self.assertGreater(comparison["baseline_comparison"]["return_60d_rank_desc"]["row_count"], 0)
            self.assertIn("candidate_feature_enrichment_completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
