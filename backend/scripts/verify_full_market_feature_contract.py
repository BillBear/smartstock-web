#!/usr/bin/env python3
"""Verify a frozen feature contract against one immutable full-market asset."""
from __future__ import annotations

import argparse
import json
import os
import resource
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# ``python scripts/...`` sets sys.path to the scripts directory, while the
# documented command is intentionally run from backend without PYTHONPATH.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.feature_contract import build_features_as_of, build_full_market_feature_contract
from app.services.ml_online_feature_provider import OnlineFeatureProvider


RAW_COLUMNS = (
    "trade_date",
    "symbol",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "volume_shares",
    "amount_cny",
    "turnover_rate",
    "total_mv",
    "circ_mv",
    "pe",
    "pb",
    "ps",
    "industry_l1",
    "listing_age_trade_days",
    "valid_ohlc",
)


def main() -> int:
    args = _parse_args()
    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.json"
    try:
        report = verify_feature_contract(
            dataset_root=dataset_root,
            output_dir=output_dir,
            history_sessions=args.history_sessions,
            code_commit=args.code_commit,
            progress_path=progress_path,
        )
    except Exception as error:
        _write_json(
            progress_path,
            {
                "status": "failed",
                "updated_at": _now(),
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        raise
    _write_json(output_dir / "feature_contract_verification.json", report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def verify_feature_contract(
    *,
    dataset_root: Path,
    output_dir: Path,
    history_sessions: int,
    code_commit: str,
    progress_path: Path,
) -> dict[str, Any]:
    if history_sessions < 61:
        raise ValueError("history_sessions must cover the 60-session registered lookback")
    quality = _read_json(dataset_root / "artifacts" / "full-build" / "quality_report.json")
    split = _read_json(dataset_root / "artifacts" / "full-build" / "split_plan_v2.json")
    registry = _read_json(dataset_root / "dataset_registry_v2.json")
    data_path = dataset_root / "artifacts" / "full-build" / "dataset.parquet"
    contract = build_full_market_feature_contract(moneyflow_coverage=float(quality["moneyflow_coverage"]))
    parquet = pq.ParquetFile(data_path)
    schema = set(parquet.schema_arrow.names)
    missing = sorted((set(RAW_COLUMNS) | set(contract.feature_names)) - schema)
    if missing:
        raise ValueError("canonical dataset is missing contract columns: " + ", ".join(missing))

    observed_dates = tuple(str(value) for value in quality["observed_trade_dates"])
    if len(observed_dates) < history_sessions:
        raise ValueError("canonical dataset does not have enough observed sessions for parity verification")
    as_of_date = observed_dates[-1]
    history_dates = set(observed_dates[-history_sessions:])
    fold_dates = {f"fold-{fold['fold']}": set(str(value) for value in fold["test_dates"]) for fold in split["outer_folds"]}
    coverage_dates = set().union(*fold_dates.values())
    counts = {
        fold_name: {feature: [0, 0] for feature in contract.required_feature_names}
        for fold_name in fold_dates
    }

    _write_progress(progress_path, "scan-raw-history", 0, parquet.metadata.num_row_groups)
    raw_frames: list[pd.DataFrame] = []
    for index, batch in enumerate(parquet.iter_batches(batch_size=65_536, columns=list(RAW_COLUMNS)), start=1):
        frame = batch.to_pandas()
        selected = frame.loc[frame["trade_date"].astype(str).isin(history_dates)]
        if not selected.empty:
            raw_frames.append(selected)
        if index % 8 == 0:
            _write_progress(progress_path, "scan-raw-history", index, parquet.metadata.num_row_groups)
    raw_history = pd.concat(raw_frames, ignore_index=True)

    _write_progress(progress_path, "build-offline-online-parity", 0, 2)
    source_as_of_dates = {source: as_of_date for source in contract.registered_sources}
    source_qualities = {source: "valid-with-rows" for source in contract.registered_sources}
    offline = build_features_as_of(raw_history, as_of_date=as_of_date, contract=contract).sort_values("symbol").reset_index(drop=True)
    _write_progress(progress_path, "build-offline-online-parity", 1, 2)
    online = OnlineFeatureProvider(contract).build_features_as_of(
        raw_history,
        as_of_date=as_of_date,
        source_as_of_dates=source_as_of_dates,
        source_qualities=source_qualities,
    ).sort_values("symbol").reset_index(drop=True)
    _assert_matching_matrix(offline, online, contract.feature_names, contract.parity_tolerance, "offline/online")
    _write_progress(progress_path, "build-offline-online-parity", 2, 2)

    _write_progress(progress_path, "scan-stored-features-and-coverage", 0, parquet.metadata.num_row_groups)
    stored_frames: list[pd.DataFrame] = []
    stored_columns = ["trade_date", "symbol", *contract.feature_names]
    coverage_columns = ["trade_date", *contract.required_feature_names]
    read_columns = list(dict.fromkeys([*stored_columns, *coverage_columns]))
    for index, batch in enumerate(parquet.iter_batches(batch_size=65_536, columns=read_columns), start=1):
        frame = batch.to_pandas()
        date_values = frame["trade_date"].astype(str)
        as_of_rows = frame.loc[date_values.eq(as_of_date), stored_columns]
        if not as_of_rows.empty:
            stored_frames.append(as_of_rows)
        for fold_name, dates in fold_dates.items():
            selected = frame.loc[date_values.isin(dates), coverage_columns]
            if selected.empty:
                continue
            for feature in contract.required_feature_names:
                values = pd.to_numeric(selected[feature], errors="coerce").to_numpy(dtype=float, copy=False)
                counts[fold_name][feature][0] += int(np.isfinite(values).sum())
                counts[fold_name][feature][1] += int(len(values))
        if index % 8 == 0:
            _write_progress(progress_path, "scan-stored-features-and-coverage", index, parquet.metadata.num_row_groups)
    stored = pd.concat(stored_frames, ignore_index=True).sort_values("symbol").reset_index(drop=True)
    _assert_matching_matrix(offline, stored, contract.feature_names, contract.parity_tolerance, "offline/stored")
    coverage = {
        fold: {feature: finite / total if total else 0.0 for feature, (finite, total) in features.items()}
        for fold, features in counts.items()
    }
    coverage_minimum = {fold: min(features.values()) for fold, features in coverage.items()}
    failures = [
        f"{fold}:{feature}={coverage_value:.4f}"
        for fold, features in coverage.items()
        for feature, coverage_value in features.items()
        if coverage_value < contract.minimum_fold_coverage
    ]
    if failures:
        raise ValueError(
            "registered core coverage is below "
            f"{contract.minimum_fold_coverage:.2%}: " + ", ".join(failures)
        )
    _write_progress(progress_path, "complete", parquet.metadata.num_row_groups, parquet.metadata.num_row_groups)
    return {
        "status": "complete",
        "verified_at": _now(),
        "code_commit": code_commit,
        "dataset_id": registry["dataset_id"],
        "dataset_sha256": registry["source_hashes"]["dataset"],
        "feature_contract_version": contract.version,
        "feature_contract_sha256": contract.sha256(),
        "feature_count": len(contract.feature_names),
        "required_feature_count": len(contract.required_feature_names),
        "disabled_groups": list(contract.disabled_groups),
        "as_of_date": as_of_date,
        "history_session_count": history_sessions,
        "history_row_count": int(len(raw_history)),
        "as_of_symbol_count": int(len(offline)),
        "core_coverage_minimum_by_outer_test_fold": coverage_minimum,
        "core_coverage_passed": True,
        "moneyflow_coverage": float(quality["moneyflow_coverage"]),
        "formal_future_holdout_status": registry["formal_future_holdout_status"],
        "production_integration_allowed": False,
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
    }


def _assert_matching_matrix(
    left: pd.DataFrame,
    right: pd.DataFrame,
    feature_names: tuple[str, ...],
    tolerance: float,
    label: str,
) -> None:
    if left[["trade_date", "symbol"]].to_dict("records") != right[["trade_date", "symbol"]].to_dict("records"):
        raise ValueError(f"{label} identity rows differ")
    np.testing.assert_allclose(
        left[list(feature_names)].to_numpy(dtype=float),
        right[list(feature_names)].to_numpy(dtype=float),
        rtol=0.0,
        atol=tolerance,
        equal_nan=True,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--history-sessions", type=int, default=84)
    parser.add_argument("--code-commit", required=True)
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_progress(path: Path, stage: str, completed: int, total: int) -> None:
    _write_json(
        path,
        {
            "status": "running" if stage != "complete" else "complete",
            "stage": stage,
            "completed_batches": completed,
            "total_row_groups": total,
            "updated_at": _now(),
        },
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
