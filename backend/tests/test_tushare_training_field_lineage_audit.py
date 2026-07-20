from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.full_market_ml.tushare_training_field_lineage_audit import (
    DETAILED_MONEYFLOW_AMOUNT_FIELDS,
    FieldLineageAuditError,
    audit_tushare_training_field_lineage,
)


_DERIVED_FEATURES = (
    "medium_net_flow_persistence_20d",
    "large_net_flow_persistence_20d",
    "price_flow_divergence_5d",
    "price_flow_divergence_20d",
    "flow_minus_industry_median",
)


class TushareTrainingFieldLineageAuditTests(unittest.TestCase):
    def test_marks_fields_available_only_when_they_reach_the_matrix(self) -> None:
        with _FixtureAsset(include_dataset_fields=True, include_matrix_fields=True) as fixture:
            report = fixture.audit()

        self.assertEqual("available_for_later_admission_test", report["overall_verdict"])
        self.assertEqual("available", report["derived_features"]["medium_net_flow_persistence_20d"]["status"])
        self.assertEqual(1.0, report["stages"]["raw"]["field_coverage"]["buy_md_amount"])
        self.assertEqual(1.0, report["stages"]["dataset"]["field_coverage"]["buy_md_amount"])
        self.assertEqual(1.0, report["stages"]["matrix"]["field_coverage"]["medium_net_flow_persistence_20d"])

    def test_marks_raw_to_dataset_gap_when_raw_fields_are_not_preserved(self) -> None:
        with _FixtureAsset(include_dataset_fields=False, include_matrix_fields=False) as fixture:
            report = fixture.audit()

        self.assertEqual("pipeline_lineage_gap", report["overall_verdict"])
        self.assertEqual("raw_to_dataset_gap", report["derived_features"]["medium_net_flow_persistence_20d"]["status"])
        self.assertIn("buy_md_amount", report["stages"]["dataset"]["missing_columns"])

    def test_marks_derived_feature_not_materialized_when_matrix_is_missing_it(self) -> None:
        with _FixtureAsset(include_dataset_fields=True, include_matrix_fields=False) as fixture:
            report = fixture.audit()

        self.assertEqual("derived_feature_not_materialized", report["overall_verdict"])
        self.assertEqual("derived_feature_not_materialized", report["derived_features"]["large_net_flow_persistence_20d"]["status"])

    def test_marks_source_missing_without_misreporting_a_pipeline_gap(self) -> None:
        with _FixtureAsset(include_raw_fields=False, include_dataset_fields=False, include_matrix_fields=False) as fixture:
            report = fixture.audit()

        self.assertEqual("source_unavailable", report["overall_verdict"])
        self.assertEqual("source_missing", report["derived_features"]["flow_minus_industry_median"]["status"])

    def test_rejects_a_missing_stage_root(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(FieldLineageAuditError, "raw root"):
                audit_tushare_training_field_lineage(
                    raw_root=Path(root) / "missing",
                    dataset_root=Path(root) / "dataset",
                    matrix_root=Path(root) / "matrix",
                    sample_dates=("2024-01-02",),
                )


class _FixtureAsset:
    def __init__(self, *, include_raw_fields: bool = True, include_dataset_fields: bool, include_matrix_fields: bool) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.raw_root = root / "raw-asset"
        self.dataset_root = root / "dataset-asset"
        self.matrix_root = root / "matrix"
        self._write_raw(include_raw_fields)
        self._write_dataset(include_dataset_fields)
        self._write_matrix(include_matrix_fields)

    def __enter__(self) -> "_FixtureAsset":
        return self

    def __exit__(self, *_: object) -> None:
        self._temporary.cleanup()

    def audit(self) -> dict[str, object]:
        return audit_tushare_training_field_lineage(
            raw_root=self.raw_root,
            dataset_root=self.dataset_root,
            matrix_root=self.matrix_root,
            sample_dates=("2024-01-02",),
        )

    def _write_raw(self, include_fields: bool) -> None:
        path = self.raw_root / "raw" / "endpoint=moneyflow" / "trade_date=20240102" / "data.parquet"
        row: dict[str, object] = {"ts_code": "000001.SZ", "trade_date": "20240102", "net_mf_amount": 10.0}
        if include_fields:
            row.update({field: 1.0 for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS})
        _write_parquet(path, row)

    def _write_dataset(self, include_fields: bool) -> None:
        path = self.dataset_root / "artifacts" / "full-build" / "dataset-v3" / "shard=00" / "data.parquet"
        row: dict[str, object] = {"symbol": "000001", "trade_date": "2024-01-02", "net_mf_amount": 10.0}
        if include_fields:
            row.update({field: 1.0 for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS})
        _write_parquet(path, row)

    def _write_matrix(self, include_fields: bool) -> None:
        path = self.matrix_root / "shard=00" / "data.parquet"
        row: dict[str, object] = {"symbol": "000001", "trade_date": "2024-01-02"}
        if include_fields:
            row.update({field: 0.2 for field in _DERIVED_FEATURES})
        _write_parquet(path, row)


def _write_parquet(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(pd.DataFrame([row]), preserve_index=False), path)
