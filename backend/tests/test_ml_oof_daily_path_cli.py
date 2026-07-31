from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import pyarrow as pa

from app.evaluation.ml_oof_daily_path import _read_selected_panel_rows, run_oof_daily_path_reconstruction


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconstruct_ml_oof_daily_paths.py"


class MLOofDailyPathRunnerTest(unittest.TestCase):
    def test_blocked_reconstruction_writes_atomic_report_without_partial_cohorts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "candidate_screen.json").write_text(
                json.dumps({"status": "development_research_failed_gate", "candidate_freeze_allowed": False}),
                encoding="utf-8",
            )
            (candidate / "oof_predictions.parquet").touch()
            output = root / "output"
            with (
                patch("app.evaluation.ml_oof_daily_path.verify_recovery_inputs", return_value=_bound_inputs()),
                patch("app.evaluation.ml_oof_daily_path.pd.read_parquet", return_value=_oof_rows()),
                patch("app.evaluation.ml_oof_daily_path._read_selected_panel_rows", return_value=_incomplete_panel()),
            ):
                report = run_oof_daily_path_reconstruction(
                    label_root=root / "labels",
                    feature_asset_root=root / "features",
                    panel_root=root / "panel",
                    candidate_run_root=candidate,
                    output_dir=output,
                    code_commit="test-commit",
                )

            self.assertEqual("blocked", report["status"])
            self.assertFalse(report["production_integration_allowed"])
            self.assertTrue((output / "path_reconstruction_report.json").is_file())
            self.assertTrue((output / "progress.json").is_file())
            self.assertFalse((output / "model_daily_cohorts.parquet").exists())
            self.assertFalse((output / "baseline_daily_cohorts.parquet").exists())

    def test_panel_reader_uses_file_schema_without_conflicting_hive_trade_date_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intermediate = root / "intermediate"
            intermediate.mkdir()
            dataset = _DatasetStub(_complete_panel())
            with patch("app.evaluation.ml_oof_daily_path.ds.dataset", return_value=dataset) as build_dataset:
                rows = _read_selected_panel_rows(root, ["000001"])

            self.assertEqual(1, len(rows))
            self.assertEqual((intermediate,), build_dataset.call_args.args)
            self.assertEqual({"format": "parquet"}, build_dataset.call_args.kwargs)


class MLOofDailyPathCliTest(unittest.TestCase):
    def test_cli_does_not_allow_cost_horizon_model_or_lockbox_overrides(self):
        module = _load_script()
        with self.assertRaises(SystemExit):
            module.parse_args(
                [
                    "--label-root", "labels",
                    "--feature-asset-root", "features",
                    "--panel-root", "panel",
                    "--candidate-run-root", "candidate",
                    "--output-dir", "output",
                    "--code-commit", "commit",
                    "--slippage", "0",
                ]
            )


def _bound_inputs() -> dict[str, object]:
    return {
        "input_manifest": {"universe_id": "shsz_a_share_v1", "production_integration_allowed": False},
        "panel_root": Path("/panel"),
    }


def _oof_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fold": 1,
                "quadrant": "A",
                "trade_date": "2025-01-02",
                "symbol": "000001",
                "model_score": 0.9,
                "baseline_score": 0.8,
                "entry_tradeable": True,
                "horizon_available_10d": True,
                "path_ambiguous_10d": False,
                "net_return_after_cost_10d": 0.1,
            }
        ]
    )


def _incomplete_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "2025-01-02",
                "symbol": "000001",
                "next_open_date": "2025-01-03",
                "adjusted_open": 10.0,
                "adjusted_close": 10.0,
                "valid_ohlc": True,
                "is_suspended": False,
                "at_up_limit_open": False,
            }
        ]
    )


def _complete_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "2025-01-02",
                "symbol": "000001",
                "next_open_date": "2025-01-03",
                "adjusted_open": 10.0,
                "adjusted_close": 10.0,
                "valid_ohlc": True,
                "is_suspended": False,
                "at_up_limit_open": False,
            }
        ]
    )


class _DatasetStub:
    def __init__(self, rows: pd.DataFrame):
        self.rows = rows

    def to_table(self, *, columns, filter):
        del columns, filter
        return pa.Table.from_pandas(self.rows, preserve_index=False)


def _load_script():
    specification = importlib.util.spec_from_file_location("reconstruct_ml_oof_daily_paths", SCRIPT)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module
