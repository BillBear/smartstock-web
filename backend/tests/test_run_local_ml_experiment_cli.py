import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.local_ml_labels import add_local_core_labels
from app.evaluation.local_ml_v2 import V2_FEATURE_NAMES, add_local_core_v2_labels, build_local_core_v2_features
from scripts.run_local_ml_experiment import (
    history_cache_root_for_config,
    _limit_frame_to_target_symbols,
    _prepare_local_training_frame,
    _prepare_v2_training_inputs,
    _assign_split_labels,
    _apply_symbol_names,
    _training_report_markdown,
    _write_training_sample_artifacts,
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

    def test_v2_args_use_strict_daily_sample_and_rank_top10_label(self):
        args = parse_args(["--model-family", "local_core_v2"])
        cfg = build_config_from_args(args)

        self.assertEqual(cfg["model_family"], "local_core_v2")
        self.assertEqual(cfg["sample_step"], 1)
        self.assertEqual(cfg["primary_label"], "label_rank_top10_10d")
        self.assertEqual(cfg["candidate_set"], "core_v2")
        self.assertEqual(cfg["min_daily_panel_count"], 500)
        self.assertIn("Local Core ML v2", cfg["model_display_name"])

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

    def test_prepare_v2_training_inputs_filters_sparse_dates_and_rebuilds_embargo_split(self):
        dates = pd.date_range("2026-01-01", periods=90, freq="D").strftime("%Y-%m-%d")
        rows = []
        for symbol_idx in range(12):
            symbol = f"600{symbol_idx:03d}"
            for day_idx, date in enumerate(dates):
                if date == "2026-01-05" and symbol_idx >= 5:
                    continue
                close = 10 + symbol_idx * 0.1 + day_idx * 0.05
                rows.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "name": symbol,
                        "open": close,
                        "high": close * 1.02,
                        "low": close * 0.98,
                        "close": close,
                        "volume": 1000 + symbol_idx,
                        "amount": 100000 + symbol_idx * 1000,
                        "pct_change": 1.0,
                    }
                )
        featured, _ = build_local_core_v2_features(pd.DataFrame(rows))

        frame, feature_names, label_col, split_plan, report = _prepare_v2_training_inputs(
            featured,
            primary_horizon=3,
            auxiliary_horizons=[5],
            sample_step=1,
            min_daily_panel_count=10,
            target_symbols=[f"600{idx:03d}" for idx in range(12)],
            target_count=12,
            final_time_holdout_months=1,
            stock_holdout_ratio=0.2,
            walk_forward_splits=2,
            labeler=add_local_core_v2_labels,
        )

        self.assertEqual(feature_names, V2_FEATURE_NAMES)
        self.assertEqual(label_col, "label_rank_top10_3d")
        self.assertNotIn("2026-01-05", set(frame["date"]))
        self.assertEqual(report["daily_panel_gate"]["dropped_date_count"], 1)
        self.assertEqual(split_plan["embargo"]["label_horizon_days"], 3)
        self.assertTrue(split_plan["embargo"]["final_holdout_embargo_dates"])

    def test_training_sample_artifacts_export_preview_columns_and_full_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            frame = pd.DataFrame(
                {
                    "date": ["2026-01-01", "2026-01-02"],
                    "symbol": ["600001", "600002"],
                    "feature": [1.0, 2.0],
                    "label_rank_top10_10d": [0, 1],
                }
            )

            artifacts = _write_training_sample_artifacts(run_dir, frame)

            self.assertTrue(Path(artifacts["columns_path"]).exists())
            self.assertTrue(Path(artifacts["preview_csv_path"]).exists())
            self.assertTrue(Path(artifacts["sample_path"]).exists())
            columns = json.loads(Path(artifacts["columns_path"]).read_text(encoding="utf-8"))
            self.assertIn("label_rank_top10_10d", columns)

    def test_assign_split_labels_marks_train_final_stock_and_embargo_rows(self):
        frame = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
                "symbol": ["600001", "600001", "600001", "600002"],
            }
        )
        split_plan = {
            "training_dates": ["2026-01-01", "2026-01-04"],
            "training_symbols": ["600001"],
            "final_holdout": {"dates": ["2026-01-03"]},
            "stock_holdout": {"symbols": ["600002"]},
            "embargo": {"final_holdout_embargo_dates": ["2026-01-02"]},
            "walk_forward": {"windows": [{"embargo_dates": ["2026-01-04"]}]},
        }

        labeled = _assign_split_labels(frame, split_plan)

        by_key = {(row.date, row.symbol): row.split for row in labeled.itertuples()}
        self.assertEqual(by_key[("2026-01-01", "600001")], "train")
        self.assertEqual(by_key[("2026-01-02", "600001")], "embargo_gap")
        self.assertEqual(by_key[("2026-01-03", "600001")], "final_holdout")
        self.assertEqual(by_key[("2026-01-04", "600002")], "stock_holdout")

    def test_apply_symbol_names_restores_names_after_history_cache_filters_symbols(self):
        frame = pd.DataFrame({"symbol": ["600001", "600002"], "name": ["600001", "600002"]})
        sampled = [{"symbol": "600001", "name": "样本A"}, {"symbol": "600002", "name": "样本B"}]

        named = _apply_symbol_names(frame, sampled)

        self.assertEqual(named["name"].tolist(), ["样本A", "样本B"])

    def test_training_report_title_uses_model_family_version(self):
        markdown = _training_report_markdown(
            {"model_family": "local_core_v2", "target_valid_symbols": 700},
            {"valid_symbol_count": 700, "sample_count": 1000},
            {"best_model": "decision_tree_shallow"},
        )

        self.assertIn("Local Core ML V2 Training Report", markdown)


if __name__ == "__main__":
    unittest.main()
