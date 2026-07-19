"""Pre-registered, development-only OOF evidence for a simple scorecard."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .evaluator import (
    bootstrap_uplift,
    evaluate_ranking,
    simulate_daily_topk_portfolio,
    validate_identical_comparison_rows,
)
from .splits import FinalHoldoutAccessError, SplitPlan
from .train_only_scorecard import PRE_REGISTERED_DIRECTION_TARGETS, fit_scorecard_directions, score_with_directions
from .v3_feature_evidence import _development_only_split, _load_eligible_feature_asset, _read_json


PRE_REGISTERED_FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "h1_momentum_trend": (
        "adjusted_return_5d",
        "adjusted_return_20d",
        "adjusted_return_60d",
        "price_to_sma_20d",
        "price_to_sma_60d",
    ),
    "h2_liquidity_turnover": (
        "amount_log",
        "amount_ratio_20d",
        "volume_cv_20d",
        "turnover_rate",
        "turnover_ratio_20d",
    ),
    "h3_industry_relative": (
        "industry_return_5d_rank",
        "industry_return_20d_rank",
    ),
}
PRE_REGISTERED_COMPARATORS = (
    "baseline_momentum_60d",
    "baseline_inverse_60d_diagnostic",
    "scorecard_h1_momentum_trend",
    "scorecard_h2_liquidity_turnover",
    "scorecard_h3_industry_relative",
    "scorecard_combined_h1_h2_h3",
)
_ALL_FEATURES = tuple(dict.fromkeys(feature for group in PRE_REGISTERED_FEATURE_GROUPS.values() for feature in group))
_REQUIRED_COLUMNS = (
    "trade_date",
    "symbol",
    "eligible_for_training_10d",
    "entry_tradeable_10d",
    "horizon_available_10d",
    "path_ambiguous_10d",
    "future_return_10d",
    "net_return_after_cost_10d",
    "relevance_grade_10d",
    "label_strong_path_10d",
    "label_severe_negative_10d",
    "entry_price_10d",
    "exit_price_10d",
    "exit_trade_date_10d",
    "market_median_net_return_10d",
    "industry_median_net_return_10d",
)


class ScorecardOofError(ValueError):
    """Raised when the scorecard experiment cannot preserve its research contract."""


def run_train_only_scorecard_oof(
    *,
    source_dataset_root: str | Path,
    feature_asset_root: str | Path,
    output_root: str | Path,
    code_commit: str,
    bootstrap_iterations: int = 1000,
    direction_target_column: str = "net_return_after_cost_10d",
) -> dict[str, Any]:
    """Run fixed, fold-local A/C OOF diagnostics without touching final dates."""
    source_root = Path(source_dataset_root).expanduser().resolve()
    asset_root = Path(feature_asset_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    manifest = _load_eligible_feature_asset(asset_root, source_root)
    split_payload = _read_json(source_root / "artifacts" / "full-build" / "split_plan_v2.json")
    split_plan = _development_only_split(split_payload)
    matrix_root = Path(str(manifest["matrix_path"])).expanduser().resolve()

    _prepare_output(destination)
    _write_json(destination / "progress.json", _progress("running", "load-development-rows"))
    try:
        rows = _load_development_rows(matrix_root, split_plan, direction_target_column=direction_target_column)
        _write_json(
            destination / "progress.json",
            _progress("running", "run-folds", row_count=len(rows), total_folds=len(split_plan.walk_forward)),
        )
        result = run_train_only_scorecard_oof_rows(
            rows,
            split_plan,
            bootstrap_iterations=bootstrap_iterations,
            direction_target_column=direction_target_column,
            on_progress=lambda payload: _write_json(
                destination / "progress.json",
                _progress("running", "run-folds", row_count=len(rows), total_folds=len(split_plan.walk_forward), **payload),
            ),
        )
        _write_outputs(destination, result)
        report = _report(
            manifest,
            split_payload,
            result,
            code_commit=code_commit,
            direction_target_column=direction_target_column,
        )
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


def run_train_only_scorecard_oof_rows(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    *,
    bootstrap_iterations: int = 1000,
    direction_target_column: str = "net_return_after_cost_10d",
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """Run exactly the registered five expanding folds on development rows.

    Outer validation windows are registered as overlapping.  Consequently this
    function evaluates and bootstraps every fold separately and never pools
    duplicate dates into a single headline metric.
    """
    direction_target_column = _validate_direction_target(direction_target_column)
    data = _normalize_rows(rows, split_plan, direction_target_column=direction_target_column)
    all_symbols = set(split_plan.A_dev_train_symbols) | set(split_plan.C_dev_unseen_symbols)
    data = data.loc[data["symbol"].isin(all_symbols) & data["eligible_for_training_10d"].eq(True)].copy()
    data = data.loc[pd.to_numeric(data["adjusted_return_60d"], errors="coerce").notna()].copy()
    if data.empty:
        raise ScorecardOofError("scorecard experiment has no label-eligible baseline rows")
    data["risk_eligible"] = True

    predictions: list[pd.DataFrame] = []
    directions: list[dict[str, Any]] = []
    fold_metrics: dict[str, dict[str, Any]] = {}
    fold_bootstrap: dict[str, dict[str, Any]] = {}
    fold_portfolios: dict[str, dict[str, Any]] = {}
    for fold in split_plan.walk_forward:
        fit = data.loc[
            data["trade_date"].isin(fold.training_dates) & data["symbol"].isin(fold.training_symbols)
        ].copy()
        validation = data.loc[data["trade_date"].isin(fold.validation_dates)].copy()
        if fit.empty or validation.empty:
            raise ScorecardOofError(f"fold {fold.fold} has no fit or validation rows after fixed eligibility")
        fitted = fit_scorecard_directions(
            fit,
            feature_schema=_ALL_FEATURES,
            target_column=direction_target_column,
        )
        trial = validation.copy()
        trial["fold"] = int(fold.fold)
        trial["score__baseline_momentum_60d"] = pd.to_numeric(trial["adjusted_return_60d"], errors="coerce")
        trial["score__baseline_inverse_60d_diagnostic"] = -trial["score__baseline_momentum_60d"]
        active_comparators = {"baseline_momentum_60d", "baseline_inverse_60d_diagnostic"}
        for group, features in PRE_REGISTERED_FEATURE_GROUPS.items():
            group_directions = {feature: fitted["directions"][feature] for feature in features if feature in fitted["directions"]}
            score_name = f"scorecard_{group}"
            trial[f"score__{score_name}"] = np.nan
            if group_directions:
                trial[f"score__{score_name}"] = score_with_directions(trial, directions=group_directions)["score"]
                active_comparators.add(score_name)
        trial["score__scorecard_combined_h1_h2_h3"] = np.nan
        if fitted["directions"]:
            trial["score__scorecard_combined_h1_h2_h3"] = score_with_directions(
                trial, directions=fitted["directions"]
            )["score"]
            active_comparators.add("scorecard_combined_h1_h2_h3")
        _validate_comparator_rows(trial, active_comparators)
        predictions.append(trial)
        directions.append(
            {
                "fold": int(fold.fold),
                "fit_start": fold.train_start,
                "fit_end": fold.train_end,
                "validation_start": fold.validation_start,
                "validation_end": fold.validation_end,
                "direction_target_column": direction_target_column,
                "directions": fitted["directions"],
                "direction_evidence": fitted["direction_evidence"],
                "active_comparators": sorted(active_comparators),
                "inactive_comparators": sorted(set(PRE_REGISTERED_COMPARATORS) - active_comparators),
            }
        )
        for quadrant, symbols in (("A_development_seen", set(fold.training_symbols)), ("C_development_unseen", set(split_plan.C_dev_unseen_symbols))):
            subset = trial.loc[trial["symbol"].isin(symbols)].copy()
            if subset.empty:
                continue
            fold_key = f"fold_{fold.fold}_{quadrant}"
            fold_metrics[fold_key] = _evaluate_comparators(subset, active_comparators)
            fold_bootstrap[fold_key] = _bootstrap_comparators(subset, active_comparators, iterations=bootstrap_iterations)
            fold_portfolios[fold_key] = _portfolio_comparators(subset, active_comparators)
        if on_progress is not None:
            on_progress({"completed_folds": int(fold.fold), "current_fold": int(fold.fold), "last_heartbeat": _now()})

    output = pd.concat(predictions, ignore_index=True).sort_values(["fold", "trade_date", "symbol"], kind="stable").reset_index(drop=True)
    return {
        "predictions": output,
        "fold_directions": directions,
        "fold_metrics": fold_metrics,
        "fold_bootstrap": fold_bootstrap,
        "fold_portfolios": fold_portfolios,
        "candidate_screen": _candidate_screen(fold_metrics, fold_bootstrap, fold_portfolios),
        "input_summary": {
            "row_count": int(len(data)),
            "date_count": int(data["trade_date"].nunique()),
            "symbol_count": int(data["symbol"].nunique()),
            "direction_target_column": direction_target_column,
            "outer_test_aggregation_policy": "fold_local_metrics_only",
            "outer_test_windows_overlap": True,
        },
    }


def _normalize_rows(rows: pd.DataFrame, split_plan: SplitPlan, *, direction_target_column: str) -> pd.DataFrame:
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    required = set(_REQUIRED_COLUMNS) | set(_ALL_FEATURES) | {direction_target_column}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ScorecardOofError("scorecard rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if result["trade_date"].isna().any() or result["trade_date"].isin(split_plan.final_dates).any():
        raise FinalHoldoutAccessError("scorecard OOF cannot read final holdout dates")
    if (~result["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("scorecard OOF cannot read dates outside the development plan")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise ScorecardOofError("scorecard rows contain duplicate trade_date and symbol keys")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _load_development_rows(
    matrix_root: Path,
    split_plan: SplitPlan,
    *,
    direction_target_column: str,
) -> pd.DataFrame:
    direction_target_column = _validate_direction_target(direction_target_column)
    columns = [*_REQUIRED_COLUMNS, *_ALL_FEATURES, direction_target_column]
    frames = []
    for trade_date in split_plan.development_dates:
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise ScorecardOofError(f"feature matrix misses registered development date: {trade_date}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise ScorecardOofError(f"feature matrix {trade_date} misses scorecard columns: " + ", ".join(missing))
        frames.append(pq.read_table(path, columns=columns).to_pandas())
    return pd.concat(frames, ignore_index=True)


def _validate_comparator_rows(rows: pd.DataFrame, comparators: set[str]) -> None:
    if "baseline_momentum_60d" not in comparators:
        raise ScorecardOofError("primary momentum baseline must remain active")
    comparators = {
        name: rows.assign(score=pd.to_numeric(rows[f"score__{name}"], errors="coerce"))
        for name in sorted(comparators)
    }
    if any(frame["score"].isna().any() for frame in comparators.values()):
        raise ScorecardOofError("registered comparators have unequal score availability")
    validate_identical_comparison_rows(comparators)


def _evaluate_comparators(rows: pd.DataFrame, comparators: set[str]) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_ranking(rows.assign(score=rows[f"score__{name}"]))
        for name in sorted(comparators)
    }


def _bootstrap_comparators(rows: pd.DataFrame, comparators: set[str], *, iterations: int) -> dict[str, dict[str, Any]]:
    baseline = "score__baseline_momentum_60d"
    return {
        name: {
            "status": "diagnostic_only" if name == "baseline_inverse_60d_diagnostic" else "candidate_comparator",
            **bootstrap_uplift(
                rows.assign(score=rows[f"score__{name}"], baseline_score=rows[baseline]),
                baseline_score_col="baseline_score",
                iterations=iterations,
                seed=1000 + index,
            ),
        }
        for index, name in enumerate(sorted(comparators))
        if name != "baseline_momentum_60d"
    }


def _portfolio_comparators(rows: pd.DataFrame, comparators: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in sorted(comparators):
        try:
            result[name] = {
                "status": "diagnostic_only" if name == "baseline_inverse_60d_diagnostic" else "candidate_comparator",
                **simulate_daily_topk_portfolio(rows.assign(score=rows[f"score__{name}"])),
            }
        except ValueError as error:
            result[name] = {"status": "unavailable", "reason": str(error)}
    return result


def _candidate_screen(
    fold_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    fold_bootstrap: Mapping[str, Mapping[str, Mapping[str, Any]]],
    fold_portfolios: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    candidate_names = [name for name in PRE_REGISTERED_COMPARATORS if name not in {"baseline_momentum_60d", "baseline_inverse_60d_diagnostic"}]
    for name in candidate_names:
        a_keys = sorted(key for key in fold_metrics if key.endswith("_A_development_seen"))
        c_keys = sorted(key for key in fold_metrics if key.endswith("_C_development_unseen"))
        a_available = [key for key in a_keys if name in fold_metrics[key]]
        c_available = [key for key in c_keys if name in fold_metrics[key]]
        if len(a_available) < 5:
            result[name] = {
                "status": "inactive_no_train_only_direction",
                "a_fold_count": len(a_keys),
                "a_active_fold_count": len(a_available),
                "c_fold_count": len(c_keys),
                "c_active_fold_count": len(c_available),
                "production_integration_allowed": False,
                "reason": "The registered feature group had no stable, fit-period direction in every outer fold.",
            }
            continue
        a_non_decreasing = [
            key
            for key in a_available
            if fold_metrics[key][name]["ndcg_at_10"] >= fold_metrics[key]["baseline_momentum_60d"]["ndcg_at_10"]
            and fold_metrics[key][name]["precision_at_5"] >= fold_metrics[key]["baseline_momentum_60d"]["precision_at_5"]
            and fold_metrics[key][name]["top_5_mean_return"] >= fold_metrics[key]["baseline_momentum_60d"]["top_5_mean_return"]
            and _portfolio_not_worse(fold_portfolios[key][name], fold_portfolios[key]["baseline_momentum_60d"])
            and fold_bootstrap[key][name]["precision_at_5_uplift_ci_low"] > 0.0
        ]
        c_non_collapsed = [
            key
            for key in c_available
            if fold_metrics[key][name]["ndcg_at_10"] >= fold_metrics[key]["baseline_momentum_60d"]["ndcg_at_10"] - 0.02
        ]
        passes = len(a_non_decreasing) >= 4 and len(c_non_collapsed) >= 4
        result[name] = {
            "status": "development_screen_passed" if passes else "development_screen_failed",
            "a_fold_count": len(a_available),
            "a_folds_passing_all_registered_checks": len(a_non_decreasing),
            "c_fold_count": len(c_available),
            "c_folds_without_ndcg_collapse": len(c_non_collapsed),
            "production_integration_allowed": False,
            "reason": "No formal future holdout exists; this development-only screen cannot authorize production integration.",
        }
    return result


def _portfolio_not_worse(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    if candidate.get("status") == "unavailable" or baseline.get("status") == "unavailable":
        return False
    return float(candidate.get("maximum_drawdown", 0.0)) >= float(baseline.get("maximum_drawdown", 0.0))


def _write_outputs(destination: Path, result: Mapping[str, Any]) -> None:
    result["predictions"].to_parquet(destination / "oof_predictions.parquet", compression="zstd", index=False)
    _write_json(destination / "fold_directions.json", {"folds": result["fold_directions"]})
    _write_json(destination / "metrics.json", result["fold_metrics"])
    _write_json(destination / "bootstrap.json", result["fold_bootstrap"])
    _write_json(destination / "portfolio_metrics.json", result["fold_portfolios"])
    _write_json(destination / "candidate_screen.json", result["candidate_screen"])
    _write_json(destination / "input_summary.json", result["input_summary"])


def _report(
    manifest: Mapping[str, Any],
    split_payload: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    code_commit: str,
    direction_target_column: str,
) -> dict[str, Any]:
    return {
        "status": "complete",
        "research_only": True,
        "production_integration_allowed": False,
        "code_commit": str(code_commit),
        "source_dataset_id": str(manifest.get("source_dataset_id", "")),
        "source_dataset_sha256": str(manifest.get("source_dataset_sha256", "")),
        "feature_asset_manifest_sha256": str(manifest.get("sha256", "")),
        "feature_contract_sha256": str(manifest.get("feature_contract_sha256", "")),
        "split_sha256": str(split_payload.get("sha256", "")),
        "pre_registered_feature_groups": {name: list(features) for name, features in PRE_REGISTERED_FEATURE_GROUPS.items()},
        "pre_registered_comparators": list(PRE_REGISTERED_COMPARATORS),
        "direction_target_column": _validate_direction_target(direction_target_column),
        "input_summary": result["input_summary"],
        "candidate_screen": result["candidate_screen"],
        "limitations": [
            "All directions are learned only from each fold's fit dates and training symbols.",
            "Outer validation windows overlap, so metrics and bootstrap intervals are reported fold-locally and are not pooled.",
            "The inverse 60-day return comparator is a diagnostic for observed mean reversion, not a production candidate.",
            "No formal future holdout exists for this research dataset; no result from this run authorizes model or strategy integration.",
        ],
        "generated_at": _now(),
    }


def _prepare_output(destination: Path) -> None:
    if destination.exists():
        if any(destination.iterdir()):
            raise ScorecardOofError(f"scorecard output root must be empty: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=False)


def _validate_direction_target(target_column: str) -> str:
    target_column = str(target_column)
    if target_column not in PRE_REGISTERED_DIRECTION_TARGETS:
        raise ScorecardOofError("direction_target_column must be one of: " + ", ".join(PRE_REGISTERED_DIRECTION_TARGETS))
    return target_column


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
