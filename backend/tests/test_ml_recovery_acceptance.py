from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.ml_recovery_acceptance import (
    FIXED_FEATURES,
    MLRecoveryAcceptanceError,
    audit_fixed_features,
    build_recovery_dataset,
    build_recovery_rows,
    run_fixed_logistic_oof,
    validate_fixed_features,
    verify_recovery_inputs,
)


class MLRecoveryAcceptanceInputTests(unittest.TestCase):
    def test_rejects_a_panel_manifest_not_bound_to_r1_and_r2(self):
        with tempfile.TemporaryDirectory() as temporary:
            roots = _asset_roots(Path(temporary))
            _write_fixture_assets(roots)
            _write_json(
                roots["panel"] / "panel_rebuild_manifest.json",
                {**_panel_manifest(), "tampered_after_registration": True},
            )

            with self.assertRaisesRegex(MLRecoveryAcceptanceError, "panel manifest SHA256"):
                verify_recovery_inputs(roots["labels"], roots["features"], roots["panel"])

    def test_rejects_a_split_that_exposes_a_final_holdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            roots = _asset_roots(Path(temporary))
            _write_fixture_assets(roots, formal_evaluation_allowed=True)

            with self.assertRaisesRegex(MLRecoveryAcceptanceError, "future holdout"):
                verify_recovery_inputs(roots["labels"], roots["features"], roots["panel"])


class MLRecoveryAcceptanceDatasetTests(unittest.TestCase):
    def test_dataset_loader_reads_only_registered_development_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            label_path = root / "labels" / "labels" / "shard=00" / "data.parquet"
            matrix_path = root / "features" / "matrix" / "trade_date=2025-01-02" / "data.parquet"
            label_path.parent.mkdir(parents=True)
            matrix_path.parent.mkdir(parents=True)
            _write_parquet(label_path, _recovery_labels().to_dict("list"))
            _write_parquet(matrix_path, _recovery_matrix().to_dict("list"))
            inputs = {
                "labels_root": root / "labels",
                "features_root": root / "features",
                "registry": {"label_files": [_file_entry(label_path, root / "labels", "2025-01-02")]},
                "feature_manifest": {
                    "matrix_files": [_file_entry(matrix_path, root / "features", "2025-01-02")],
                    "feature_contract": {"features": [{"name": feature} for feature in FIXED_FEATURES]},
                },
                "split_plan": {"development_dates": ("2025-01-02",)},
            }

            rows, report = build_recovery_dataset(inputs)

        self.assertEqual(6, len(rows))
        self.assertEqual(6, report["source_label_row_count"])
        self.assertEqual(6, report["source_matrix_row_count"])

    def test_common_mask_drops_rows_missing_any_fixed_feature(self):
        labels = _recovery_labels()
        matrix = _recovery_matrix()
        matrix.loc[0, "turnover_rate_rank"] = None

        rows, report = build_recovery_rows(labels, matrix)

        self.assertEqual(5, len(rows))
        self.assertEqual(1, report["excluded_missing_feature_count"])
        self.assertTrue(rows["risk_eligible"].all())
        self.assertTrue(all(f"rank__{feature}" in rows for feature in FIXED_FEATURES))

    def test_rejects_future_or_label_named_feature(self):
        with self.assertRaisesRegex(MLRecoveryAcceptanceError, "future or label"):
            validate_fixed_features(("adjusted_return_20d", "future_return_10d"))

    def test_feature_audit_reports_each_fixed_feature_for_a_and_c(self):
        rows, _ = build_recovery_rows(_recovery_labels(), _recovery_matrix())

        diagnostics = audit_fixed_features(rows, _diagnostic_split())

        self.assertEqual(len(FIXED_FEATURES) * 2, len(diagnostics))
        self.assertEqual(set(FIXED_FEATURES), set(diagnostics["feature"]))
        self.assertTrue(diagnostics["coverage"].eq(1.0).all())


class MLRecoveryAcceptanceOOFTests(unittest.TestCase):
    def test_oof_fit_never_reads_validation_dates_or_c_symbols(self):
        predictions, report = run_fixed_logistic_oof(_oof_rows(), _oof_split())

        self.assertEqual({"A", "C"}, set(predictions["quadrant"]))
        self.assertTrue((predictions["train_max_date"] < predictions["trade_date"]).all())
        self.assertFalse(set(_oof_split()["C_dev_unseen_symbols"]) & set(report["fit_symbols_by_fold"]["1"]))
        self.assertTrue(pd.to_numeric(predictions["model_score"], errors="coerce").notna().all())


def _asset_roots(root: Path) -> dict[str, Path]:
    return {
        "labels": root / "labels",
        "features": root / "features",
        "panel": root / "panel",
    }


def _write_fixture_assets(roots: dict[str, Path], *, formal_evaluation_allowed: bool = False) -> None:
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)

    panel_path = roots["panel"] / "panel_rebuild_manifest.json"
    _write_json(panel_path, _panel_manifest())
    panel_sha = _sha256(panel_path)

    label_path = roots["labels"] / "labels" / "shard=00" / "data.parquet"
    label_path.parent.mkdir(parents=True, exist_ok=True)
    _write_parquet(label_path, {"trade_date": ["2025-01-02"], "symbol": ["000001.SZ"]})
    split_path = roots["labels"] / "development_split_plan.json"
    _write_json(split_path, _split_payload(formal_evaluation_allowed=formal_evaluation_allowed))
    registry_path = roots["labels"] / "dataset_registry.json"
    _write_json(
        registry_path,
        {
            "label_quality_passed": True,
            "production_integration_allowed": False,
            "future_holdout_status": "awaiting_model_freeze_and_future_labels",
            "source_panel_manifest_sha256": panel_sha,
            "label_files": [_file_entry(label_path, roots["labels"], "2025-01-02")],
        },
    )
    _write_json(
        roots["labels"] / "label_split_manifest.json",
        {
            "status": "complete_development_labels_ready",
            "research_ready": True,
            "production_integration_allowed": False,
            "universe_id": "shsz_a_share_v1",
            "allowed_exchanges": ["SH", "SZ"],
        },
    )

    matrix_path = roots["features"] / "matrix" / "trade_date=2025-01-02" / "data.parquet"
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    _write_parquet(matrix_path, {"trade_date": ["2025-01-02"], "symbol": ["000001.SZ"]})
    feature_manifest = {
        "status": "complete",
        "research_ready": True,
        "production_integration_allowed": False,
        "formal_future_holdout_status": "awaiting_model_freeze_and_future_labels",
        "universe_id": "shsz_a_share_v1",
        "allowed_exchanges": ["SH", "SZ"],
        "panel_manifest_sha256": panel_sha,
        "label_registry_sha256": _sha256(registry_path),
        "label_split_sha256": _sha256(split_path),
        "matrix_files": [_file_entry(matrix_path, roots["features"], "2025-01-02")],
    }
    feature_manifest["sha256"] = _payload_sha256(feature_manifest)
    _write_json(roots["features"] / "feature_asset_manifest.json", feature_manifest)


def _split_payload(*, formal_evaluation_allowed: bool) -> dict[str, object]:
    return {
        "development_dates": ["2025-01-02"],
        "future_holdout": {
            "status": "awaiting_model_freeze_and_future_labels",
            "formal_evaluation_allowed": formal_evaluation_allowed,
        },
        "quadrants": {
            "A_dev_train_symbols": ["000001"],
            "C_dev_unseen_symbols": ["000002"],
        },
        "walk_forward": [
            {
                "fold": index,
                "training_dates": ["2025-01-02"],
                "validation_dates": ["2025-01-02"],
                "training_symbols": ["000001"],
            }
            for index in range(1, 6)
        ],
    }


def _panel_manifest() -> dict[str, object]:
    return {
        "status": "complete_shsz_panel_rebuilt",
        "research_ready": True,
        "production_integration_allowed": False,
        "universe_id": "shsz_a_share_v1",
        "allowed_exchanges": ["SH", "SZ"],
    }


def _recovery_labels() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": ["2025-01-02"] * 6,
            "symbol": [f"00000{index}.SZ" for index in range(1, 7)],
            "eligible_for_training": [True] * 6,
            "entry_tradeable": [True] * 6,
            "horizon_available_10d": [True] * 6,
            "path_ambiguous_10d": [False] * 6,
            "alpha_top10_10d": [False, False, False, False, True, True],
            "alpha_target_10d": [-0.05, -0.03, -0.01, 0.01, 0.04, 0.08],
            "net_return_after_cost_10d": [-0.04, -0.02, -0.01, 0.01, 0.03, 0.07],
            "severe_negative_10d": [True, False, False, False, False, False],
        }
    )


def _recovery_matrix() -> pd.DataFrame:
    rows = {
        "trade_date": ["2025-01-02"] * 6,
        "symbol": [f"00000{index}.SZ" for index in range(1, 7)],
    }
    for index, feature in enumerate(FIXED_FEATURES, start=1):
        rows[feature] = [float(index * 10 + row) for row in range(1, 7)]
    return pd.DataFrame(rows)


def _diagnostic_split() -> dict[str, object]:
    return {
        "A_dev_train_symbols": ("000001", "000002", "000003"),
        "C_dev_unseen_symbols": ("000004", "000005", "000006"),
        "walk_forward": (
            {
                "fold": 1,
                "training_dates": ("2025-01-01",),
                "validation_dates": ("2025-01-02",),
                "training_symbols": ("000001", "000002", "000003"),
            },
        ),
    }


def _oof_rows() -> pd.DataFrame:
    rows = []
    features = tuple(f"rank__{feature}" for feature in FIXED_FEATURES)
    for trade_date in ("2025-01-02", "2025-01-03", "2025-01-06"):
        for symbol_index, symbol in enumerate(("000001", "000002", "000003", "000004", "000005", "000006"), start=1):
            strong = symbol_index >= 3
            row = {
                "trade_date": trade_date,
                "symbol": symbol,
                "risk_eligible": True,
                "alpha_top10_10d": strong,
                "alpha_target_10d": 0.02 * symbol_index,
                "net_return_after_cost_10d": 0.01 * symbol_index,
                "severe_negative_10d": False,
            }
            for feature_index, feature in enumerate(features, start=1):
                row[feature] = (symbol_index + feature_index) / 12.0
            rows.append(row)
    return pd.DataFrame(rows)


def _oof_split() -> dict[str, object]:
    return {
        "A_dev_train_symbols": ("000001", "000002", "000003", "000004"),
        "C_dev_unseen_symbols": ("000005", "000006"),
        "walk_forward": (
            {
                "fold": 1,
                "training_dates": ("2025-01-02", "2025-01-03"),
                "validation_dates": ("2025-01-06",),
                "training_symbols": ("000001", "000002", "000003", "000004"),
            },
        ),
    }


def _file_entry(path: Path, root: Path, trade_date: str) -> dict[str, object]:
    return {
        "path": str(path.relative_to(root)),
        "trade_date": trade_date,
        "row_count": pq.ParquetFile(path).metadata.num_rows,
        "sha256": _sha256(path),
    }


def _write_parquet(path: Path, values: dict[str, list[object]]) -> None:
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(values), preserve_index=False), path)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_sha256(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
