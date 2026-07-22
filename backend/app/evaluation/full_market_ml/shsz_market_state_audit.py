"""Point-in-time SH/SZ market-state construction for development-only research."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from .market_regime import build_market_regime_table
from .evaluator import evaluate_ranking, simulate_daily_topk_portfolio
from .splits import SplitPlan


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
