from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.full_market_ml.context_feature_audit import CONTEXT_SOURCE_COLUMNS
from app.evaluation.full_market_ml.train_only_scorecard_oof import _ALL_FEATURES, _REQUIRED_COLUMNS


class ContextScorecardAblationRunnerTests(unittest.TestCase):
    def test_writes_only_exploratory_development_artifacts(self):
        from app.evaluation.full_market_ml.context_scorecard_ablation_runner import run_context_scorecard_ablation

        with tempfile.TemporaryDirectory() as directory:
            source_root, asset_root = _write_fixture_assets(Path(directory))
            output = Path(directory) / "output"

            report = run_context_scorecard_ablation(
                source_dataset_root=source_root,
                feature_asset_root=asset_root,
                output_root=output,
                code_commit="fixture-commit",
                bootstrap_iterations=2,
            )

            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["model_status"], "research_only_exploratory")
            self.assertTrue(report["post_selection_exploratory"])
            self.assertFalse(report["production_integration_allowed"])
            self.assertFalse(report["final_holdout_used"])
            self.assertEqual(report["input_summary"]["context_source_row_count"], report["input_summary"]["scorecard_input_row_count"])
            self.assertGreater(report["input_summary"]["context_source_row_count"], report["input_summary"]["row_count"])
            for name in (
                "context_features.parquet",
                "oof_predictions.parquet",
                "fold_directions.json",
                "metrics.json",
                "bootstrap.json",
                "portfolio_metrics.json",
                "candidate_screen.json",
                "input_summary.json",
                "report.json",
                "progress.json",
            ):
                self.assertTrue((output / name).is_file(), name)
            self.assertEqual(json.loads((output / "progress.json").read_text(encoding="utf-8"))["status"], "complete")

    def test_rejects_nonempty_output_root_before_reading_assets(self):
        from app.evaluation.full_market_ml.context_scorecard_ablation_runner import run_context_scorecard_ablation

        with tempfile.TemporaryDirectory() as directory:
            source_root, asset_root = _write_fixture_assets(Path(directory))
            output = Path(directory) / "output"
            output.mkdir()
            (output / "occupied.txt").write_text("do not overwrite", encoding="utf-8")

            with self.assertRaises(ValueError):
                run_context_scorecard_ablation(
                    source_dataset_root=source_root,
                    feature_asset_root=asset_root,
                    output_root=output,
                    code_commit="fixture-commit",
                    bootstrap_iterations=1,
                )

    def test_marks_progress_failed_when_registered_matrix_is_unavailable(self):
        from app.evaluation.full_market_ml.context_scorecard_ablation_runner import run_context_scorecard_ablation

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root, asset_root = _write_fixture_assets(root)
            manifest_path = asset_root / "feature_asset_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["matrix_path"] = str(root / "missing-matrix")
            manifest["sha256"] = _payload_sha256({key: value for key, value in manifest.items() if key != "sha256"})
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "output"

            with self.assertRaises(ValueError):
                run_context_scorecard_ablation(
                    source_dataset_root=source_root,
                    feature_asset_root=asset_root,
                    output_root=output,
                    code_commit="fixture-commit",
                    bootstrap_iterations=1,
                )

            progress = json.loads((output / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(progress["status"], "failed")
            self.assertEqual(progress["stage"], "failed")


def _write_fixture_assets(root: Path) -> tuple[Path, Path]:
    source_root = root / "dataset"
    asset_root = root / "feature-asset"
    matrix_root = root / "matrix"
    dates = tuple(pd.bdate_range("2025-01-02", periods=9).strftime("%Y-%m-%d"))
    symbols = [f"{index + 1:06d}" for index in range(10)]
    split = {
        "development_dates": list(dates),
        "training_symbols": symbols[:-2],
        "stock_holdout_symbols": symbols[-2:],
        "outer_folds": [
            {
                "fold": index + 1,
                "fit_dates": list(dates[: index + 2]),
                "test_dates": [dates[index + 2]],
                "training_symbols": symbols[:-2],
            }
            for index in range(5)
        ],
        "sha256": "fixture-split-sha",
    }
    split_path = source_root / "artifacts" / "full-build" / "split_plan_v2.json"
    split_path.parent.mkdir(parents=True)
    split_path.write_text(json.dumps(split), encoding="utf-8")
    (source_root / "dataset_registry_v2.json").write_text(
        json.dumps({"dataset_id": "fixture-dataset", "source_hashes": {"dataset": "fixture-dataset-sha"}}),
        encoding="utf-8",
    )
    data = _rows(dates, symbols)
    for trade_date, partition in data.groupby("trade_date", sort=True):
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        path.parent.mkdir(parents=True)
        partition.to_parquet(path, index=False)
    manifest = {
        "status": "complete",
        "training_eligible": True,
        "production_integration_allowed": False,
        "feature_contract_sha256": "fixture-feature-contract-sha",
        "source_dataset_id": "fixture-dataset",
        "source_dataset_sha256": "fixture-dataset-sha",
        "matrix_path": str(matrix_root),
    }
    manifest["sha256"] = _payload_sha256(manifest)
    asset_root.mkdir(parents=True)
    (asset_root / "feature_asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return source_root, asset_root


def _rows(dates: tuple[str, ...], symbols: list[str]) -> pd.DataFrame:
    rows = []
    for date_index, trade_date in enumerate(dates):
        for rank, symbol in enumerate(symbols, start=1):
            low_industry = rank <= len(symbols) // 2
            forward_return = rank / 100.0 + date_index / 100_000.0
            row = {
                "trade_date": trade_date,
                "symbol": symbol,
                "valid_ohlc": True,
                "industry_l1": "low" if low_industry else "high",
                "adjusted_return_1d": (rank - len(symbols) / 2) / 1000.0,
                "adjusted_return_5d": -rank / 100.0,
                "adjusted_return_20d": rank / 50.0,
                "price_to_sma_20d": (rank - 5) / 100.0,
                "amount_ratio_5d": 1.0 + rank / 10.0,
                "turnover_rate": rank / 5.0,
                "total_mv": rank * 100.0,
                "at_up_limit": low_industry,
                "at_down_limit": low_industry,
                "eligible_for_training_10d": rank != 1,
                "entry_tradeable_10d": True,
                "horizon_available_10d": True,
                "path_ambiguous_10d": False,
                "future_return_10d": forward_return,
                "net_return_after_cost_10d": forward_return - 0.002,
                "relevance_grade_10d": 4 if rank >= 8 else 0,
                "label_strong_path_10d": rank >= 8,
                "label_severe_negative_10d": rank <= 2,
                "entry_price_10d": 10.0,
                "exit_price_10d": 10.0 * (1.0 + forward_return),
                "exit_trade_date_10d": dates[min(date_index + 1, len(dates) - 1)],
                "market_median_net_return_10d": 0.05,
                "industry_median_net_return_10d": 0.05,
            }
            for index, feature in enumerate(_ALL_FEATURES, start=1):
                row[feature] = float(rank * index + date_index)
            rows.append(row)
    frame = pd.DataFrame(rows)
    missing = (set(CONTEXT_SOURCE_COLUMNS) | set(_REQUIRED_COLUMNS) | set(_ALL_FEATURES)) - set(frame.columns)
    if missing:
        raise AssertionError(f"fixture misses required columns: {sorted(missing)}")
    return frame


def _payload_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
