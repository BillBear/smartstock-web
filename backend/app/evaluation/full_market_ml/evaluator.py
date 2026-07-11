"""Read-only offline evaluation for full-market ML ranking predictions."""
from __future__ import annotations

import math
from statistics import mean, median
from typing import Any

import numpy as np
import pandas as pd


_DATE = "trade_date"
_RETURN = "future_return_10d"
_GRADE = "relevance_grade_10d"
_STRONG = "label_strong_path_10d"


def evaluate_ranking(predictions: pd.DataFrame, *, score_col: str = "score") -> dict[str, Any]:
    """Evaluate predictions per signal date, then average each daily metric."""
    data = _validated_predictions(predictions, score_col, {_GRADE, _STRONG}, require_symbol=True)
    daily = [_daily_ranking_metrics(rows, score_col) for _, rows in data.groupby(_DATE, sort=True)]
    if not daily:
        return _empty_ranking_result()

    result = {"date_count": len(daily)}
    for key in daily[0]:
        if key != "candidate_count":
            result[key] = _mean_metric(row[key] for row in daily)
    result["candidate_count"] = int(sum(row["candidate_count"] for row in daily))
    return result


def evaluate_calibration(predictions: pd.DataFrame, *, score_col: str = "score", bins: int = 10) -> dict[str, Any]:
    """Report Brier score and ECE using equal-count prediction bins."""
    data = _validated_predictions(predictions, score_col, {_STRONG})
    probabilities = pd.to_numeric(data[score_col], errors="coerce").clip(0.0, 1.0)
    outcomes = data[_STRONG].astype(bool).astype(float)
    valid = probabilities.notna() & outcomes.notna()
    probabilities, outcomes = probabilities.loc[valid], outcomes.loc[valid]
    if probabilities.empty:
        return {"brier": 0.0, "ece": 0.0, "bin_count": 0, "bins": []}

    bin_count = min(max(1, int(bins)), len(probabilities))
    ordered = pd.DataFrame({"probability": probabilities, "outcome": outcomes}).sort_values("probability", kind="stable")
    index_groups = np.array_split(np.arange(len(ordered)), bin_count)
    calibration_bins = []
    ece = 0.0
    for number, indexes in enumerate(index_groups, start=1):
        current = ordered.iloc[indexes]
        predicted = float(current["probability"].mean())
        observed = float(current["outcome"].mean())
        count = int(len(current))
        ece += abs(predicted - observed) * count / len(ordered)
        calibration_bins.append(
            {
                "bin": number,
                "count": count,
                "mean_predicted_probability": predicted,
                "hit_rate": observed,
            }
        )
    return {
        "brier": float(np.mean((probabilities - outcomes) ** 2)),
        "ece": float(ece),
        "bin_count": bin_count,
        "bins": calibration_bins,
    }


def bootstrap_uplift(
    predictions: pd.DataFrame,
    *,
    score_col: str = "score",
    baseline_score_col: str | None = None,
    iterations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Bootstrap metric uplift by resampling complete trade-date cross sections."""
    data = _validated_predictions(predictions, score_col, {_GRADE, _STRONG}, require_symbol=True)
    baseline_score_col = baseline_score_col or score_col
    if baseline_score_col not in data:
        raise ValueError(f"predictions missing baseline score column: {baseline_score_col}")
    dates = tuple(sorted(data[_DATE].unique()))
    if not dates:
        return {"resample_unit": _DATE, "source_date_count": 0, "iterations": 0, "precision_at_5_uplift_ci_low": 0.0, "precision_at_5_uplift_ci_high": 0.0}

    rng = np.random.default_rng(seed)
    uplifts = []
    iterations = max(1, int(iterations))
    by_date = {date: rows for date, rows in data.groupby(_DATE, sort=False)}
    for _ in range(iterations):
        sampled_dates = rng.choice(dates, size=len(dates), replace=True)
        model_scores = []
        baseline_scores = []
        for date in sampled_dates:
            rows = by_date[str(date)]
            model_scores.append(_daily_ranking_metrics(rows, score_col)["precision_at_5"])
            baseline_scores.append(_daily_ranking_metrics(rows, baseline_score_col)["precision_at_5"])
        uplifts.append(float(mean(model_scores) - mean(baseline_scores)))
    low, high = np.quantile(np.asarray(uplifts, dtype=float), [0.025, 0.975])
    return {
        "resample_unit": _DATE,
        "source_date_count": len(dates),
        "iterations": iterations,
        "precision_at_5_uplift": float(mean(uplifts)),
        "precision_at_5_uplift_ci_low": float(low),
        "precision_at_5_uplift_ci_high": float(high),
    }


def simulate_daily_topk_portfolio(
    predictions: pd.DataFrame,
    *,
    score_col: str = "score",
    top_k: int = 5,
    hold_days: int = 10,
    commission: float = 0.0003,
    slippage: float = 0.001,
) -> dict[str, Any]:
    """Simulate equal-weight daily Top-K cohorts entered next open and exited at horizon."""
    required = {"adjusted_next_open", "adjusted_exit_close", "exit_trade_date"}
    data = _validated_predictions(predictions, score_col, required, require_symbol=True)
    top_k = max(1, int(top_k))
    commission, slippage = max(0.0, float(commission)), max(0.0, float(slippage))
    cohorts = []
    for trade_date, rows in data.groupby(_DATE, sort=True):
        selected = rows.sort_values([score_col, "symbol"], ascending=[False, True], kind="stable").head(top_k)
        returns = []
        exit_dates = []
        for row in selected.itertuples(index=False):
            entry = _finite_positive(getattr(row, "adjusted_next_open"))
            exit_price = _finite_positive(getattr(row, "adjusted_exit_close"))
            if entry is None or exit_price is None:
                continue
            net_return = ((exit_price * (1.0 - slippage)) / (entry * (1.0 + slippage))) * (1.0 - commission) ** 2 - 1.0
            returns.append(float(net_return))
            exit_dates.append(str(getattr(row, "exit_trade_date")))
        if returns:
            cohorts.append({"trade_date": str(trade_date), "exit_trade_date": max(exit_dates), "return": float(mean(returns)), "trade_count": len(returns)})
    if not cohorts:
        return _empty_portfolio_result()

    cohort_returns = [cohort["return"] for cohort in cohorts]
    total_return = float(mean(cohort_returns))
    daily_returns = pd.DataFrame(cohorts).groupby("exit_trade_date", sort=True)["return"].mean().to_numpy(dtype=float)
    equity = np.cumprod(1.0 + daily_returns)
    peaks = np.maximum.accumulate(equity)
    maximum_drawdown = float(np.min(equity / peaks - 1.0)) if len(equity) else 0.0
    daily_std = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 0.0
    sharpe = float(np.mean(daily_returns) / daily_std * math.sqrt(252)) if daily_std > 0 else 0.0
    annualized = float((1.0 + total_return) ** (252 / max(1, len(daily_returns))) - 1.0)
    return {
        "total_return": total_return,
        "annualized_return": annualized,
        "maximum_drawdown": maximum_drawdown,
        "sharpe": sharpe,
        "turnover": float(2.0 * sum(cohort["trade_count"] for cohort in cohorts) / len(cohorts)),
        "cohort_count": len(cohorts),
        "closed_trade_count": int(sum(cohort["trade_count"] for cohort in cohorts)),
        "hold_days": max(1, int(hold_days)),
    }


def _daily_ranking_metrics(rows: pd.DataFrame, score_col: str) -> dict[str, float]:
    ranked = rows.sort_values([score_col, "symbol"], ascending=[False, True], kind="stable").reset_index(drop=True)
    strong = ranked[_STRONG].astype(bool).to_numpy()
    grades = pd.to_numeric(ranked[_GRADE], errors="coerce").fillna(0.0).clip(lower=0.0).to_numpy()
    returns = pd.to_numeric(ranked.get(_RETURN, pd.Series(0.0, index=ranked.index)), errors="coerce").fillna(0.0).to_numpy()
    top = lambda size: slice(0, min(size, len(ranked)))
    denominator = lambda size: max(1, min(size, len(ranked)))
    ideal = np.sort(grades)[::-1][:10]
    dcg = sum((2.0 ** grade - 1.0) / math.log2(index + 2) for index, grade in enumerate(grades[:10]))
    idcg = sum((2.0 ** grade - 1.0) / math.log2(index + 2) for index, grade in enumerate(ideal))
    first = np.flatnonzero(strong)
    top5_returns = returns[top(5)]
    result = {
        "candidate_count": float(len(ranked)),
        "precision_at_3": float(strong[top(3)].sum() / denominator(3)),
        "precision_at_5": float(strong[top(5)].sum() / denominator(5)),
        "precision_at_10": float(strong[top(10)].sum() / denominator(10)),
        "recall_at_10": float(strong[top(10)].sum() / strong.sum()) if strong.sum() else 0.0,
        "ndcg_at_10": float(dcg / idcg) if idcg > 0 else 0.0,
        "mrr": float(1.0 / (first[0] + 1)) if len(first) else 0.0,
        "top_5_mean_return": float(np.mean(top5_returns)) if len(top5_returns) else 0.0,
        "top_5_median_return": float(np.median(top5_returns)) if len(top5_returns) else 0.0,
        "top_5_positive_rate": float(np.mean(top5_returns > 0.0)) if len(top5_returns) else 0.0,
    }
    for column, key in (("market_median_future_return_10d", "market_excess_return"), ("industry_median_future_return_10d", "industry_excess_return")):
        if column in ranked:
            benchmark = pd.to_numeric(ranked[column], errors="coerce").to_numpy()[top(5)]
            valid = np.isfinite(benchmark)
            result[key] = float(np.mean(top5_returns[valid] - benchmark[valid])) if valid.any() else 0.0
        else:
            result[key] = 0.0
    for column, key in (("mfe_10d", "mfe"), ("mae_10d", "mae"), ("future_limit_up_count_10d", "limit_up_rate"), ("future_limit_down_count_10d", "limit_down_rate"), ("tp_before_sl_10d", "tp_before_sl_rate"), ("sl_before_tp_10d", "sl_before_tp_rate"), ("label_severe_negative_10d", "severe_negative_rate")):
        values = ranked[column].iloc[top(5)] if column in ranked else pd.Series(dtype=float)
        numeric = pd.to_numeric(values, errors="coerce") if key in {"mfe", "mae"} else values.astype(bool)
        result[key] = float(numeric.mean()) if len(numeric) else 0.0
    return result


def _validated_predictions(
    predictions: pd.DataFrame,
    score_col: str,
    extra_required: set[str],
    *,
    require_symbol: bool = False,
) -> pd.DataFrame:
    if not isinstance(predictions, pd.DataFrame):
        raise TypeError("predictions must be a pandas DataFrame")
    required = {_DATE, score_col, *extra_required}
    if require_symbol:
        required.add("symbol")
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError("predictions missing columns: " + ", ".join(missing))
    data = predictions.copy()
    data[_DATE] = pd.to_datetime(data[_DATE], errors="coerce").dt.strftime("%Y-%m-%d")
    data[score_col] = pd.to_numeric(data[score_col], errors="coerce")
    return data.loc[data[_DATE].notna() & data[score_col].notna()].copy()


def _mean_metric(values: Any) -> float:
    return float(mean(values))


def _finite_positive(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _empty_ranking_result() -> dict[str, Any]:
    return {"date_count": 0, "candidate_count": 0, "precision_at_3": 0.0, "precision_at_5": 0.0, "precision_at_10": 0.0, "recall_at_10": 0.0, "ndcg_at_10": 0.0, "mrr": 0.0}


def _empty_portfolio_result() -> dict[str, Any]:
    return {"total_return": 0.0, "annualized_return": 0.0, "maximum_drawdown": 0.0, "sharpe": 0.0, "turnover": 0.0, "cohort_count": 0, "closed_trade_count": 0, "hold_days": 10}
