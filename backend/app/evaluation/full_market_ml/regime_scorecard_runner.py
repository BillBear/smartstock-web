"""File-backed runner for point-in-time market-regime OOF research."""
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

from .market_regime import build_market_regime_table
from .regime_scorecard_oof import run_regime_conditioned_scorecard_oof_rows
from .train_only_scorecard_oof import ScorecardOofError, _ALL_FEATURES, _REQUIRED_COLUMNS
from .v3_feature_evidence import _development_only_split, _load_eligible_feature_asset, _read_json


_MARKET_HISTORY_COLUMNS = (
    "trade_date",
    "market_index_close",
    "adjusted_return_1d",
    "price_to_sma_20d",
    "at_up_limit",
    "at_down_limit",
    "valid_ohlc",
)


def run_regime_conditioned_scorecard_oof(
    *,
    source_dataset_root: str | Path,
    feature_asset_root: str | Path,
    output_root: str | Path,
    code_commit: str,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    """Run registered state-conditioned OOF research on a certified asset.

    The market-state table is built before any label-bearing development rows
    are read, and partition access is capped at the last development date.
    """
    source_root = Path(source_dataset_root).expanduser().resolve()
    asset_root = Path(feature_asset_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    manifest = _load_eligible_feature_asset(asset_root, source_root)
    split_payload = _read_json(source_root / "artifacts" / "full-build" / "split_plan_v2.json")
    split_plan = _development_only_split(split_payload)
    matrix_root = Path(str(manifest["matrix_path"])).expanduser().resolve()
    _prepare_output(destination)
    try:
        development_end = max(split_plan.development_dates)
        _write_json(destination / "progress.json", _progress("running", "load-market-history", development_end=development_end))
        market_rows = _load_market_history_rows(matrix_root, development_end)
        _write_json(destination / "progress.json", _progress("running", "build-market-regimes", market_row_count=len(market_rows)))
        regimes = build_market_regime_table(market_rows)
        regimes = regimes.loc[regimes["trade_date"].isin(split_plan.development_dates)].copy()
        _validate_development_regimes(regimes, split_plan.development_dates)
        regimes.to_parquet(destination / "market_regimes.parquet", compression="zstd", index=False)
        _write_json(destination / "regime_coverage.json", _regime_coverage(regimes))

        _write_json(destination / "progress.json", _progress("running", "load-development-rows", development_date_count=len(split_plan.development_dates)))
        rows = _load_development_rows(matrix_root, split_plan.development_dates)
        rows = rows.merge(
            regimes[["trade_date", "market_regime", "regime_history_complete"]],
            on="trade_date",
            how="left",
            validate="many_to_one",
        )
        if rows["market_regime"].isna().any() or rows["regime_history_complete"].isna().any():
            raise ScorecardOofError("development scorecard rows lack a point-in-time market regime")
        _write_json(destination / "progress.json", _progress("running", "run-folds", row_count=len(rows), total_folds=len(split_plan.walk_forward)))
        result = run_regime_conditioned_scorecard_oof_rows(
            rows,
            split_plan,
            bootstrap_iterations=max(1, int(bootstrap_iterations)),
            on_progress=lambda payload: _write_json(
                destination / "progress.json",
                _progress("running", "run-folds", row_count=len(rows), total_folds=len(split_plan.walk_forward), **payload),
            ),
        )
        _write_outputs(destination, result)
        report = _report(manifest, split_payload, result, code_commit=code_commit)
        _write_json(destination / "report.json", report)
        _write_json(destination / "progress.json", _progress("complete", "complete", row_count=len(rows), total_folds=len(split_plan.walk_forward)))
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


def _load_market_history_rows(matrix_root: Path, development_end: str) -> pd.DataFrame:
    frames = []
    for path in _partition_paths_until(matrix_root, development_end):
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(_MARKET_HISTORY_COLUMNS) - available)
        if missing:
            raise ScorecardOofError(f"feature matrix {path.parent.name} misses market-state columns: " + ", ".join(missing))
        frames.append(pq.read_table(path, columns=list(_MARKET_HISTORY_COLUMNS)).to_pandas())
    if not frames:
        raise ScorecardOofError("feature matrix has no historical partitions before the development cutoff")
    return pd.concat(frames, ignore_index=True)


def _load_development_rows(matrix_root: Path, development_dates: tuple[str, ...]) -> pd.DataFrame:
    columns = [*_REQUIRED_COLUMNS, *_ALL_FEATURES]
    frames = []
    for trade_date in development_dates:
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise ScorecardOofError(f"feature matrix misses registered development date: {trade_date}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise ScorecardOofError(f"feature matrix {trade_date} misses scorecard columns: " + ", ".join(missing))
        frames.append(pq.read_table(path, columns=columns).to_pandas())
    return pd.concat(frames, ignore_index=True)


def _partition_paths_until(matrix_root: Path, development_end: str) -> tuple[Path, ...]:
    if not matrix_root.is_dir():
        raise ScorecardOofError(f"feature matrix root is unavailable: {matrix_root}")
    selected = []
    for directory in sorted(matrix_root.glob("trade_date=*")):
        trade_date = directory.name.split("=", 1)[1]
        if trade_date <= development_end:
            path = directory / "data.parquet"
            if not path.is_file():
                raise ScorecardOofError(f"feature matrix partition has no data.parquet: {directory}")
            selected.append(path)
    return tuple(selected)


def _validate_development_regimes(regimes: pd.DataFrame, development_dates: tuple[str, ...]) -> None:
    present = set(regimes["trade_date"])
    expected = set(development_dates)
    if present != expected:
        missing, unexpected = sorted(expected - present), sorted(present - expected)
        raise ScorecardOofError(
            "market regime coverage does not match development dates: "
            f"missing={missing[:3]}, unexpected={unexpected[:3]}"
        )
    if regimes.duplicated("trade_date").any():
        raise ScorecardOofError("market regime table has duplicate trade dates")


def _regime_coverage(regimes: pd.DataFrame) -> dict[str, Any]:
    counts = regimes["market_regime"].value_counts().to_dict()
    return {
        "date_count": int(len(regimes)),
        "history_complete_date_count": int(regimes["regime_history_complete"].eq(True).sum()),
        "market_regime_date_counts": {str(name): int(count) for name, count in sorted(counts.items())},
        "market_return_20d_summary": _numeric_summary(regimes["market_return_20d"]),
        "market_volatility_20d_summary": _numeric_summary(regimes["market_volatility_20d"]),
    }


def _numeric_summary(values: pd.Series) -> dict[str, float | int]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {"count": 0}
    return {
        "count": int(len(numeric)),
        "minimum": float(numeric.min()),
        "median": float(numeric.median()),
        "maximum": float(numeric.max()),
    }


def _write_outputs(destination: Path, result: Mapping[str, Any]) -> None:
    result["predictions"].to_parquet(destination / "oof_predictions.parquet", compression="zstd", index=False)
    _write_json(destination / "fold_directions.json", {"folds": result["fold_directions"]})
    _write_json(destination / "skipped_regime_folds.json", {"skipped": result["skipped_regime_folds"]})
    _write_json(destination / "metrics.json", result["fold_metrics"])
    _write_json(destination / "bootstrap.json", result["fold_bootstrap"])
    _write_json(destination / "portfolio_metrics.json", result["fold_portfolios"])
    _write_json(destination / "candidate_screen.json", result["candidate_screen"])
    _write_json(destination / "input_summary.json", result["input_summary"])


def _report(manifest: Mapping[str, Any], split_payload: Mapping[str, Any], result: Mapping[str, Any], *, code_commit: str) -> dict[str, Any]:
    screens = [screen for per_regime in result["candidate_screen"].values() for screen in per_regime.values()]
    any_passed = any(screen.get("status") == "development_screen_passed" for screen in screens)
    return {
        "status": "complete",
        "model_status": "research_only_development_candidate" if any_passed else "research_only_failed_gate",
        "research_only": True,
        "production_integration_allowed": False,
        "code_commit": str(code_commit),
        "source_dataset_id": str(manifest.get("source_dataset_id", "")),
        "source_dataset_sha256": str(manifest.get("source_dataset_sha256", "")),
        "feature_asset_manifest_sha256": str(manifest.get("sha256", "")),
        "feature_contract_sha256": str(manifest.get("feature_contract_sha256", "")),
        "split_sha256": str(split_payload.get("sha256", "")),
        "input_summary": result["input_summary"],
        "candidate_screen": result["candidate_screen"],
        "limitations": [
            "Market regimes use only signal-date and historical market data; no labels define the regime threshold.",
            "Directions use only matching fold training dates and matching fold training symbols.",
            "Outer validation windows overlap, so all metrics and bootstrap intervals are fold-local and are not pooled.",
            "This research dataset has no new formal future holdout; no result authorizes model or strategy integration.",
        ],
        "generated_at": _now(),
    }


def _prepare_output(destination: Path) -> None:
    if destination.exists():
        if any(destination.iterdir()):
            raise ScorecardOofError(f"regime scorecard output root must be empty: {destination}")
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
