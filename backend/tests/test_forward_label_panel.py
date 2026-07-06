import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ForwardLabelPanelTests(unittest.TestCase):
    def test_labels_future_returns_and_first_stop_event(self):
        from app.evaluation.forward_label_panel import build_forward_label_panel

        history = pd.DataFrame(
            [
                {"trade_date": "2026-01-01", "symbol": "000001", "close": 10, "high": 10.2, "low": 9.8, "pct_chg": 0},
                {"trade_date": "2026-01-02", "symbol": "000001", "close": 10.5, "high": 10.8, "low": 10.1, "pct_chg": 5},
                {"trade_date": "2026-01-05", "symbol": "000001", "close": 11.2, "high": 11.5, "low": 10.4, "pct_chg": 6.67},
                {"trade_date": "2026-01-06", "symbol": "000001", "close": 10.8, "high": 11.0, "low": 10.2, "pct_chg": -3.57},
            ]
        )

        labels = build_forward_label_panel(history, horizons=[2], take_profit_pct=10, stop_loss_pct=-5)
        row = labels[labels["trade_date"] == "2026-01-01"].iloc[0]

        self.assertAlmostEqual(row["return_2d_pct"], 12.0)
        self.assertTrue(row["strong_2d"])
        self.assertEqual(row["first_event_2d"], "take_profit")
        self.assertFalse(row["incomplete_2d"])

    def test_labels_stop_loss_before_take_profit(self):
        from app.evaluation.forward_label_panel import build_forward_label_panel

        history = pd.DataFrame(
            [
                {"trade_date": "2026-01-01", "symbol": "000001", "close": 10, "high": 10.1, "low": 9.9, "pct_chg": 0},
                {"trade_date": "2026-01-02", "symbol": "000001", "close": 9.6, "high": 9.8, "low": 9.3, "pct_chg": -4},
                {"trade_date": "2026-01-05", "symbol": "000001", "close": 11.2, "high": 11.5, "low": 10.8, "pct_chg": 16.67},
            ]
        )

        labels = build_forward_label_panel(history, horizons=[2], take_profit_pct=10, stop_loss_pct=-5)
        row = labels[labels["trade_date"] == "2026-01-01"].iloc[0]

        self.assertEqual(row["first_event_2d"], "stop_loss")
        self.assertLess(row["max_drawdown_2d_pct"], -5)

    def test_marks_incomplete_future_window(self):
        from app.evaluation.forward_label_panel import build_forward_label_panel

        history = pd.DataFrame(
            [
                {"trade_date": "2026-01-01", "symbol": "000001", "close": 10, "high": 10.2, "low": 9.8, "pct_chg": 0},
                {"trade_date": "2026-01-02", "symbol": "000001", "close": 10.5, "high": 10.8, "low": 10.1, "pct_chg": 5},
            ]
        )

        labels = build_forward_label_panel(history, horizons=[3])
        row = labels[labels["trade_date"] == "2026-01-01"].iloc[0]

        self.assertTrue(row["incomplete_3d"])
        self.assertTrue(row["suspended_or_missing_3d"])

    def test_cli_writes_forward_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_path = root / "history.csv"
            output_path = root / "labels.csv"
            pd.DataFrame(
                [
                    {"date": "2026-01-01", "symbol": "1", "close": 10, "high": 10.2, "low": 9.8, "pct_chg": 0},
                    {"date": "2026-01-02", "symbol": "1", "close": 10.5, "high": 10.8, "low": 10.1, "pct_chg": 5},
                    {"date": "2026-01-05", "symbol": "1", "close": 11.2, "high": 11.5, "low": 10.4, "pct_chg": 6.67},
                ]
            ).to_csv(history_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "build_forward_label_panel.py"),
                    "--history-csv",
                    str(history_path),
                    "--output-csv",
                    str(output_path),
                    "--horizons",
                    "2",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_path.exists())
            labels = pd.read_csv(output_path)
            self.assertIn("return_2d_pct", labels.columns)
            self.assertIn("completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
