"""Read-only lineage audit for detailed TuShare money-flow training fields."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq


DETAILED_MONEYFLOW_AMOUNT_FIELDS = (
    "buy_sm_amount",
    "sell_sm_amount",
    "buy_md_amount",
    "sell_md_amount",
    "buy_lg_amount",
    "sell_lg_amount",
    "buy_elg_amount",
    "sell_elg_amount",
)

DERIVED_MONEYFLOW_FEATURE_DEPENDENCIES = {
    "medium_net_flow_persistence_20d": ("buy_md_amount", "sell_md_amount"),
    "large_net_flow_persistence_20d": ("buy_lg_amount", "sell_lg_amount"),
    "price_flow_divergence_5d": (
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
    ),
    "price_flow_divergence_20d": (
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
    ),
    "flow_minus_industry_median": (
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
    ),
}


class FieldLineageAuditError(ValueError):
    """Raised when supplied immutable training assets cannot be audited safely."""


@dataclass(frozen=True)
class _StageSpec:
    name: str
    root: Path
    pattern: str
    fields: tuple[str, ...]


def audit_tushare_training_field_lineage(
    *,
    raw_root: str | Path,
    dataset_root: str | Path,
    matrix_root: str | Path,
    sample_dates: Iterable[str],
) -> dict[str, object]:
    """Audit retained raw-to-matrix lineage without mutating any asset.

    The historical panel for the current full-market asset was not retained, so
    this function deliberately reports that provenance gap instead of inferring
    a runtime panel from source code or reconstructing one during an audit.
    """
    requested_dates = _normalise_dates(sample_dates)
    raw = _require_directory(raw_root, "raw root")
    dataset = _require_directory(dataset_root, "dataset root")
    matrix = _require_directory(matrix_root, "matrix root")
    stages = {
        "raw": _inspect_raw_stage(raw, requested_dates),
        "dataset": _inspect_stage(
            _StageSpec(
                name="dataset",
                root=dataset / "artifacts" / "full-build" / "dataset-v3",
                pattern="shard=*/data.parquet",
                fields=DETAILED_MONEYFLOW_AMOUNT_FIELDS,
            ),
            requested_dates,
        ),
        "matrix": _inspect_stage(
            _StageSpec(
                name="matrix",
                root=matrix,
                pattern="shard=*/data.parquet",
                fields=tuple(DERIVED_MONEYFLOW_FEATURE_DEPENDENCIES),
            ),
            requested_dates,
        ),
    }
    derived_features = {
        name: _derived_feature_status(name, dependencies, stages)
        for name, dependencies in DERIVED_MONEYFLOW_FEATURE_DEPENDENCIES.items()
    }
    statuses = {str(item["status"]) for item in derived_features.values()}
    overall_verdict = _overall_verdict(statuses)
    return {
        "schema_version": 1,
        "sample_dates": list(requested_dates),
        "asset_roots": {
            "raw": str(raw),
            "dataset": str(dataset),
            "matrix": str(matrix),
        },
        "stages": stages,
        "unretained_panel_stage": {
            "status": "not_retained",
            "reason": "the supplied immutable asset does not include a panel root",
            "static_join_contract": "backend/app/evaluation/full_market_ml/panel.py",
        },
        "derived_features": derived_features,
        "overall_verdict": overall_verdict,
        "production_integration_allowed": False,
        "interpretation": (
            "A lineage verdict proves only retained data availability. "
            "It is not predictive-performance, model-admission, or production evidence."
        ),
    }


def _inspect_raw_stage(root: Path, sample_dates: tuple[str, ...]) -> dict[str, object]:
    endpoint_root = root / "raw" / "endpoint=moneyflow"
    if not endpoint_root.is_dir():
        raise FieldLineageAuditError(f"raw root has no moneyflow partitions: {endpoint_root}")
    files: list[Path] = []
    missing_dates: list[str] = []
    for trade_date in sample_dates:
        path = endpoint_root / f"trade_date={trade_date.replace('-', '')}" / "data.parquet"
        if path.is_file():
            files.append(path)
        else:
            missing_dates.append(trade_date)
    return _inspect_files(
        stage_name="raw",
        files=files,
        fields=DETAILED_MONEYFLOW_AMOUNT_FIELDS,
        sample_dates=sample_dates,
        missing_sample_dates=missing_dates,
    )


def _inspect_stage(spec: _StageSpec, sample_dates: tuple[str, ...]) -> dict[str, object]:
    if not spec.root.is_dir():
        raise FieldLineageAuditError(f"{spec.name} root is missing: {spec.root}")
    files = tuple(sorted(spec.root.glob(spec.pattern)))
    if not files:
        raise FieldLineageAuditError(f"{spec.name} root has no parquet shards: {spec.root}")
    return _inspect_files(
        stage_name=spec.name,
        files=files,
        fields=spec.fields,
        sample_dates=sample_dates,
        missing_sample_dates=(),
    )


def _inspect_files(
    *,
    stage_name: str,
    files: Iterable[Path],
    fields: Iterable[str],
    sample_dates: tuple[str, ...],
    missing_sample_dates: Iterable[str],
) -> dict[str, object]:
    field_names = tuple(fields)
    file_paths = tuple(files)
    schema_columns: set[str] = set()
    row_count = 0
    non_null_counts = {field: 0 for field in field_names}
    observed_dates: set[str] = set()
    files_with_trade_date = 0
    for path in file_paths:
        parquet = pq.ParquetFile(path)
        columns = set(parquet.schema_arrow.names)
        schema_columns.update(columns)
        if "trade_date" not in columns:
            continue
        files_with_trade_date += 1
        requested_columns = ["trade_date", *[field for field in field_names if field in columns]]
        frame = pq.read_table(path, columns=requested_columns).to_pandas()
        date_values = frame["trade_date"].map(_normalise_date)
        selected = date_values.isin(sample_dates)
        if not bool(selected.any()):
            continue
        observed_dates.update(date_values.loc[selected].tolist())
        row_count += int(selected.sum())
        for field in field_names:
            if field in frame:
                non_null_counts[field] += int(frame.loc[selected, field].notna().sum())
    coverage = {
        field: (round(non_null_counts[field] / row_count, 8) if row_count else 0.0)
        for field in field_names
    }
    missing = sorted(set(field_names) - schema_columns)
    requested = set(sample_dates)
    missing_dates = sorted((requested - observed_dates) | {str(value) for value in missing_sample_dates})
    return {
        "stage": stage_name,
        "file_count": len(file_paths),
        "files_with_trade_date": files_with_trade_date,
        "sample_row_count": row_count,
        "observed_sample_dates": sorted(observed_dates),
        "missing_sample_dates": missing_dates,
        "schema_columns": sorted(schema_columns),
        "schema_sha256": _schema_hash(schema_columns),
        "missing_columns": missing,
        "non_null_counts": non_null_counts,
        "field_coverage": coverage,
    }


def _derived_feature_status(
    feature: str,
    dependencies: Iterable[str],
    stages: dict[str, object],
) -> dict[str, object]:
    raw = _stage_mapping(stages, "raw")
    dataset = _stage_mapping(stages, "dataset")
    matrix = _stage_mapping(stages, "matrix")
    required = tuple(dependencies)
    if not _fields_available(raw, required):
        status = "source_missing"
    elif not _fields_available(dataset, required):
        status = "raw_to_dataset_gap"
    elif feature in set(matrix["missing_columns"]) or float(matrix["field_coverage"].get(feature, 0.0)) <= 0.0:
        status = "derived_feature_not_materialized"
    else:
        status = "available"
    return {
        "status": status,
        "required_raw_fields": list(required),
        "raw_coverage": {field: raw["field_coverage"].get(field, 0.0) for field in required},
        "dataset_coverage": {field: dataset["field_coverage"].get(field, 0.0) for field in required},
        "matrix_coverage": float(matrix["field_coverage"].get(feature, 0.0)),
    }


def _overall_verdict(statuses: set[str]) -> str:
    if "source_missing" in statuses:
        return "source_unavailable"
    if "raw_to_dataset_gap" in statuses:
        return "pipeline_lineage_gap"
    if "derived_feature_not_materialized" in statuses:
        return "derived_feature_not_materialized"
    if statuses == {"available"}:
        return "available_for_later_admission_test"
    return "inconclusive_input_layout"


def _fields_available(stage: dict[str, object], fields: Iterable[str]) -> bool:
    missing = set(stage["missing_columns"])
    coverage = stage["field_coverage"]
    return all(field not in missing and float(coverage.get(field, 0.0)) > 0.0 for field in fields)


def _stage_mapping(stages: dict[str, object], name: str) -> dict[str, object]:
    stage = stages[name]
    if not isinstance(stage, dict):
        raise FieldLineageAuditError(f"invalid {name} stage report")
    return stage


def _require_directory(value: str | Path, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise FieldLineageAuditError(f"{name} is missing: {path}")
    return path


def _normalise_dates(values: Iterable[str]) -> tuple[str, ...]:
    dates = tuple(dict.fromkeys(_normalise_date(value) for value in values))
    if not dates:
        raise FieldLineageAuditError("sample_dates cannot be empty")
    return dates


def _normalise_date(value: object) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise FieldLineageAuditError(f"invalid trade date: {value}")
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _schema_hash(columns: Iterable[str]) -> str:
    payload = "\n".join(sorted(columns)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
