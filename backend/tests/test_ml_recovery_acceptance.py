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
    MLRecoveryAcceptanceError,
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
