import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FullMarketFeaturePanelTests(unittest.TestCase):
    def test_builds_cross_sectional_ranks_per_trade_date(self):
        from app.evaluation.full_market_feature_panel import build_full_market_feature_panel

        history = pd.DataFrame(
            [
                {"trade_date": "2026-01-01", "symbol": "000001", "close": 10, "amount": 100, "turnover_rate": 1.0},
                {"trade_date": "2026-01-02", "symbol": "000001", "close": 11, "amount": 120, "turnover_rate": 1.2},
                {"trade_date": "2026-01-01", "symbol": "000002", "close": 10, "amount": 300, "turnover_rate": 3.0},
                {"trade_date": "2026-01-02", "symbol": "000002", "close": 9, "amount": 330, "turnover_rate": 3.3},
            ]
        )

        panel = build_full_market_feature_panel(history, min_symbols_per_date=2)

        self.assertEqual(set(panel["trade_date"]), {"2026-01-02"})
        self.assertIn("return_1d_pct", panel.columns)
        self.assertIn("amount_rank", panel.columns)
        self.assertIn("turnover_rank", panel.columns)
        row = panel[panel["symbol"] == "000001"].iloc[0]
        self.assertGreater(row["return_1d_pct"], 0)
        self.assertGreaterEqual(row["return_1d_rank"], 0.5)

    def test_blocks_low_coverage_full_market_dates(self):
        from app.evaluation.full_market_feature_panel import build_full_market_feature_panel

        history = pd.DataFrame(
            [
                {"trade_date": "2026-01-02", "symbol": "000001", "close": 11, "amount": 120, "turnover_rate": 1.2},
            ]
        )

        panel = build_full_market_feature_panel(history, min_symbols_per_date=5000)

        self.assertTrue(panel.empty)

    def test_cli_writes_feature_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path = root / "history.csv"
            output_path = root / "panel.csv"
            pd.DataFrame(
                [
                    {"date": "2026-01-01", "symbol": "1", "close": 10, "amount": 100, "turnover_rate": 1.0},
                    {"date": "2026-01-02", "symbol": "1", "close": 11, "amount": 120, "turnover_rate": 1.2},
                    {"date": "2026-01-01", "symbol": "2", "close": 10, "amount": 300, "turnover_rate": 3.0},
                    {"date": "2026-01-02", "symbol": "2", "close": 9, "amount": 330, "turnover_rate": 3.3},
                ]
            ).to_csv(history_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "build_full_market_feature_panel.py"),
                    "--history-csv",
                    str(history_path),
                    "--output-csv",
                    str(output_path),
                    "--min-symbols-per-date",
                    "2",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_path.exists())
            panel = pd.read_csv(output_path)
            self.assertEqual(len(panel), 2)
            self.assertIn("completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
