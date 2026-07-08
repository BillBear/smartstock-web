import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeTuShareProClient:
    def __init__(self):
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        trade_date = kwargs["trade_date"]
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "close": 10.0, "vol": 100, "amount": 200},
                {"ts_code": "000002.SZ", "trade_date": trade_date, "close": 20.0, "vol": 200, "amount": 300},
            ]
        )

    def daily_basic(self, **kwargs):
        self.calls.append(("daily_basic", kwargs))
        trade_date = kwargs["trade_date"]
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "turnover_rate": 2.5},
                {"ts_code": "000002.SZ", "trade_date": trade_date, "turnover_rate": 0.7},
            ]
        )

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        raise RuntimeError("quota exceeded")

    def suspend_d(self, **kwargs):
        self.calls.append(("suspend_d", kwargs))
        return pd.DataFrame()

    def index_daily(self, **kwargs):
        self.calls.append(("index_daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": kwargs["start_date"],
                    "close": 3000.0,
                    "pct_chg": 1.2,
                }
            ]
        )


class TuShareEnhancedPanelCollectionTests(unittest.TestCase):
    def test_collects_panels_with_statuses_and_symbol_filter(self):
        from app.evaluation.tushare_enhanced_panel_collection import collect_tushare_enhanced_panels

        fake = FakeTuShareProClient()

        collection = collect_tushare_enhanced_panels(
            fake,
            trade_dates=["2026-07-01", "20260702"],
            symbols=["000001"],
            endpoints=["daily", "daily_basic", "adj_factor", "suspend_d", "index_daily"],
            index_codes=["000001.SH"],
        )

        self.assertEqual(collection["summary"]["trade_date_count"], 2)
        self.assertEqual(collection["summary"]["symbol_count"], 1)
        self.assertEqual(collection["endpoint_status"]["daily"]["status"], "available")
        self.assertEqual(collection["endpoint_status"]["daily"]["row_count"], 2)
        self.assertEqual(collection["endpoint_status"]["daily_basic"]["status"], "available")
        self.assertEqual(collection["endpoint_status"]["adj_factor"]["status"], "error")
        self.assertIn("quota exceeded", collection["endpoint_status"]["adj_factor"]["error"])
        self.assertEqual(collection["endpoint_status"]["suspend_d"]["status"], "empty")
        self.assertEqual(set(collection["panels"]["daily"]["symbol"]), {"000001"})
        self.assertEqual(collection["panels"]["index_daily"]["ts_code"].iloc[0], "000001.SH")

    def test_collection_artifact_writer_outputs_csv_and_json(self):
        from app.evaluation.tushare_enhanced_panel_collection import (
            collect_tushare_enhanced_panels,
            write_tushare_panel_collection_artifacts,
        )

        collection = collect_tushare_enhanced_panels(
            FakeTuShareProClient(),
            trade_dates=["2026-07-01"],
            symbols=["000001"],
            endpoints=["daily", "daily_basic", "adj_factor", "suspend_d"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_tushare_panel_collection_artifacts(collection, tmp)
            self.assertTrue(Path(paths["summary"]).exists())
            self.assertTrue(Path(paths["endpoint_status"]).exists())
            self.assertTrue(Path(paths["daily"]).exists())
            self.assertTrue(Path(paths["daily_basic"]).exists())
            payload = json.loads(Path(paths["summary"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["audit_type"], "tushare_enhanced_panel_collection")
            self.assertFalse(payload["production_evidence"])

    def test_collector_cli_runs_with_fake_fixture_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.csv"
            output_dir = root / "out"
            pd.DataFrame(
                [
                    {"trade_date": "2026-07-01", "symbol": "000001", "strong_10d": True, "return_10d_pct": 5.0},
                ]
            ).to_csv(candidates, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "collect_tushare_enhanced_panels.py"),
                    "--candidate-csv",
                    str(candidates),
                    "--output-dir",
                    str(output_dir),
                    "--fixture",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("tushare_enhanced_panel_collection_completed", result.stdout)
            self.assertTrue((output_dir / "daily_panel.csv").exists())
            self.assertTrue((output_dir / "collection_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
