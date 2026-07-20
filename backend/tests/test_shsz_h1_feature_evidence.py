from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.shsz_h1_feature_evidence import (
    SHSZH1FeatureEvidenceError,
    run_shsz_h1_feature_evidence,
)


class SHSZH1FeatureEvidenceTests(unittest.TestCase):
    def test_runs_bound_development_only_h1_evidence(self):
        with _FixtureEvidenceAsset() as fixture:
            report = run_shsz_h1_feature_evidence(
                label_root=fixture.label_root,
                feature_asset_root=fixture.feature_root,
                output_dir=fixture.output_root,
                code_commit="fixture",
                bootstrap_iterations=3,
            )

            self.assertEqual("complete", report["status"])
            self.assertTrue(report["research_only"])
            self.assertFalse(report["production_integration_allowed"])
            self.assertEqual(5, report["walk_forward_fold_count"])
            self.assertEqual("unavailable", report["market_state"]["status"])
            self.assertEqual(
                {"fold_1_A_development_seen", "fold_1_C_development_unseen"},
                set(key for key in report["fold_metrics"] if key.startswith("fold_1_")),
            )
            self.assertTrue((fixture.output_root / "predictions.parquet").is_file())
            self.assertTrue((fixture.output_root / "model_card.md").is_file())
            self.assertIn("No model was trained", (fixture.output_root / "model_card.md").read_text())

    def test_rejects_feature_asset_with_stale_label_registry_hash(self):
        with _FixtureEvidenceAsset() as fixture:
            registry_path = fixture.label_root / "dataset_registry.json"
            registry = json.loads(registry_path.read_text())
            registry["dataset_id"] = "tampered"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(SHSZH1FeatureEvidenceError, "label registry SHA256"):
                run_shsz_h1_feature_evidence(
                    label_root=fixture.label_root,
                    feature_asset_root=fixture.feature_root,
                    output_dir=fixture.output_root,
                    code_commit="fixture",
                    bootstrap_iterations=3,
                )

    def test_resolves_matrix_from_asset_root_when_manifest_keeps_old_staging_path(self):
        with _FixtureEvidenceAsset() as fixture:
            fixture._feature_manifest["matrix_path"] = str(fixture.feature_root / ".old-staging" / "matrix")
            fixture.refresh_feature_label_binding()

            report = run_shsz_h1_feature_evidence(
                label_root=fixture.label_root,
                feature_asset_root=fixture.feature_root,
                output_dir=fixture.output_root,
                code_commit="fixture",
                bootstrap_iterations=3,
            )

            self.assertEqual("complete", report["status"])
            self.assertEqual(str((fixture.feature_root / "matrix").resolve()), report["input_manifest"]["resolved_matrix_path"])

    def test_normalizes_compact_label_dates_before_joining_hive_feature_dates(self):
        with _FixtureEvidenceAsset() as fixture:
            label_path = next((fixture.label_root / "labels").rglob("*.parquet"))
            labels = pq.read_table(label_path).to_pandas()
            labels["trade_date"] = labels["trade_date"].str.replace("-", "", regex=False)
            pq.write_table(pa.Table.from_pandas(labels, preserve_index=False), label_path)
            fixture.refresh_label_registry()
            fixture.refresh_feature_label_binding()

            report = run_shsz_h1_feature_evidence(
                label_root=fixture.label_root,
                feature_asset_root=fixture.feature_root,
                output_dir=fixture.output_root,
                code_commit="fixture",
                bootstrap_iterations=3,
            )

            self.assertEqual("complete", report["status"])

    def test_rejects_empty_symbols_instead_of_coercing_them_to_zeroes(self):
        with _FixtureEvidenceAsset() as fixture:
            label_path = next((fixture.label_root / "labels").rglob("*.parquet"))
            labels = pq.read_table(label_path).to_pandas()
            labels.loc[0, "symbol"] = ""
            pq.write_table(pa.Table.from_pandas(labels, preserve_index=False), label_path)
            fixture.refresh_label_registry()
            fixture.refresh_feature_label_binding()

            with self.assertRaisesRegex(SHSZH1FeatureEvidenceError, "invalid symbol"):
                run_shsz_h1_feature_evidence(
                    label_root=fixture.label_root,
                    feature_asset_root=fixture.feature_root,
                    output_dir=fixture.output_root,
                    code_commit="fixture",
                    bootstrap_iterations=3,
                )

    def test_rejects_bj_symbols_before_evidence_calculation(self):
        with _FixtureEvidenceAsset() as fixture:
            label_path = next((fixture.label_root / "labels").rglob("*.parquet"))
            labels = pq.read_table(label_path).to_pandas()
            labels.loc[0, "symbol"] = "430001.BJ"
            pq.write_table(pa.Table.from_pandas(labels, preserve_index=False), label_path)
            fixture.refresh_label_registry()
            fixture.refresh_feature_label_binding()

            with self.assertRaisesRegex(SHSZH1FeatureEvidenceError, "BJ symbol"):
                run_shsz_h1_feature_evidence(
                    label_root=fixture.label_root,
                    feature_asset_root=fixture.feature_root,
                    output_dir=fixture.output_root,
                    code_commit="fixture",
                    bootstrap_iterations=3,
                )


class _FixtureEvidenceAsset:
    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.label_root = self.root / "labels"
        self.feature_root = self.root / "features"
        self.output_root = self.root / "evidence"
        self.dates = [f"2025-01-{day:02d}" for day in range(2, 9)]
        self.symbols = tuple(f"{index:06d}.SZ" for index in range(1, 11))
        self._write_labels()
        self._write_features()

    def __enter__(self) -> "_FixtureEvidenceAsset":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()

    def _write_labels(self) -> None:
        rows = []
        for day_index, trade_date in enumerate(self.dates):
            for symbol_index, symbol in enumerate(self.symbols, start=1):
                strength = float(symbol_index + day_index)
                rows.append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "eligible_for_training": True,
                        "alpha_relevance_grade_10d": symbol_index % 5,
                        "alpha_top10_10d": symbol_index >= 9,
                        "alpha_target_10d": strength / 100.0,
                        "future_return_10d": strength / 100.0,
                        "net_return_after_cost_10d": strength / 100.0,
                        "severe_negative_10d": False,
                        "entry_price": 10.0,
                        "exit_price": 10.0 * (1.0 + strength / 100.0),
                        "exit_trade_date": trade_date,
                        "entry_tradeable": True,
                        "path_ambiguous_10d": False,
                        "horizon_available_10d": True,
                    }
                )
        label_path = self.label_root / "labels" / "shard=00" / "data.parquet"
        label_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False), label_path)
        split = {
            "development_dates": self.dates,
            "A_dev_train_symbols": [symbol.split(".")[0] for symbol in self.symbols[:8]],
            "C_dev_unseen_symbols": [symbol.split(".")[0] for symbol in self.symbols[8:]],
            "stock_holdout_symbols": [symbol.split(".")[0] for symbol in self.symbols[8:]],
            "embargo_trade_days": 20,
            "walk_forward": [
                {
                    "fold": index,
                    "training_dates": self.dates[:index],
                    "validation_dates": [self.dates[index]],
                    "training_symbols": [symbol.split(".")[0] for symbol in self.symbols[:8]],
                    "train_start": self.dates[0],
                    "train_end": self.dates[index - 1],
                    "validation_start": self.dates[index],
                    "validation_end": self.dates[index],
                }
                for index in range(1, 6)
            ],
            "future_holdout": {
                "status": "awaiting_model_freeze_and_future_labels",
                "formal_evaluation_allowed": False,
            },
            "split_sha256": "fixture-split-internal",
        }
        self.label_root.mkdir(parents=True, exist_ok=True)
        (self.label_root / "development_split_plan.json").write_text(json.dumps(split), encoding="utf-8")
        manifest = {
            "status": "complete_development_labels_ready",
            "research_ready": True,
            "production_integration_allowed": False,
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
            "source": {"panel_rebuild_manifest_sha256": "a" * 64},
        }
        (self.label_root / "label_split_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.refresh_label_registry()

    def refresh_label_registry(self) -> None:
        label_path = next((self.label_root / "labels").rglob("*.parquet"))
        registry = {
            "dataset_id": "fixture-labels",
            "source_panel_manifest_sha256": "a" * 64,
            "label_quality_passed": True,
            "production_integration_allowed": False,
            "future_holdout_status": "awaiting_model_freeze_and_future_labels",
            "split_sha256": "fixture-split-internal",
            "label_files": [
                {
                    "path": str(label_path.relative_to(self.label_root)),
                    "row_count": int(pq.ParquetFile(label_path).metadata.num_rows),
                    "bytes": int(label_path.stat().st_size),
                    "sha256": _sha256_file(label_path),
                }
            ],
        }
        (self.label_root / "dataset_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    def _write_features(self) -> None:
        matrix = self.feature_root / "matrix"
        files = []
        for day_index, trade_date in enumerate(self.dates):
            rows = []
            for symbol_index, symbol in enumerate(self.symbols, start=1):
                strength = float(symbol_index + day_index)
                rows.append(
                    {
                        "trade_date": trade_date,
                        "symbol": symbol.split(".")[0],
                        "industry_return_5d_rank": strength / 20.0,
                        "industry_return_5d_excess": strength / 100.0,
                        "industry_return_20d_rank": strength / 20.0,
                        "industry_return_20d_excess": strength / 100.0,
                        "adjusted_return_60d": -strength / 100.0,
                    }
                )
            path = matrix / f"trade_date={trade_date}" / "data.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False)
            table = table.set_column(0, "trade_date", pa.array([trade_date] * len(rows), type=pa.string()))
            table = table.set_column(1, "symbol", pa.array([row["symbol"] for row in rows], type=pa.string()))
            pq.write_table(table, path)
            files.append(
                {
                    "path": str(path.relative_to(self.feature_root)),
                    "trade_date": trade_date,
                    "row_count": len(rows),
                    "bytes": int(path.stat().st_size),
                    "sha256": _sha256_file(path),
                }
            )
        self._feature_manifest = {
            "status": "complete",
            "research_ready": True,
            "production_integration_allowed": False,
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
            "feature_asset_version": "shsz_r1_feature_asset_v1",
            "panel_manifest_sha256": "a" * 64,
            "label_registry_sha256": _sha256_file(self.label_root / "dataset_registry.json"),
            "label_split_sha256": _sha256_file(self.label_root / "development_split_plan.json"),
            "formal_future_holdout_status": "awaiting_model_freeze_and_future_labels",
            "matrix_path": str(matrix),
            "matrix_files": files,
            "feature_contract": {
                "features": [
                    {"name": "industry_return_5d_rank", "group": "industry_relative"},
                    {"name": "industry_return_5d_excess", "group": "industry_relative"},
                    {"name": "industry_return_20d_rank", "group": "industry_relative"},
                    {"name": "industry_return_20d_excess", "group": "industry_relative"},
                    {"name": "adjusted_return_60d", "group": "price_return"},
                ]
            },
        }
        self.feature_root.mkdir(parents=True, exist_ok=True)
        self.refresh_feature_label_binding()

    def refresh_feature_label_binding(self) -> None:
        manifest = {key: value for key, value in self._feature_manifest.items() if key != "sha256"}
        manifest["label_registry_sha256"] = _sha256_file(self.label_root / "dataset_registry.json")
        manifest["label_split_sha256"] = _sha256_file(self.label_root / "development_split_plan.json")
        manifest["sha256"] = _sha256_json(manifest)
        self._feature_manifest = manifest
        (self.feature_root / "feature_asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
