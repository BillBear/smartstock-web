"""Point-in-time SH/SZ market-state construction for development-only research."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .market_regime import build_market_regime_table
from .evaluator import evaluate_ranking, simulate_daily_topk_portfolio
from .splits import SplitPlan
from .shsz_h1_feature_evidence import (
    _load_bound_inputs as _load_r1_r2_bound_inputs,
    _load_labels as _load_r1_labels,
)


MIN_VALID_STOCK_COUNT = 4_500
STATE_PANEL_COLUMNS = (
    "trade_date",
    "symbol",
    "market_index_close",
    "at_up_limit",
    "at_down_limit",
)
STATE_R2_COLUMNS = (
    "trade_date",
    "symbol",
    "valid_ohlc_flag",
    "adjusted_return_1d",
    "price_to_sma_20d",
)
STATE_OUTPUT_COLUMNS = (
    "trade_date",
    "market_index_close",
    "market_return_1d",
    "market_return_5d",
    "market_return_20d",
    "market_volatility_20d",
    "valid_stock_count",
    "market_positive_breadth_1d",
    "market_above_sma20_rate",
    "market_limit_up_rate",
    "market_limit_down_rate",
    "regime_history_complete",
    "market_regime",
)
_BASELINE_LABEL_COLUMNS = (
    "trade_date",
    "symbol",
    "adjusted_return_60d",
    "entry_tradeable",
    "horizon_available_10d",
    "path_ambiguous_10d",
    "alpha_relevance_grade_10d",
    "alpha_top10_10d",
    "future_return_10d",
    "severe_negative_10d",
    "entry_price",
    "exit_price",
    "exit_trade_date",
)
_STATE_PAIR_NAMES = ("trend_up", "trend_down")
_MIN_STATE_VALIDATION_DATES = 20
_RUN_R2_COLUMNS = (*STATE_R2_COLUMNS, "adjusted_return_60d")
_STATE_CONTRACT = {
    "state_version": "shsz_r3_market_state_v1",
    "universe": "shsz_a_share_v1",
    "allowed_exchanges": ["SH", "SZ"],
    "index_source": "certified_panel.market_index_close",
    "limit_source": "certified_panel.at_up_limit/at_down_limit",
    "breadth_source": "r2.valid_ohlc_flag + r2.adjusted_return_1d",
    "state_formula": {
        "trend_up": "market_return_20d > 0 and market_positive_breadth_1d >= 0.50",
        "trend_down": "market_return_20d < 0 and market_positive_breadth_1d <= 0.50",
        "mixed": "all other complete-history dates",
    },
    "minimum_valid_stock_count": MIN_VALID_STOCK_COUNT,
    "history_sessions": 20,
    "labels_allowed_for_state_construction": False,
    "production_integration_allowed": False,
}


class SHSZMarketStateAuditError(ValueError):
    """Raised when a state input cannot support point-in-time SH/SZ research."""


def validate_shsz_state_inputs(
    panel_manifest: Mapping[str, Any],
    r2_manifest: Mapping[str, Any],
    expected_panel_sha256: str,
) -> None:
    """Validate the immutable panel/R2 universe binding before data is read."""
    if not isinstance(panel_manifest, Mapping) or not isinstance(r2_manifest, Mapping):
        raise TypeError("state audit manifests must be mappings")
    panel_sha = str(r2_manifest.get("panel_manifest_sha256", ""))
    if panel_sha != str(expected_panel_sha256):
        raise SHSZMarketStateAuditError("R2 panel manifest SHA256 does not match the frozen state source")
    if str(panel_manifest.get("universe_id", "")) != "shsz_a_share_v1":
        raise SHSZMarketStateAuditError("state panel does not define shsz_a_share_v1")
    exchanges = tuple(str(value).upper() for value in panel_manifest.get("allowed_exchanges", ()))
    if exchanges != ("SH", "SZ"):
        raise SHSZMarketStateAuditError("state panel does not restrict the universe to SH/SZ")
    if str(r2_manifest.get("universe_id", "")) != "shsz_a_share_v1":
        raise SHSZMarketStateAuditError("R2 feature asset does not define shsz_a_share_v1")
    if tuple(str(value).upper() for value in r2_manifest.get("allowed_exchanges", ())) != ("SH", "SZ"):
        raise SHSZMarketStateAuditError("R2 feature asset does not restrict the universe to SH/SZ")


def verify_shsz_panel_manifest_binding(
    panel_root: str | Path,
    *,
    expected_panel_manifest_sha256: str,
) -> dict[str, Any]:
    """Validate the supplied panel root against the immutable R1/R2 hash."""
    root = Path(panel_root).expanduser().resolve()
    path = root / "panel_rebuild_manifest.json"
    if not path.is_file():
        raise SHSZMarketStateAuditError(f"certified panel manifest is missing: {path}")
    actual_sha = _sha256_file(path)
    if actual_sha != str(expected_panel_manifest_sha256):
        raise SHSZMarketStateAuditError("certified panel manifest SHA256 does not match R1/R2 registration")
    manifest = _read_json(path, "certified panel manifest")
    if manifest.get("status") != "complete_shsz_panel_rebuilt" or manifest.get("research_ready") is not True:
        raise SHSZMarketStateAuditError("certified panel is not a complete SH/SZ rebuilt research panel")
    if manifest.get("production_integration_allowed") is True:
        raise SHSZMarketStateAuditError("certified panel must remain research-only for this audit")
    return manifest


def run_shsz_market_state_audit(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    panel_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
    bootstrap_iterations: int = 1_000,
) -> dict[str, Any]:
    """Publish a bound, development-only SH/SZ market-state measurement.

    This runner deliberately evaluates one fixed baseline.  It does not train,
    tune, calibrate, open a future holdout, or change any production behavior.
    """
    labels_root = Path(label_root).expanduser().resolve()
    features_root = Path(feature_asset_root).expanduser().resolve()
    certified_panel_root = Path(panel_root).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"market-state audit output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete market-state audit requires inspection: {temporary}")
    temporary.mkdir()
    try:
        _write_progress(temporary, "data-verify", status="running")
        inputs = _load_bound_r1_r2_inputs(labels_root, features_root)
        panel_manifest = verify_shsz_panel_manifest_binding(
            certified_panel_root,
            expected_panel_manifest_sha256=inputs["expected_panel_manifest_sha256"],
        )
        validate_shsz_state_inputs(
            panel_manifest,
            inputs["feature_manifest"],
            inputs["expected_panel_manifest_sha256"],
        )
        input_manifest = {
            **inputs["input_manifest"],
            "panel_rebuild_manifest_sha256": _sha256_file(certified_panel_root / "panel_rebuild_manifest.json"),
            "resolved_panel_root": str(certified_panel_root),
            "state_contract_sha256": _sha256_payload(_STATE_CONTRACT),
            "code_commit": str(code_commit),
            "production_integration_allowed": False,
        }
        _write_json(temporary / "input_manifest.json", input_manifest)
        _write_json(temporary / "state_contract.json", _STATE_CONTRACT)

        _write_progress(temporary, "load-state-input", status="running")
        r2_rows = _load_r2_state_rows(inputs, on_progress=lambda current, total, date: _write_progress(
            temporary,
            "load-state-input",
            status="running",
            completed_dates=current,
            total_dates=total,
            current_trade_date=date,
        ))
        panel_rows = _load_certified_panel_state_rows(
            certified_panel_root,
            trade_dates=tuple(sorted(r2_rows["trade_date"].unique())),
            on_progress=lambda current, total, shard: _write_progress(
                temporary,
                "load-state-input",
                status="running",
                completed_panel_shards=current,
                total_panel_shards=total,
                current_panel_shard=shard,
            ),
        )

        _write_progress(temporary, "build-states", status="running", r2_row_count=int(len(r2_rows)))
        states = build_shsz_market_state_table(panel_rows, r2_rows.loc[:, STATE_R2_COLUMNS])
        _write_parquet(temporary / "market_states.parquet", states)
        _write_json(
            temporary / "data_quality_report.json",
            _state_data_quality_report(r2_rows, panel_rows, states),
        )

        _write_progress(temporary, "load-labels", status="running")
        labels = _load_registered_labels(inputs, on_progress=lambda current, total: _write_progress(
            temporary,
            "load-labels",
            status="running",
            completed_label_files=current,
            total_label_files=total,
        ))
        baseline_rows = _join_labels_with_baseline(labels, r2_rows, inputs["split_plan"])

        _write_progress(temporary, "evaluate-baseline", status="running", row_count=int(len(baseline_rows)))
        evaluation = evaluate_shsz_baseline_state_heterogeneity(
            baseline_rows,
            states,
            inputs["split_plan"],
            bootstrap_iterations=max(1, int(bootstrap_iterations)),
        )
        _write_parquet(temporary / "daily_baseline_metrics.parquet", evaluation["daily_baseline_metrics"])
        _write_json(temporary / "fold_metrics.json", evaluation["fold_metrics"])
        _write_json(temporary / "bootstrap.json", _bootstrap_by_fold(evaluation["fold_metrics"]))
        _write_json(temporary / "portfolio_metrics.json", _portfolio_by_fold(evaluation["fold_metrics"]))
        _write_json(temporary / "candidate_screen.json", evaluation["candidate_screen"])
        report = {
            "status": "complete",
            "research_only": True,
            "model_trained": False,
            "production_integration_allowed": False,
            "code_commit": str(code_commit),
            "input_manifest": input_manifest,
            "state_contract": _STATE_CONTRACT,
            "state_row_count": int(len(states)),
            "state_counts": {str(key): int(value) for key, value in states["market_regime"].value_counts().sort_index().items()},
            "baseline_row_count": int(len(baseline_rows)),
            "walk_forward_fold_count": len(inputs["split_plan"].walk_forward),
            "candidate_screen": evaluation["candidate_screen"],
            "limitations": [
                "One frozen adjusted_return_60d baseline was measured; no candidate model was trained.",
                "Only development A/C folds were read; the formal future holdout remains sealed.",
                "A supported state difference would still require a separate research plan before model or production changes.",
            ],
        }
        _write_json(temporary / "market_state_audit.json", report)
        _write_progress(temporary, "complete", status="complete", baseline_row_count=int(len(baseline_rows)))
        os.replace(temporary, destination)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            status="failed",
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def build_shsz_market_state_table(panel_rows: pd.DataFrame, r2_rows: pd.DataFrame) -> pd.DataFrame:
    """Build one same-date-only state row for each SH/SZ market session.

    This function does not accept labels or forward outcomes. The state is
    determined solely from historical index closes and same-date full-market
    breadth, then delegated to the frozen ``market_regime`` classifier.
    """
    panel = _normalize_rows(panel_rows, STATE_PANEL_COLUMNS, "certified panel")
    r2 = _normalize_rows(r2_rows, STATE_R2_COLUMNS, "R2 matrix")
    index_rows = _one_index_close_per_date(panel)
    limit_rows = _panel_limit_rows(panel)
    market_rows = _full_market_state_rows(r2)
    source = market_rows.merge(limit_rows, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    if source[["at_up_limit", "at_down_limit"]].isna().any(axis=None):
        raise SHSZMarketStateAuditError("certified panel does not cover every R2 state key with limit flags")
    source = source.merge(index_rows, on="trade_date", how="inner", validate="many_to_one")
    if source.empty:
        raise SHSZMarketStateAuditError("state inputs have no overlapping trade dates")
    result = build_market_regime_table(source.rename(columns={"valid_ohlc_flag": "valid_ohlc"}))
    _validate_state_table(result)
    return result.loc[:, STATE_OUTPUT_COLUMNS].sort_values("trade_date", kind="stable").reset_index(drop=True)


def bootstrap_state_metric_delta(
    trend_up_daily: list[float] | np.ndarray,
    trend_down_daily: list[float] | np.ndarray,
    *,
    seed: int,
    iterations: int,
    block_length: int = 10,
) -> dict[str, float | int | str]:
    """Bootstrap a state difference from precomputed daily NDCG scalars only."""
    up = _finite_metric_values(trend_up_daily, "trend_up")
    down = _finite_metric_values(trend_down_daily, "trend_down")
    if not len(up) or not len(down):
        raise SHSZMarketStateAuditError("state bootstrap requires non-empty daily metric series")
    count = max(1, int(iterations))
    block = max(1, int(block_length))
    rng = np.random.default_rng(int(seed))
    draws = np.empty(count, dtype="float64")
    for index in range(count):
        draws[index] = float(_sample_circular_blocks(up, rng, block).mean() - _sample_circular_blocks(down, rng, block).mean())
    low, high = np.quantile(draws, [0.025, 0.975])
    return {
        "resample_unit": "trade_date",
        "bootstrap_method": "independent_circular_block",
        "block_length": block,
        "iterations": count,
        "trend_up_date_count": int(len(up)),
        "trend_down_date_count": int(len(down)),
        "ndcg_delta": float(up.mean() - down.mean()),
        "ndcg_delta_ci_low": float(low),
        "ndcg_delta_ci_high": float(high),
    }


def evaluate_shsz_baseline_state_heterogeneity(
    rows: pd.DataFrame,
    states: pd.DataFrame,
    split_plan: SplitPlan,
    *,
    bootstrap_iterations: int,
) -> dict[str, Any]:
    """Evaluate a frozen 60-session baseline by precomputed market state.

    The state table must have been constructed before this function receives
    label-bearing rows. This function never fits a model or mutates a state.
    """
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("state heterogeneity requires a SplitPlan")
    labels = _normalize_baseline_label_rows(rows)
    state_rows = _normalize_state_rows(states)
    joined = labels.merge(
        state_rows,
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    if joined["market_regime"].isna().any() or joined["regime_history_complete"].isna().any():
        raise SHSZMarketStateAuditError("baseline labels are missing a frozen market state")
    if (~joined["trade_date"].isin(split_plan.development_dates)).any():
        raise SHSZMarketStateAuditError("baseline state audit reads a date outside the development split")
    joined["baseline_score"] = pd.to_numeric(joined["adjusted_return_60d"], errors="coerce")
    joined["risk_eligible"] = (
        joined["entry_tradeable"].eq(True)
        & joined["horizon_available_10d"].eq(True)
        & joined["path_ambiguous_10d"].eq(False)
        & joined["baseline_score"].notna()
        & joined["regime_history_complete"].eq(True)
    )
    fold_metrics: dict[str, Any] = {}
    daily_frames: list[pd.DataFrame] = []
    for fold in split_plan.walk_forward:
        for quadrant, symbols in _quadrants(split_plan):
            current = joined.loc[
                joined["trade_date"].isin(fold.validation_dates)
                & joined["symbol"].isin(symbols)
                & joined["risk_eligible"].eq(True)
            ].copy()
            if current.empty:
                raise SHSZMarketStateAuditError(f"baseline audit has no eligible rows for fold {fold.fold} {quadrant}")
            metrics, daily = _evaluate_state_pair(
                current,
                fold=int(fold.fold),
                quadrant=quadrant,
                bootstrap_iterations=max(1, int(bootstrap_iterations)),
            )
            fold_metrics[f"fold_{fold.fold}_{quadrant}"] = metrics
            daily_frames.append(daily)
    daily_metrics = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    return {
        "fold_metrics": fold_metrics,
        "daily_baseline_metrics": daily_metrics,
        "candidate_screen": decide_market_state_explanation_gate(fold_metrics),
    }


def decide_market_state_explanation_gate(fold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the frozen four-fold A/C state-heterogeneity gate."""
    groups = {"A_development_seen": [], "C_development_unseen": []}
    for value in fold_metrics.values():
        if not isinstance(value, Mapping):
            continue
        quadrant = str(value.get("quadrant", ""))
        if quadrant in groups:
            groups[quadrant].append(value)
    support_counts = {
        quadrant: sum(bool(value.get("supports_claim")) for value in values)
        for quadrant, values in groups.items()
    }
    evaluated_counts = {
        quadrant: sum(str(value.get("status")) == "evaluated" for value in values)
        for quadrant, values in groups.items()
    }
    enough = all(evaluated_counts[quadrant] >= 4 for quadrant in groups)
    passed = enough and all(support_counts[quadrant] >= 4 for quadrant in groups)
    if passed:
        status = "market_state_explanation_supported"
    elif not enough:
        status = "insufficient_state_support"
    else:
        status = "market_state_explanation_rejected"
    return {
        "status": status,
        "passed": passed,
        "production_integration_allowed": False,
        "required_supporting_fold_count": 4,
        "supporting_fold_counts": support_counts,
        "evaluated_fold_counts": evaluated_counts,
    }


def _normalize_rows(rows: pd.DataFrame, required: tuple[str, ...], source_name: str) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError(f"{source_name} rows must be a pandas DataFrame")
    missing = sorted(set(required) - set(rows.columns))
    if missing:
        raise SHSZMarketStateAuditError(f"{source_name} misses columns: {', '.join(missing)}")
    _reject_outcome_columns(rows, source_name)
    result = rows.loc[:, required].copy()
    _reject_bj_symbols(result["symbol"], source_name)
    result["trade_date"] = _normalize_trade_dates(result["trade_date"], source_name)
    result["symbol"] = _normalize_symbols(result["symbol"], source_name)
    if source_name == "R2 matrix" and result.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("R2 matrix has duplicate trade_date and symbol keys")
    return result


def _reject_outcome_columns(rows: pd.DataFrame, source_name: str) -> None:
    forbidden_prefixes = ("future_", "label_", "alpha_", "relevance_", "net_return", "entry_price", "exit_price")
    present = sorted(column for column in rows.columns if str(column).startswith(forbidden_prefixes))
    if present:
        raise SHSZMarketStateAuditError(f"{source_name} includes forbidden outcome columns: {', '.join(present)}")


def _reject_bj_symbols(symbols: pd.Series, source_name: str) -> None:
    raw = symbols.astype("string").fillna("").str.strip().str.upper()
    if raw.str.endswith(".BJ").any():
        raise SHSZMarketStateAuditError(f"{source_name} includes BJ symbols before normalization")


def _normalize_trade_dates(values: pd.Series, source_name: str) -> pd.Series:
    normalized = pd.to_datetime(values.astype("string"), errors="coerce").dt.strftime("%Y-%m-%d")
    if normalized.isna().any():
        raise SHSZMarketStateAuditError(f"{source_name} contains invalid trade dates")
    return normalized


def _normalize_symbols(values: pd.Series, source_name: str) -> pd.Series:
    raw = values.astype("string").fillna("").str.strip().str.upper()
    stripped = raw.str.split(".", regex=False).str[0]
    valid = stripped.str.fullmatch(r"\d{6}")
    if (~valid).any():
        raise SHSZMarketStateAuditError(f"{source_name} contains malformed symbols")
    return stripped


def _one_index_close_per_date(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.loc[:, ["trade_date", "market_index_close"]].copy()
    result["market_index_close"] = pd.to_numeric(result["market_index_close"], errors="coerce")
    if (~np.isfinite(result["market_index_close"]) | result["market_index_close"].le(0)).any():
        raise SHSZMarketStateAuditError("certified panel contains invalid market index closes")
    counts = result.groupby("trade_date", sort=True)["market_index_close"].nunique(dropna=True)
    if counts.ne(1).any():
        invalid = str(counts.loc[counts.ne(1)].index[0])
        raise SHSZMarketStateAuditError(f"certified panel has conflicting market index close on {invalid}")
    return result.groupby("trade_date", as_index=False, sort=True)["market_index_close"].first()


def _panel_limit_rows(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.loc[:, ["trade_date", "symbol", "at_up_limit", "at_down_limit"]].copy()
    if result.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("certified panel has duplicate trade_date and symbol keys")
    result["at_up_limit"] = result["at_up_limit"].eq(True)
    result["at_down_limit"] = result["at_down_limit"].eq(True)
    return result


def _full_market_state_rows(r2: pd.DataFrame) -> pd.DataFrame:
    result = r2.copy()
    result["valid_ohlc_flag"] = result["valid_ohlc_flag"].eq(True)
    valid_counts = result.loc[result["valid_ohlc_flag"]].groupby("trade_date", sort=True).size()
    if valid_counts.empty:
        raise SHSZMarketStateAuditError("R2 matrix has no valid OHLC rows")
    low_coverage = valid_counts.loc[valid_counts.lt(MIN_VALID_STOCK_COUNT)]
    if not low_coverage.empty:
        date, count = str(low_coverage.index[0]), int(low_coverage.iloc[0])
        raise SHSZMarketStateAuditError(f"R2 matrix has fewer than 4500 valid SH/SZ rows on {date}: {count}")
    result["adjusted_return_1d"] = pd.to_numeric(result["adjusted_return_1d"], errors="coerce")
    result["price_to_sma_20d"] = pd.to_numeric(result["price_to_sma_20d"], errors="coerce")
    return result.loc[:, [
        "trade_date",
        "symbol",
        "adjusted_return_1d",
        "price_to_sma_20d",
        "valid_ohlc_flag",
    ]]


def _validate_state_table(states: pd.DataFrame) -> None:
    if states.duplicated("trade_date").any():
        raise SHSZMarketStateAuditError("market state table has duplicate trade dates")
    if states["valid_stock_count"].lt(MIN_VALID_STOCK_COUNT).any():
        raise SHSZMarketStateAuditError("market state table contains a date below the minimum SH/SZ coverage")
    if states["market_regime"].isna().any() or states["regime_history_complete"].isna().any():
        raise SHSZMarketStateAuditError("market state table has incomplete regime values")


def _normalize_baseline_label_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("baseline labels must be a pandas DataFrame")
    missing = sorted(set(_BASELINE_LABEL_COLUMNS) - set(rows.columns))
    if missing:
        raise SHSZMarketStateAuditError("baseline labels miss columns: " + ", ".join(missing))
    result = rows.loc[:, _BASELINE_LABEL_COLUMNS].copy()
    _reject_bj_symbols(result["symbol"], "baseline labels")
    result["trade_date"] = _normalize_trade_dates(result["trade_date"], "baseline labels")
    result["symbol"] = _normalize_symbols(result["symbol"], "baseline labels")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("baseline labels have duplicate trade_date and symbol keys")
    return result


def _normalize_state_rows(states: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(states, pd.DataFrame):
        raise TypeError("market states must be a pandas DataFrame")
    required = {"trade_date", "market_regime", "regime_history_complete"}
    missing = sorted(required - set(states.columns))
    if missing:
        raise SHSZMarketStateAuditError("market states miss columns: " + ", ".join(missing))
    result = states.loc[:, ["trade_date", "market_regime", "regime_history_complete"]].copy()
    result["trade_date"] = _normalize_trade_dates(result["trade_date"], "market states")
    if result.duplicated("trade_date").any():
        raise SHSZMarketStateAuditError("market states have duplicate trade dates")
    return result


def _quadrants(split_plan: SplitPlan) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        ("A_development_seen", tuple(split_plan.A_dev_train_symbols)),
        ("C_development_unseen", tuple(split_plan.C_dev_unseen_symbols)),
    )


def _evaluate_state_pair(
    rows: pd.DataFrame,
    *,
    fold: int,
    quadrant: str,
    bootstrap_iterations: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    state_results: dict[str, Any] = {}
    daily_frames: list[pd.DataFrame] = []
    for state in _STATE_PAIR_NAMES:
        current = rows.loc[rows["market_regime"].eq(state)].copy()
        date_count = int(current["trade_date"].nunique())
        if date_count < _MIN_STATE_VALIDATION_DATES:
            state_results[state] = {"status": "insufficient_state_support", "date_count": date_count}
            continue
        ranking = evaluate_ranking(
            current,
            score_col="baseline_score",
            grade_col="alpha_relevance_grade_10d",
            strong_col="alpha_top10_10d",
        )
        portfolio = simulate_daily_topk_portfolio(current, score_col="baseline_score")
        daily = _daily_state_metrics(current, state=state, fold=fold, quadrant=quadrant)
        daily_frames.append(daily)
        state_results[state] = {
            "status": "evaluated",
            "date_count": date_count,
            "ranking": ranking,
            "portfolio": portfolio,
        }
    evaluated = all(state_results.get(state, {}).get("status") == "evaluated" for state in _STATE_PAIR_NAMES)
    bootstrap: dict[str, Any] | None = None
    supports = False
    if evaluated:
        by_state = {frame["market_regime"].iloc[0]: frame for frame in daily_frames}
        bootstrap = bootstrap_state_metric_delta(
            by_state["trend_up"]["ndcg_at_10"].to_numpy(dtype="float64"),
            by_state["trend_down"]["ndcg_at_10"].to_numpy(dtype="float64"),
            seed=20260722 + fold * 100 + (0 if quadrant.startswith("A_") else 1),
            iterations=bootstrap_iterations,
        )
        supports = bool(bootstrap["ndcg_delta"] >= 0.02 and bootstrap["ndcg_delta_ci_low"] > 0.0)
    return (
        {
            "fold": fold,
            "quadrant": quadrant,
            "status": "evaluated" if evaluated else "insufficient_state_support",
            "trend_up": state_results.get("trend_up", {}),
            "trend_down": state_results.get("trend_down", {}),
            "bootstrap": bootstrap,
            "supports_claim": supports,
        },
        pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame(),
    )


def _daily_state_metrics(rows: pd.DataFrame, *, state: str, fold: int, quadrant: str) -> pd.DataFrame:
    metrics = []
    for trade_date, current in rows.groupby("trade_date", sort=True):
        ranking = evaluate_ranking(
            current,
            score_col="baseline_score",
            grade_col="alpha_relevance_grade_10d",
            strong_col="alpha_top10_10d",
        )
        metrics.append(
            {
                "fold": fold,
                "quadrant": quadrant,
                "trade_date": str(trade_date),
                "market_regime": state,
                "precision_at_5": ranking["precision_at_5"],
                "ndcg_at_10": ranking["ndcg_at_10"],
                "top_5_mean_return": ranking["top_5_mean_return"],
                "severe_negative_rate": ranking["severe_negative_rate"],
            }
        )
    return pd.DataFrame(metrics)


def _finite_metric_values(values: list[float] | np.ndarray, state_name: str) -> np.ndarray:
    numeric = np.asarray(values, dtype="float64")
    if numeric.ndim != 1 or not np.isfinite(numeric).all():
        raise SHSZMarketStateAuditError(f"{state_name} daily metrics must be a finite one-dimensional series")
    return numeric


def _sample_circular_blocks(values: np.ndarray, rng: np.random.Generator, block_length: int) -> np.ndarray:
    positions: list[int] = []
    while len(positions) < len(values):
        start = int(rng.integers(0, len(values)))
        positions.extend((start + offset) % len(values) for offset in range(block_length))
    return values[np.asarray(positions[: len(values)], dtype="int64")]


def _load_bound_r1_r2_inputs(labels_root: Path, features_root: Path) -> dict[str, Any]:
    try:
        inputs = _load_r1_r2_bound_inputs(
            labels_root,
            features_root,
            required_feature_names=("adjusted_return_1d", "price_to_sma_20d", "adjusted_return_60d"),
        )
    except Exception as error:
        raise SHSZMarketStateAuditError(f"R1/R2 immutable input binding failed: {error}") from error
    expected_panel_sha = str(inputs["registry"].get("source_panel_manifest_sha256", ""))
    if not expected_panel_sha:
        raise SHSZMarketStateAuditError("R1 registry has no source panel manifest SHA256")
    return {
        **inputs,
        "expected_panel_manifest_sha256": expected_panel_sha,
    }


def _load_r2_state_rows(inputs: Mapping[str, Any], *, on_progress) -> pd.DataFrame:
    entries = inputs["feature_manifest"].get("matrix_files", ())
    if not isinstance(entries, list) or not entries:
        raise SHSZMarketStateAuditError("R2 feature asset has no registered matrix files")
    maximum_date = max(inputs["split_plan"].development_dates)
    selected = sorted(
        (entry for entry in entries if _date_text(entry.get("trade_date"), "R2 matrix manifest") <= maximum_date),
        key=lambda entry: _date_text(entry.get("trade_date"), "R2 matrix manifest"),
    )
    if not selected:
        raise SHSZMarketStateAuditError("R2 feature asset has no state history before the development end date")
    frames = []
    matrix_root = Path(inputs["matrix_root"])
    for index, entry in enumerate(selected, start=1):
        trade_date = _date_text(entry.get("trade_date"), "R2 matrix manifest")
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise SHSZMarketStateAuditError(f"registered R2 matrix file is missing: {path}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(_RUN_R2_COLUMNS) - available)
        if missing:
            raise SHSZMarketStateAuditError(f"R2 matrix {trade_date} misses state fields: " + ", ".join(missing))
        raw = pq.ParquetFile(path).read(columns=list(_RUN_R2_COLUMNS)).to_pandas()
        state = _normalize_rows(raw, STATE_R2_COLUMNS, f"R2 matrix {trade_date}")
        state["adjusted_return_60d"] = pd.to_numeric(raw["adjusted_return_60d"], errors="coerce")
        frames.append(state)
        on_progress(index, len(selected), trade_date)
    result = pd.concat(frames, ignore_index=True)
    if result.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("R2 state history has duplicate trade_date and symbol keys")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _load_certified_panel_state_rows(
    panel_root: Path,
    *,
    trade_dates: tuple[str, ...],
    on_progress,
) -> pd.DataFrame:
    stage = panel_root / "panel" / "stage=full-build"
    paths = sorted(stage.glob("shard=*/data.parquet"))
    if not paths:
        raise SHSZMarketStateAuditError(f"certified panel has no full-build parquet shards: {stage}")
    requested = set(trade_dates)
    frames = []
    for index, path in enumerate(paths, start=1):
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(STATE_PANEL_COLUMNS) - available)
        if missing:
            raise SHSZMarketStateAuditError(f"certified panel shard {path.parent.name} misses state fields: " + ", ".join(missing))
        raw = pq.ParquetFile(path).read(columns=list(STATE_PANEL_COLUMNS)).to_pandas()
        frame = _normalize_rows(raw, STATE_PANEL_COLUMNS, f"certified panel {path.parent.name}")
        frame = frame.loc[frame["trade_date"].isin(requested)].copy()
        if not frame.empty:
            frames.append(frame)
        on_progress(index, len(paths), path.parent.name)
    if not frames:
        raise SHSZMarketStateAuditError("certified panel has no rows for the registered R2 state dates")
    result = pd.concat(frames, ignore_index=True)
    if result.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("certified panel has duplicate trade_date and symbol keys")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _load_registered_labels(inputs: Mapping[str, Any], *, on_progress) -> pd.DataFrame:
    try:
        labels = _load_r1_labels(inputs, on_progress=on_progress)
    except Exception as error:
        raise SHSZMarketStateAuditError(f"registered R1 label load failed: {error}") from error
    missing = sorted(set(_BASELINE_LABEL_COLUMNS) - {"adjusted_return_60d"} - set(labels.columns))
    if missing:
        raise SHSZMarketStateAuditError("R1 labels miss baseline fields: " + ", ".join(missing))
    return labels


def _join_labels_with_baseline(labels: pd.DataFrame, r2_rows: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    baseline = r2_rows.loc[
        r2_rows["trade_date"].isin(split_plan.development_dates),
        ["trade_date", "symbol", "adjusted_return_60d"],
    ].copy()
    if baseline.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("R2 baseline rows have duplicate trade_date and symbol keys")
    merged = labels.merge(baseline, on=["trade_date", "symbol"], how="left", validate="one_to_one", indicator=True)
    missing = merged.loc[merged["_merge"].ne("both"), ["trade_date", "symbol"]]
    if not missing.empty:
        first = missing.iloc[0]
        raise SHSZMarketStateAuditError(f"R2 baseline does not cover registered R1 label key: {first['trade_date']}/{first['symbol']}")
    result = _normalize_baseline_label_rows(merged.drop(columns="_merge"))
    # The shared evaluator recognizes the historical label-prefixed spelling.
    # Preserve the registered source field and expose only an identical alias.
    result["label_severe_negative_10d"] = result["severe_negative_10d"].eq(True)
    if set(result["trade_date"]) != set(split_plan.development_dates):
        raise SHSZMarketStateAuditError("baseline rows do not exactly cover the registered development dates")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _state_data_quality_report(r2_rows: pd.DataFrame, panel_rows: pd.DataFrame, states: pd.DataFrame) -> dict[str, Any]:
    valid = r2_rows.loc[r2_rows["valid_ohlc_flag"].eq(True)]
    coverage = valid.groupby("trade_date", sort=True).size()
    state_counts = states["market_regime"].value_counts().sort_index()
    return {
        "status": "complete",
        "r2_state_row_count": int(len(r2_rows)),
        "panel_state_row_count": int(len(panel_rows)),
        "trade_date_count": int(states["trade_date"].nunique()),
        "minimum_valid_stock_count": int(coverage.min()),
        "maximum_valid_stock_count": int(coverage.max()),
        "low_coverage_trade_dates": states.loc[states["valid_stock_count"].lt(MIN_VALID_STOCK_COUNT), "trade_date"].tolist(),
        "state_counts": {str(key): int(value) for key, value in state_counts.items()},
        "bj_symbol_rejected_before_normalization": True,
        "future_labels_read_for_state_construction": False,
    }


def _bootstrap_by_fold(fold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value.get("bootstrap") for key, value in fold_metrics.items()}


def _portfolio_by_fold(fold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): {
            state: value.get(state, {}).get("portfolio")
            for state in _STATE_PAIR_NAMES
        }
        for key, value in fold_metrics.items()
    }


def _read_json(path: Path, source: str) -> dict[str, Any]:
    if not path.is_file():
        raise SHSZMarketStateAuditError(f"{source} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SHSZMarketStateAuditError(f"{source} is invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise SHSZMarketStateAuditError(f"{source} must be a JSON object: {path}")
    return value


def _date_text(value: object, source: str) -> str:
    result = pd.to_datetime(str(value).replace("-", ""), errors="coerce", format="%Y%m%d")
    if pd.isna(result):
        raise SHSZMarketStateAuditError(f"{source} has an invalid trade_date: {value}")
    return result.strftime("%Y-%m-%d")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def _write_parquet(path: Path, rows: pd.DataFrame) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    pq.write_table(pa.Table.from_pandas(rows, preserve_index=False), temporary, compression="zstd")
    os.replace(temporary, path)


def _write_progress(destination: Path, stage: str, *, status: str, **values: Any) -> None:
    _write_json(
        destination / "progress.json",
        {"status": status, "stage": stage, "updated_at": datetime.now(timezone.utc).isoformat(), **values},
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")
