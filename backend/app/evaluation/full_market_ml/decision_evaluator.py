"""Capital-constrained evaluation for decision-model ranking policies."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


_DATE = "trade_date"
_SYMBOL = "symbol"
_RETURN = "net_return_after_cost_10d"
_ACTIONABLE = "label_actionable_positive_10d"
_SEVERE = "label_severe_negative_10d_v2"
_RELEVANCE = "return_relevance_grade_10d_v2"
_MFE = "mfe_10d"
_MAE = "mae_10d"


@dataclass(frozen=True)
class PolicyEvaluation:
    forced_topk: dict[str, Any]
    selective_topk: dict[str, Any]
    non_overlapping_portfolio: dict[str, Any]
    rolling_portfolio: dict[str, Any]


def evaluate_decision_policy(
    predictions: pd.DataFrame,
    *,
    score_col: str,
    risk_col: str,
    selection_threshold: float | None,
    top_k: int = 5,
    horizon: int = 10,
) -> PolicyEvaluation:
    """Evaluate forced, selective, and fully funded portfolio interpretations.

    ``net_return_after_cost_10d`` is already an execution-costed outcome. This
    evaluator consumes it directly and never charges commission or slippage a
    second time.
    """
    top_k = int(top_k)
    horizon = int(horizon)
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if selection_threshold is not None and not math.isfinite(float(selection_threshold)):
        raise ValueError("selection_threshold must be finite or None")

    data = _validated_predictions(predictions, score_col=score_col, risk_col=risk_col)
    dates = tuple(sorted(data[_DATE].dropna().unique()))
    valid = data.loc[data["_valid_candidate"]].copy()
    forced: dict[str, pd.DataFrame] = {}
    selective: dict[str, pd.DataFrame] = {}
    eligible_by_date: dict[str, pd.DataFrame] = {}
    for trade_date in dates:
        rows = valid.loc[valid[_DATE].eq(trade_date)].sort_values(
            [score_col, _SYMBOL], ascending=[False, True], kind="stable"
        )
        if len(rows) < top_k:
            raise ValueError(f"trade date {trade_date} has fewer than top_k valid candidates")
        eligible_by_date[str(trade_date)] = rows
        forced[str(trade_date)] = rows.head(top_k).copy()
        if selection_threshold is None:
            selected = rows.head(top_k)
        else:
            selected = rows.loc[rows[score_col].ge(float(selection_threshold))].head(top_k)
        selective[str(trade_date)] = selected.copy()

    forced_metrics = _selection_metrics(forced, eligible_by_date, risk_col=risk_col)
    selective_metrics = _selection_metrics(selective, eligible_by_date, risk_col=risk_col)
    portfolio_selection = selective if selection_threshold is not None else forced
    non_overlapping = _simulate_non_overlapping(
        portfolio_selection, horizon=horizon, risk_col=risk_col
    )
    rolling = _simulate_rolling(portfolio_selection, horizon=horizon, risk_col=risk_col)
    return PolicyEvaluation(
        forced_topk=forced_metrics,
        selective_topk=selective_metrics,
        non_overlapping_portfolio=non_overlapping,
        rolling_portfolio=rolling,
    )


def _validated_predictions(
    predictions: pd.DataFrame, *, score_col: str, risk_col: str
) -> pd.DataFrame:
    if not isinstance(predictions, pd.DataFrame):
        raise TypeError("predictions must be a pandas DataFrame")
    required = {
        _DATE,
        _SYMBOL,
        score_col,
        risk_col,
        "eligible_for_training_10d",
        "entry_tradeable_10d",
        _RETURN,
        _ACTIONABLE,
        _SEVERE,
        _RELEVANCE,
        _MFE,
        _MAE,
    }
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError("decision predictions missing columns: " + ", ".join(missing))

    data = predictions.reset_index(drop=True).copy()
    data[_DATE] = pd.to_datetime(data[_DATE], errors="coerce").dt.strftime("%Y-%m-%d")
    data[_SYMBOL] = data[_SYMBOL].astype("string").fillna("")
    duplicate = data[_DATE].notna() & data[_SYMBOL].ne("") & data.duplicated(
        [_DATE, _SYMBOL], keep=False
    )
    if bool(duplicate.any()):
        raise ValueError("decision predictions contain duplicate trade_date and symbol rows")
    for column in (_ACTIONABLE, _SEVERE):
        invalid_boolean = data[column].notna() & ~data[column].isin([True, False])
        if bool(invalid_boolean.any()):
            raise ValueError("decision predictions require boolean decision labels")
    numeric_columns = (score_col, risk_col, _RETURN, _RELEVANCE, _MFE, _MAE)
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    finite = pd.Series(True, index=data.index)
    for column in numeric_columns:
        finite &= np.isfinite(data[column].to_numpy(dtype=float, na_value=np.nan))
    valid = (
        data[_DATE].notna()
        & data[_SYMBOL].ne("")
        & finite
        & data["eligible_for_training_10d"].eq(True).fillna(False)
        & data["entry_tradeable_10d"].eq(True).fillna(False)
        & data[_ACTIONABLE].notna()
        & data[_SEVERE].notna()
        & data[_RETURN].gt(-1.0)
    )
    data["_valid_candidate"] = valid.astype(bool)
    return data


def _selection_metrics(
    selected_by_date: dict[str, pd.DataFrame],
    eligible_by_date: dict[str, pd.DataFrame],
    *,
    risk_col: str,
) -> dict[str, Any]:
    selected = [rows for rows in selected_by_date.values() if not rows.empty]
    combined = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()
    eligible_date_count = len(eligible_by_date)
    selected_date_count = len(selected)
    result = {
        "eligible_date_count": eligible_date_count,
        "selected_date_count": selected_date_count,
        "selected_count": int(len(combined)),
        "coverage": selected_date_count / eligible_date_count if eligible_date_count else 0.0,
    }
    result.update(_outcome_metrics(combined, risk_col=risk_col))
    result["ndcg_at_10"] = _mean_or_zero(
        _date_ndcg(rows, eligible_by_date[date])
        for date, rows in selected_by_date.items()
        if not rows.empty
    )
    return result


def _simulate_non_overlapping(
    selected_by_date: dict[str, pd.DataFrame], *, horizon: int, risk_col: str
) -> dict[str, Any]:
    dates = sorted(selected_by_date)
    chosen = {
        date: selected_by_date[date]
        for index, date in enumerate(dates)
        if index % horizon == 0 and not selected_by_date[date].empty
    }
    cohorts = [_cohort(date, rows) for date, rows in chosen.items()]
    if not cohorts:
        return _empty_portfolio(horizon)

    equity_path = [1.0]
    for cohort in cohorts:
        equity_path.append(equity_path[-1] * (1.0 + cohort["return"]))
    metrics = _portfolio_metrics(
        equity_path,
        periods=max(horizon, horizon * len(cohorts)),
        closed_trade_count=sum(cohort["trade_count"] for cohort in cohorts),
        cohort_count=len(cohorts),
        turnover=2.0 * len(cohorts),
        cash_ratios=[0.0] * len(cohorts),
        gross_exposures=[1.0] * len(cohorts),
        horizon=horizon,
    )
    metrics.update(_outcome_metrics(pd.concat(list(chosen.values()), ignore_index=True), risk_col=risk_col))
    return metrics


def _simulate_rolling(
    selected_by_date: dict[str, pd.DataFrame], *, horizon: int, risk_col: str
) -> dict[str, Any]:
    dates = sorted(selected_by_date)
    if not dates or not any(not rows.empty for rows in selected_by_date.values()):
        return _empty_portfolio(horizon)

    active: list[dict[str, Any]] = []
    cash = 1.0
    equity_path = [1.0]
    cash_ratios = []
    gross_exposures = []
    closed_trade_count = 0
    cohort_count = 0
    turnover = 0.0
    for session_index in range(len(dates) + horizon):
        closing = [position for position in active if position["exit_index"] == session_index]
        if closing:
            for position in closing:
                cash += position["capital"] * (1.0 + position["return"])
                closed_trade_count += int(position["trade_count"])
                turnover += float(position["capital"])
            active = [position for position in active if position["exit_index"] != session_index]

        active_capital = sum(float(position["capital"]) for position in active)
        equity = cash + active_capital
        if session_index < len(dates):
            rows = selected_by_date[dates[session_index]]
            if not rows.empty:
                allocation = min(max(0.0, equity / horizon), max(0.0, cash))
                cohort = _cohort(dates[session_index], rows)
                active.append(
                    {
                        **cohort,
                        "capital": allocation,
                        "exit_index": session_index + horizon,
                    }
                )
                cash -= allocation
                active_capital += allocation
                turnover += allocation
                cohort_count += 1
        equity = cash + active_capital
        equity_path.append(equity)
        if session_index < len(dates):
            cash_ratios.append(cash / equity if equity > 0 else 0.0)
            gross_exposures.append(active_capital / equity if equity > 0 else 0.0)

    selected = [rows for rows in selected_by_date.values() if not rows.empty]
    metrics = _portfolio_metrics(
        equity_path,
        periods=max(1, len(dates) + horizon),
        closed_trade_count=closed_trade_count,
        cohort_count=cohort_count,
        turnover=turnover,
        cash_ratios=cash_ratios,
        gross_exposures=gross_exposures,
        horizon=horizon,
    )
    metrics.update(
        _outcome_metrics(
            pd.concat(selected, ignore_index=True) if selected else pd.DataFrame(),
            risk_col=risk_col,
        )
    )
    return metrics


def _cohort(trade_date: str, rows: pd.DataFrame) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "return": float(rows[_RETURN].mean()),
        "trade_count": int(len(rows)),
    }


def _portfolio_metrics(
    equity_path: list[float],
    *,
    periods: int,
    closed_trade_count: int,
    cohort_count: int,
    turnover: float,
    cash_ratios: list[float],
    gross_exposures: list[float],
    horizon: int,
) -> dict[str, Any]:
    equity = np.asarray(equity_path, dtype=float)
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1.0
    total_return = float(equity[-1] - 1.0)
    annualized = (
        float(equity[-1] ** (252.0 / max(1, periods)) - 1.0)
        if equity[-1] > 0
        else -1.0
    )
    maximum_drawdown = float(drawdowns.min())
    return {
        "total_return": total_return,
        "annualized_return": annualized,
        "maximum_drawdown": maximum_drawdown,
        "return_drawdown_ratio": annualized / abs(maximum_drawdown) if maximum_drawdown < 0 else None,
        "turnover": float(turnover),
        "cohort_count": int(cohort_count),
        "closed_trade_count": int(closed_trade_count),
        "cash_ratio": float(np.mean(cash_ratios)) if cash_ratios else 1.0,
        "minimum_cash_ratio": float(min(cash_ratios)) if cash_ratios else 1.0,
        "max_gross_exposure": float(max(gross_exposures)) if gross_exposures else 0.0,
        "hold_days": horizon,
    }


def _outcome_metrics(rows: pd.DataFrame, *, risk_col: str) -> dict[str, float]:
    if rows.empty:
        return {
            "actionable_precision": 0.0,
            "positive_return_rate": 0.0,
            "mean_return": 0.0,
            "median_return": 0.0,
            "cvar_10": 0.0,
            "severe_rate": 0.0,
            "mean_mfe": 0.0,
            "mean_mae": 0.0,
            "mean_predicted_risk": 0.0,
        }
    returns = rows[_RETURN].to_numpy(dtype=float)
    tail_count = max(1, int(math.ceil(len(returns) * 0.10)))
    return {
        "actionable_precision": float(rows[_ACTIONABLE].eq(True).mean()),
        "positive_return_rate": float(np.mean(returns > 0.0)),
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "cvar_10": float(np.mean(np.sort(returns)[:tail_count])),
        "severe_rate": float(rows[_SEVERE].eq(True).mean()),
        "mean_mfe": float(rows[_MFE].mean()),
        "mean_mae": float(rows[_MAE].mean()),
        "mean_predicted_risk": float(rows[risk_col].mean()),
    }


def _date_ndcg(selected: pd.DataFrame, eligible: pd.DataFrame) -> float:
    size = min(10, len(selected))
    if size == 0:
        return 0.0
    grades = selected[_RELEVANCE].to_numpy(dtype=float)[:size]
    ideal = np.sort(eligible[_RELEVANCE].to_numpy(dtype=float))[::-1][:size]
    discounts = np.log2(np.arange(size, dtype=float) + 2.0)
    dcg = float(np.sum((np.power(2.0, grades) - 1.0) / discounts))
    idcg = float(np.sum((np.power(2.0, ideal) - 1.0) / discounts))
    return dcg / idcg if idcg > 0 else 0.0


def _mean_or_zero(values) -> float:
    materialized = list(values)
    return float(np.mean(materialized)) if materialized else 0.0


def _empty_portfolio(horizon: int) -> dict[str, Any]:
    result = _portfolio_metrics(
        [1.0],
        periods=1,
        closed_trade_count=0,
        cohort_count=0,
        turnover=0.0,
        cash_ratios=[],
        gross_exposures=[],
        horizon=horizon,
    )
    result.update(_outcome_metrics(pd.DataFrame(), risk_col="risk"))
    return result
