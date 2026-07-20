"""File-backed execution for exploratory context scorecard ablation."""
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

from .context_feature_audit import CONTEXT_SOURCE_COLUMNS
from .context_scorecard_ablation import (
    CONTEXT_ABLATION_FEATURES,
    ContextScorecardAblationError,
    run_context_scorecard_ablation_rows,
)
from .market_industry_features import build_industry_state_features, build_market_state_features
from .train_only_scorecard_oof import _ALL_FEATURES, _REQUIRED_COLUMNS
from .v3_feature_evidence import _development_only_split, _load_eligible_feature_asset, _read_json


def run_context_scorecard_ablation(
    *,
    source_dataset_root: str | Path,
    feature_asset_root: str | Path,
    output_root: str | Path,
    code_commit: str,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    """Run one post-selection, development-only context ablation.

    Same-day market and industry aggregates deliberately use every available
    full-market row for each registered development date.  Label-bearing rows
    are loaded only after those aggregates exist, then merged by stable keys.
    """
    source_root = Path(source_dataset_root).expanduser().resolve()
    asset_root = Path(feature_asset_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    _prepare_output(destination)
    try:
        _write_json(destination / "progress.json", _progress("running", "validate-research-assets"))
        manifest = _load_eligible_feature_asset(asset_root, source_root)
        split_payload = _read_json(source_root / "artifacts" / "full-build" / "split_plan_v2.json")
        split_plan = _development_only_split(split_payload)
        matrix_root = Path(str(manifest["matrix_path"])).expanduser().resolve()

        _write_json(
            destination / "progress.json",
            _progress("running", "load-full-market-context-source", total_dates=len(split_plan.development_dates)),
        )
        context_source = _load_partition_rows(
            matrix_root,
            split_plan.development_dates,
            CONTEXT_SOURCE_COLUMNS,
            destination,
            stage="load-full-market-context-source",
        )
        _write_json(
            destination / "progress.json",
            _progress("running", "build-full-market-context", context_source_row_count=len(context_source)),
        )
        context = _build_context(context_source)

        _write_json(
            destination / "progress.json",
            _progress("running", "load-scorecard-input", total_dates=len(split_plan.development_dates)),
        )
        scorecard_rows = _load_partition_rows(
            matrix_root,
            split_plan.development_dates,
            (*_REQUIRED_COLUMNS, *_ALL_FEATURES),
            destination,
            stage="load-scorecard-input",
        )
        rows = scorecard_rows.merge(context, on=["trade_date", "symbol"], how="left", validate="one_to_one")
        missing_context = [name for name in CONTEXT_ABLATION_FEATURES if name not in rows]
        if missing_context:
            raise ContextScorecardAblationError("built context misses registered features: " + ", ".join(missing_context))
        _write_json(
            destination / "progress.json",
            _progress(
                "running",
                "run-folds",
                context_source_row_count=len(context_source),
                scorecard_input_row_count=len(scorecard_rows),
                total_folds=len(split_plan.walk_forward),
            ),
        )
        result = run_context_scorecard_ablation_rows(
            rows,
            split_plan,
            bootstrap_iterations=max(1, int(bootstrap_iterations)),
            on_progress=lambda payload: _write_json(
                destination / "progress.json",
                _progress(
                    "running",
                    "run-folds",
                    context_source_row_count=len(context_source),
                    scorecard_input_row_count=len(scorecard_rows),
                    total_folds=len(split_plan.walk_forward),
                    **payload,
                ),
            ),
        )
        result["input_summary"].update(
            {
                "context_source_row_count": int(len(context_source)),
                "scorecard_input_row_count": int(len(scorecard_rows)),
                "context_row_count": int(len(context)),
                "context_construction_population": "full_market_registered_development_partitions_before_label_eligibility_filter",
            }
        )
        _write_outputs(destination, context, result)
        report = _report(manifest, split_payload, result, code_commit=code_commit)
        _write_json(destination / "report.json", report)
        _write_json(
            destination / "progress.json",
            _progress(
                "complete",
                "complete",
                context_source_row_count=len(context_source),
                scorecard_input_row_count=len(scorecard_rows),
                row_count=result["input_summary"]["row_count"],
                total_folds=len(split_plan.walk_forward),
            ),
        )
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


def _build_context(context_source: pd.DataFrame) -> pd.DataFrame:
    context = build_market_state_features(context_source)
    context = build_industry_state_features(context)
    selected = context.loc[:, ["trade_date", "symbol", *CONTEXT_ABLATION_FEATURES]].copy()
    if selected.duplicated(["trade_date", "symbol"]).any():
        raise ContextScorecardAblationError("full-market context contains duplicate trade_date and symbol keys")
    return selected.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _load_partition_rows(
    matrix_root: Path,
    development_dates: tuple[str, ...],
    requested_columns: tuple[str, ...],
    destination: Path,
    *,
    stage: str,
) -> pd.DataFrame:
    columns = tuple(dict.fromkeys(str(column) for column in requested_columns))
    frames: list[pd.DataFrame] = []
    for position, trade_date in enumerate(development_dates, start=1):
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise ContextScorecardAblationError(f"feature matrix misses registered development date: {trade_date}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise ContextScorecardAblationError(
                f"feature matrix {trade_date} misses {stage} columns: " + ", ".join(missing)
            )
        frames.append(pq.read_table(path, columns=list(columns)).to_pandas())
        _write_json(
            destination / "progress.json",
            _progress("running", stage, completed_dates=position, total_dates=len(development_dates), trade_date=trade_date),
        )
    if not frames:
        raise ContextScorecardAblationError(f"{stage} has no registered development partitions")
    return pd.concat(frames, ignore_index=True)


def _write_outputs(destination: Path, context: pd.DataFrame, result: Mapping[str, Any]) -> None:
    context.to_parquet(destination / "context_features.parquet", compression="zstd", index=False)
    result["predictions"].to_parquet(destination / "oof_predictions.parquet", compression="zstd", index=False)
    _write_json(destination / "fold_directions.json", {"folds": result["fold_directions"]})
    _write_json(destination / "inactive_folds.json", {"folds": result["inactive_folds"]})
    _write_json(destination / "metrics.json", result["fold_metrics"])
    _write_json(destination / "bootstrap.json", result["fold_bootstrap"])
    _write_json(destination / "portfolio_metrics.json", result["fold_portfolios"])
    _write_json(destination / "candidate_screen.json", result["candidate_screen"])
    _write_json(destination / "input_summary.json", result["input_summary"])
    _write_json(
        destination / "research_contract.json",
        {
            "status": "exploratory_post_selection_only",
            "production_integration_allowed": False,
            "final_holdout_used": False,
            "baseline_scorecard": "scorecard_baseline_h1_h2_h3",
            "candidate_context_features": list(CONTEXT_ABLATION_FEATURES),
            "direction_learning": "fit_dates_and_A_training_symbols_only_per_outer_fold",
            "context_construction": "full_market_same_day_before_label_eligibility_filter",
        },
    )


def _report(
    manifest: Mapping[str, Any],
    split_payload: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    code_commit: str,
) -> dict[str, Any]:
    return {
        "status": "complete",
        "model_status": "research_only_exploratory",
        "research_only": True,
        "post_selection_exploratory": True,
        "model_selection_allowed": False,
        "production_integration_allowed": False,
        "final_holdout_used": False,
        "code_commit": str(code_commit),
        "source_dataset_id": str(manifest.get("source_dataset_id", "")),
        "source_dataset_sha256": str(manifest.get("source_dataset_sha256", "")),
        "feature_asset_manifest_sha256": str(manifest.get("sha256", "")),
        "feature_contract_sha256": str(manifest.get("feature_contract_sha256", "")),
        "split_sha256": str(split_payload.get("sha256", "")),
        "input_summary": result["input_summary"],
        "candidate_screen": result["candidate_screen"],
        "limitations": [
            "The context features were selected by a prior development-period audit; this comparison is post-selection exploratory research.",
            "Each context direction is fit only from the current outer fold's A-quadrant training dates and symbols.",
            "Outer validation windows overlap, so every metric, bootstrap interval, and portfolio result is fold-local and is never pooled.",
            "This source asset has no new untouched future time holdout; no result can freeze a model or authorize strategy integration.",
        ],
        "generated_at": _now(),
    }


def _prepare_output(destination: Path) -> None:
    if destination.exists():
        if any(destination.iterdir()):
            raise ContextScorecardAblationError(f"context ablation output root must be empty: {destination}")
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
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
