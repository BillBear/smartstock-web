"""File-backed runner for registered-development label semantic audits."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .label_semantic_audit import _REQUIRED_COLUMNS, audit_label_semantics
from .train_only_scorecard_oof import ScorecardOofError
from .v3_feature_evidence import _development_only_split, _load_eligible_feature_asset, _read_json


def run_label_semantic_audit(
    *,
    source_dataset_root: str | Path,
    feature_asset_root: str | Path,
    output_root: str | Path,
    code_commit: str,
) -> dict[str, Any]:
    """Audit label meaning on registered development dates only."""
    source_root = Path(source_dataset_root).expanduser().resolve()
    asset_root = Path(feature_asset_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    manifest = _load_eligible_feature_asset(asset_root, source_root)
    split_payload = _read_json(source_root / "artifacts" / "full-build" / "split_plan_v2.json")
    split_plan = _development_only_split(split_payload)
    matrix_root = Path(str(manifest["matrix_path"])).expanduser().resolve()
    _prepare_output(destination)
    _write_json(destination / "progress.json", _progress("running", "load-development-labels", total_dates=len(split_plan.development_dates)))
    try:
        rows = _load_development_rows(matrix_root, split_plan.development_dates)
        _write_json(destination / "progress.json", _progress("running", "audit-label-semantics", row_count=len(rows)))
        result = audit_label_semantics(rows, development_dates=split_plan.development_dates)
        daily = result.pop("daily_distribution")
        daily.to_csv(destination / "daily_label_distribution.csv", index=False)
        _write_json(destination / "label_overlap.json", result["overlap"])
        _write_json(destination / "label_disagreement_reasons.json", result["disagreement_reasons"])
        report = {
            **result,
            "code_commit": str(code_commit),
            "source_dataset_id": str(manifest.get("source_dataset_id", "")),
            "source_dataset_sha256": str(manifest.get("source_dataset_sha256", "")),
            "feature_asset_manifest_sha256": str(manifest.get("sha256", "")),
            "feature_contract_sha256": str(manifest.get("feature_contract_sha256", "")),
            "split_sha256": str(split_payload.get("sha256", "")),
            "model_status": (
                "research_only_label_integrity_failure"
                if not result["old_label_reconstruction_matches_stored"]
                else "research_only_label_audit_complete"
            ),
            "limitations": [
                "This audit uses future outcomes only to inspect labels and must not feed signal-time features.",
                "It does not select a label, tune thresholds, train a model, or authorize production integration.",
                "Only registered development dates are loaded; sealed temporal audit dates are rejected by construction.",
            ],
            "generated_at": _now(),
        }
        _write_json(destination / "label_semantic_report.json", report)
        _write_json(destination / "progress.json", _progress("complete", "complete", row_count=len(rows), date_count=result["date_count"]))
        return report
    except BaseException as error:
        _write_json(
            destination / "progress.json",
            _progress(
                "aborted" if isinstance(error, KeyboardInterrupt) else "failed",
                "failed",
                error_type=type(error).__name__,
                error=str(error),
            ),
        )
        raise


def _load_development_rows(matrix_root: Path, development_dates: tuple[str, ...]) -> pd.DataFrame:
    frames = []
    columns = sorted(_REQUIRED_COLUMNS)
    for position, trade_date in enumerate(development_dates, start=1):
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise ScorecardOofError(f"feature matrix misses registered development date: {trade_date}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise ScorecardOofError(f"feature matrix {trade_date} misses label-audit columns: " + ", ".join(missing))
        frames.append(pq.read_table(path, columns=columns).to_pandas())
    if not frames:
        raise ScorecardOofError("registered development period has no label-audit partitions")
    return pd.concat(frames, ignore_index=True)


def _prepare_output(destination: Path) -> None:
    if destination.exists():
        if any(destination.iterdir()):
            raise ScorecardOofError(f"label semantic audit output root must be empty: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=False)


def _progress(status: str, stage: str, **payload: Any) -> dict[str, Any]:
    return {"status": status, "stage": stage, "updated_at": _now(), **payload}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
