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


def evaluate_ranking(
    predictions: pd.DataFrame,
    *,
    score_col: str = "score",
    grade_col: str = _GRADE,
    strong_col: str = _STRONG,
) -> dict[str, Any]:
    """Evaluate predictions per signal date against an explicit label contract."""
    data = _validated_predictions(predictions, score_col, {grade_col, strong_col}, require_symbol=True)
    daily = [_daily_ranking_metrics(rows, score_col, grade_col=grade_col, strong_col=strong_col) for _, rows in data.groupby(_DATE, sort=True)]
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
    grade_col: str = _GRADE,
    strong_col: str = _STRONG,
    iterations: int = 1000,
    seed: int = 42,
    block_length: int = 10,
) -> dict[str, Any]:
    """Bootstrap metric uplift by resampling circular blocks of trade dates."""
    data = _validated_predictions(predictions, score_col, {grade_col, strong_col}, require_symbol=True)
    baseline_score_col = baseline_score_col or score_col
    if baseline_score_col not in data:
        raise ValueError(f"predictions missing baseline score column: {baseline_score_col}")
    dates = tuple(sorted(data[_DATE].unique()))
    block_length = max(1, int(block_length))
    if not dates:
        return {
            "resample_unit": _DATE,
            "bootstrap_method": "circular_block",
            "block_length": block_length,
            "source_date_count": 0,
            "iterations": 0,
            "precision_at_5_uplift_ci_low": 0.0,
            "precision_at_5_uplift_ci_high": 0.0,
        }

    rng = np.random.default_rng(seed)
    uplifts = []
    iterations = max(1, int(iterations))
    by_date = {date: rows for date, rows in data.groupby(_DATE, sort=False)}
    # Ranking a daily cross-section dominates runtime.  It is invariant across
    # bootstrap draws, so compute each pair once and resample only scalars.
    daily_uplifts = {
        date: _daily_ranking_metrics(
            rows, score_col, grade_col=grade_col, strong_col=strong_col
        )["precision_at_5"]
        - _daily_ranking_metrics(
            rows, baseline_score_col, grade_col=grade_col, strong_col=strong_col
        )["precision_at_5"]
        for date, rows in by_date.items()
    }
    for _ in range(iterations):
        sampled_dates = _sample_trade_date_block(dates, rng, block_length)
        uplifts.append(float(mean(daily_uplifts[str(date)] for date in sampled_dates)))
    low, high = np.quantile(np.asarray(uplifts, dtype=float), [0.025, 0.975])
    return {
        "resample_unit": _DATE,
        "bootstrap_method": "circular_block",
        "block_length": block_length,
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
    execution_columns = _execution_columns(predictions)
    required = set(execution_columns)
    data = _validated_predictions(predictions, score_col, required, require_symbol=True)
    top_k = max(1, int(top_k))
    commission, slippage = max(0.0, float(commission)), max(0.0, float(slippage))
    cohorts = []
    ambiguous_exit_count = 0
    untradeable_entry_count = 0
    unavailable_exit_count = 0
    for trade_date, rows in data.groupby(_DATE, sort=True):
        selected = rows.sort_values([score_col, "symbol"], ascending=[False, True], kind="stable").head(top_k)
        returns = []
        exit_dates = []
        for row in selected.itertuples(index=False):
            if _row_flag(row, "path_ambiguous", "path_ambiguous_10d"):
                ambiguous_exit_count += 1
                continue
            if hasattr(row, "entry_tradeable") and not _row_flag(row, "entry_tradeable"):
                untradeable_entry_count += 1
                continue
            if hasattr(row, "horizon_available_10d") and not _row_flag(row, "horizon_available_10d"):
                unavailable_exit_count += 1
                continue
            entry = _finite_positive(getattr(row, execution_columns[0]))
            exit_price = _finite_positive(getattr(row, execution_columns[1]))
            if entry is None or exit_price is None:
                unavailable_exit_count += 1
                continue
            net_return = ((exit_price * (1.0 - slippage)) / (entry * (1.0 + slippage))) * (1.0 - commission) ** 2 - 1.0
            returns.append(float(net_return))
            exit_date = getattr(row, execution_columns[2])
            if pd.isna(exit_date):
                unavailable_exit_count += 1
                returns.pop()
                continue
            exit_dates.append(str(exit_date))
        if returns:
            cohorts.append({"trade_date": str(trade_date), "exit_trade_date": max(exit_dates), "return": float(mean(returns)), "trade_count": len(returns)})
    if not cohorts:
        result = _empty_portfolio_result()
        result.update(
            {
                "ambiguous_exit_count": ambiguous_exit_count,
                "untradeable_entry_count": untradeable_entry_count,
                "unavailable_exit_count": unavailable_exit_count,
            }
        )
        return result

    cohort_returns = [cohort["return"] for cohort in cohorts]
    daily_returns = pd.DataFrame(cohorts).groupby("exit_trade_date", sort=True)["return"].mean().to_numpy(dtype=float)
    equity = np.cumprod(1.0 + daily_returns)
    total_return = float(equity[-1] - 1.0)
    peaks = np.maximum.accumulate(equity)
    maximum_drawdown = float(np.min(equity / peaks - 1.0)) if len(equity) else 0.0
    daily_std = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 0.0
    sharpe = float(np.mean(daily_returns) / daily_std * math.sqrt(252)) if daily_std > 0 else 0.0
    annualized = float(equity[-1] ** (252 / max(1, len(daily_returns))) - 1.0)
    return {
        "total_return": total_return,
        "annualized_return": annualized,
        "maximum_drawdown": maximum_drawdown,
        "sharpe": sharpe,
        "turnover": float(2.0 * sum(cohort["trade_count"] for cohort in cohorts) / len(cohorts)),
        "cohort_count": len(cohorts),
        "closed_trade_count": int(sum(cohort["trade_count"] for cohort in cohorts)),
        "ambiguous_exit_count": ambiguous_exit_count,
        "untradeable_entry_count": untradeable_entry_count,
        "unavailable_exit_count": unavailable_exit_count,
        "hold_days": max(1, int(hold_days)),
    }


def validate_identical_comparison_rows(comparators: dict[str, pd.DataFrame]) -> None:
    """Require every score comparator to use identical keys and risk eligibility."""
    if len(comparators) < 2:
        raise ValueError("at least two comparators are required")
    reference_name, reference = next(iter(comparators.items()))
    columns = ["trade_date", "symbol"]
    if "risk_eligible" in reference:
        columns.append("risk_eligible")
    reference_rows = reference[columns].sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)
    for name, rows in list(comparators.items())[1:]:
        missing = sorted(set(columns) - set(rows.columns))
        if missing:
            raise ValueError(f"comparator {name} missing comparison columns: {', '.join(missing)}")
        current = rows[columns].sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)
        if not current[["trade_date", "symbol"]].equals(reference_rows[["trade_date", "symbol"]]):
            raise ValueError(f"comparator {name} does not use identical rows as {reference_name}")
        if "risk_eligible" in columns and not current["risk_eligible"].equals(reference_rows["risk_eligible"]):
            raise ValueError(f"comparator {name} does not use the identical risk mask as {reference_name}")


def simulate_daily_mark_to_market_portfolio(
    signals: pd.DataFrame,
    price_panel: pd.DataFrame,
    *,
    score_col: str,
    eligible_col: str | None = None,
    top_k: int = 5,
    hold_sessions: int = 10,
    commission: float = 0.0003,
    slippage: float = 0.001,
    daily_cohort_fraction: float = 0.10,
    per_stock_cap: float = 0.02,
    max_gross_exposure: float = 1.0,
) -> dict[str, Any]:
    """Simulate next-open entries and daily close mark-to-market equity."""
    signal_required = {"trade_date", "symbol", score_col}
    price_required = {
        "trade_date", "symbol", "adjusted_open", "adjusted_close",
        "is_suspended", "at_up_limit_open",
    }
    missing_signals = sorted(signal_required - set(signals.columns))
    missing_prices = sorted(price_required - set(price_panel.columns))
    if missing_signals or missing_prices:
        raise ValueError(
            "mark-to-market inputs missing columns: "
            + ", ".join([*missing_signals, *missing_prices])
        )
    if eligible_col is not None and eligible_col not in signals:
        raise ValueError(f"signals missing eligibility column: {eligible_col}")
    if not 0 < daily_cohort_fraction <= 1 or not 0 < per_stock_cap <= 1 or not 0 < max_gross_exposure <= 1:
        raise ValueError("portfolio exposure fractions must be in (0, 1]")
    top_k = max(1, int(top_k))
    hold_sessions = max(1, int(hold_sessions))
    commission = max(0.0, float(commission))
    slippage = max(0.0, float(slippage))
    prices = price_panel.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    prices["symbol"] = prices["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    prices = prices.sort_values(["trade_date", "symbol"], kind="stable").drop_duplicates(
        ["trade_date", "symbol"], keep="last"
    )
    calendar = tuple(sorted(prices["trade_date"].dropna().unique()))
    calendar_index = {date: index for index, date in enumerate(calendar)}
    lookup = prices.set_index(["trade_date", "symbol"])
    if not lookup.index.is_unique:
        raise ValueError("price panel contains duplicate trade_date and symbol rows")
    signal_rows = signals.copy()
    signal_rows["trade_date"] = pd.to_datetime(signal_rows["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    signal_rows["symbol"] = signal_rows["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    if eligible_col is not None:
        signal_rows = signal_rows.loc[signal_rows[eligible_col].eq(True)]
    orders_by_date: dict[str, list[str]] = {}
    for signal_date, daily in signal_rows.groupby("trade_date", sort=True):
        index = calendar_index.get(signal_date)
        if index is None or index + 1 >= len(calendar):
            continue
        selected = daily.dropna(subset=[score_col]).sort_values(
            [score_col, "symbol"], ascending=[False, True], kind="stable"
        ).head(top_k)
        orders_by_date.setdefault(calendar[index + 1], []).extend(selected["symbol"].tolist())

    cash = 1.0
    positions: dict[str, dict[str, float | int]] = {}
    equity_curve = []
    opened = closed = duplicate_skips = untradeable_skips = 0
    turnover_notional = 0.0
    prior_equity = 1.0
    for date_index, trade_date in enumerate(calendar):
        opening_values = {}
        for symbol, position in positions.items():
            row = _price_row(lookup, trade_date, symbol)
            if row is not None:
                opening_values[symbol] = float(position["quantity"]) * float(row["adjusted_open"])
        gross_open = sum(opening_values.values())
        capacity = max(0.0, max_gross_exposure * prior_equity - gross_open)
        candidates = []
        for symbol in orders_by_date.get(trade_date, []):
            if symbol in positions:
                duplicate_skips += 1
                continue
            row = _price_row(lookup, trade_date, symbol)
            if row is None or bool(row["is_suspended"]) or bool(row["at_up_limit_open"]):
                untradeable_skips += 1
                continue
            opening = float(row["adjusted_open"])
            if not np.isfinite(opening) or opening <= 0:
                untradeable_skips += 1
                continue
            candidates.append((symbol, opening))
        cohort_budget = min(cash, prior_equity * daily_cohort_fraction, capacity)
        per_position = min(
            prior_equity * per_stock_cap,
            cohort_budget / len(candidates) if candidates else 0.0,
        )
        for symbol, opening in candidates:
            if per_position <= 0 or cash + 1e-12 < per_position:
                break
            execution_price = opening * (1.0 + slippage)
            quantity = per_position / (execution_price * (1.0 + commission))
            cash -= per_position
            positions[symbol] = {
                "quantity": quantity,
                "entry_index": date_index,
            }
            turnover_notional += per_position
            opened += 1

        close_values = {}
        exits = []
        for symbol, position in positions.items():
            row = _price_row(lookup, trade_date, symbol)
            if row is None:
                continue
            close = float(row["adjusted_close"])
            if not np.isfinite(close) or close <= 0:
                continue
            value = float(position["quantity"]) * close
            close_values[symbol] = value
            if date_index - int(position["entry_index"]) + 1 >= hold_sessions:
                proceeds = value * (1.0 - slippage) * (1.0 - commission)
                cash += proceeds
                turnover_notional += proceeds
                exits.append(symbol)
                closed += 1
        for symbol in exits:
            positions.pop(symbol, None)
            close_values.pop(symbol, None)
        equity = cash + sum(close_values.values())
        prior_equity = equity
        equity_curve.append(
            {
                "trade_date": trade_date,
                "equity": float(equity),
                "cash": float(cash),
                "position_count": len(positions),
                "gross_exposure": float(sum(close_values.values()) / equity) if equity > 0 else 0.0,
            }
        )
    if not equity_curve:
        return {
            "total_return": 0.0,
            "maximum_drawdown": 0.0,
            "opened_trade_count": 0,
            "closed_trade_count": 0,
            "duplicate_position_skip_count": 0,
            "untradeable_entry_count": 0,
            "turnover": 0.0,
            "equity_curve": [],
        }
    equity = np.asarray([row["equity"] for row in equity_curve], dtype="float64")
    peaks = np.maximum.accumulate(equity)
    drawdown = equity / peaks - 1.0
    average_equity = float(np.mean(equity))
    return {
        "total_return": float(equity[-1] - 1.0),
        "maximum_drawdown": float(drawdown.min()),
        "opened_trade_count": opened,
        "closed_trade_count": closed,
        "open_position_count": len(positions),
        "duplicate_position_skip_count": duplicate_skips,
        "untradeable_entry_count": untradeable_skips,
        "turnover": float(turnover_notional / average_equity) if average_equity > 0 else 0.0,
        "equity_curve": equity_curve,
    }


def _price_row(lookup: pd.DataFrame, trade_date: str, symbol: str):
    try:
        return lookup.loc[(trade_date, symbol)]
    except KeyError:
        return None


def _daily_ranking_metrics(
    rows: pd.DataFrame,
    score_col: str,
    *,
    grade_col: str = _GRADE,
    strong_col: str = _STRONG,
) -> dict[str, float]:
    ranked = rows.sort_values([score_col, "symbol"], ascending=[False, True], kind="stable").reset_index(drop=True)
    strong = ranked[strong_col].astype(bool).to_numpy()
    grades = pd.to_numeric(ranked[grade_col], errors="coerce").fillna(0.0).clip(lower=0.0).to_numpy()
    return_column = _first_existing(ranked, ("net_return_after_cost", "net_return_after_cost_10d", _RETURN))
    returns = pd.to_numeric(ranked.get(return_column, pd.Series(0.0, index=ranked.index)), errors="coerce").fillna(0.0).to_numpy()
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
    for columns, key in (
        (("market_median_net_return_10d", "market_median_future_return_10d"), "market_excess_return"),
        (("industry_median_net_return_10d", "industry_median_future_return_10d"), "industry_excess_return"),
    ):
        column = _first_existing(ranked, columns)
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


def _execution_columns(predictions: pd.DataFrame) -> tuple[str, str, str]:
    canonical = ("entry_price", "exit_price", "exit_trade_date")
    suffixed = ("entry_price_10d", "exit_price_10d", "exit_trade_date_10d")
    legacy = ("adjusted_next_open", "adjusted_exit_close", "exit_trade_date")
    for columns in (canonical, suffixed, legacy):
        if set(columns).issubset(predictions.columns):
            return columns
    raise ValueError(
        "predictions missing canonical execution fields: entry_price, exit_price, exit_trade_date"
    )


def _sample_trade_date_block(dates: tuple[Any, ...], rng: np.random.Generator, block_length: int) -> list[Any]:
    if not dates:
        return []
    sampled = []
    while len(sampled) < len(dates):
        start = int(rng.integers(0, len(dates)))
        sampled.extend(dates[(start + offset) % len(dates)] for offset in range(block_length))
    return sampled[: len(dates)]


def _first_existing(frame: pd.DataFrame, columns: tuple[str, ...]) -> str:
    return next((column for column in columns if column in frame), "")


def _row_flag(row: Any, *names: str) -> bool:
    for name in names:
        if hasattr(row, name):
            value = getattr(row, name)
            if pd.isna(value):
                return False
            return bool(value)
    return False


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
    return {
        "total_return": 0.0,
        "annualized_return": 0.0,
        "maximum_drawdown": 0.0,
        "sharpe": 0.0,
        "turnover": 0.0,
        "cohort_count": 0,
        "closed_trade_count": 0,
        "ambiguous_exit_count": 0,
        "untradeable_entry_count": 0,
        "unavailable_exit_count": 0,
        "hold_days": 10,
    }
