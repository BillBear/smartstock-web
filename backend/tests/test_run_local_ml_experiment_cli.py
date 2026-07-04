import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.local_ml_labels import add_local_core_labels
from scripts.run_local_ml_experiment import (
    history_cache_root_for_config,
    _limit_frame_to_target_symbols,
    _prepare_local_training_frame,
    build_config_from_args,
    history_window_for_config,
    parse_args,
)


class RunLocalMLExperimentCLITests(unittest.TestCase):
    def test_default_args_target_700_runtime_outputs_and_paper_only(self):
        args = parse_args([])
        cfg = build_config_from_args(args)

        self.assertEqual(cfg["target_valid_symbols"], 700)
        self.assertEqual(cfg["oversample_symbols"], 760)
        self.assertIn("runtime/ml_runs/local_core_v1", cfg["output_root"])
        self.assertIn("backend/data/ml_models/local_core_v1", cfg["artifact_root"])
        self.assertFalse(cfg["production_enabled"])

    def test_dry_run_writes_config_without_fetching_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(__file__).resolve().parents[1] / "scripts" / "run_local_ml_experiment.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--target-valid-symbols",
                    "20",
                    "--oversample-symbols",
                    "30",
                    "--min-formal-model-symbols",
                    "20",
                    "--output-root",
                    tmp,
                    "--dry-run",
                ],
                cwd=str(Path(__file__).resolve().parents[1]),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout.strip())
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["production_enabled"])
            self.assertTrue(Path(payload["run_config_path"]).exists())

    def test_history_window_matches_feature_warmup_and_label_lookahead(self):
        cfg = build_config_from_args(parse_args(["--train-start", "2025-01-01", "--train-end", "2026-07-03"]))

        start, end = history_window_for_config(cfg)

        self.assertEqual(start, "2024-01-02")
        self.assertEqual(end, "2026-09-01")

    def test_history_cache_root_is_shared_across_run_ids_under_output_parent(self):
        cfg = build_config_from_args(
            parse_args(
                [
                    "--output-root",
                    "/tmp/smartstock/runtime/ml_runs/local_core_v1/formal_700",
                ]
            )
        )

        self.assertEqual(
            str(history_cache_root_for_config(cfg)),
            "/tmp/smartstock/runtime/ml_runs/local_core_v1/history_cache",
        )

    def test_prepare_training_frame_adds_multi_horizon_labels_before_sampling(self):
        dates = pd.date_range("2026-01-01", periods=8, freq="D").strftime("%Y-%m-%d")
        rows = []
        for symbol, start_price in [("600001", 10.0), ("600002", 20.0)]:
            for idx, date in enumerate(dates):
                close = start_price + idx
                rows.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "name": symbol,
                        "open": close,
                        "high": close * 1.02,
                        "low": close * 0.98,
                        "close": close,
                        "volume": 1000,
                        "amount": 100000,
                        "feature_a": float(idx),
                        "future_return_pct": 1.0,
                        "future_max_drawdown_pct": -1.0,
                        "label_up": 1,
                        "label_dd": 0,
                        "label_risk_adjusted_return": 1.0,
                    }
                )

        frame = _prepare_local_training_frame(
            pd.DataFrame(rows),
            horizons=[2, 3],
            primary_horizon=3,
            sample_step=2,
            labeler=add_local_core_labels,
        )

        self.assertIn("future_return_2d_pct", frame.columns)
        self.assertIn("future_return_3d_pct", frame.columns)
        self.assertIn("label_tp_before_sl_3d", frame.columns)
        self.assertEqual(frame["symbol"].nunique(), 2)
        self.assertLess(len(frame), len(rows))

    def test_limit_frame_uses_oversampled_order_after_label_filtering(self):
        frame = pd.DataFrame(
            {
                "date": ["2026-01-01"] * 4,
                "symbol": ["600001", "600003", "600004", "600005"],
                "value": [1, 3, 4, 5],
            }
        )

        limited = _limit_frame_to_target_symbols(
            frame,
            symbol_order=["600001", "600002", "600003", "600004", "600005"],
            target_count=3,
        )

        self.assertEqual(limited["symbol"].drop_duplicates().tolist(), ["600001", "600003", "600004"])


if __name__ == "__main__":
    unittest.main()
