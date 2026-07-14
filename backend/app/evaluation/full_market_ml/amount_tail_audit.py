"""Pre-registered diagnostics for the full-market trading-amount tail signal."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .evaluator import _daily_ranking_metrics


REGISTERED_CANDIDATE = "neutral_amount_tail_diversified"
PRIMARY_METRIC_BASELINES = {
    "precision_at_5": "amount_raw",
    "ndcg_at_10": "adjusted_return_20d",
    "top_5_mean_return": "amount_raw",
}
SCORE_INPUT_COLUMNS = (
    "trade_date",
    "symbol",
    "industry_l1",
    "amount_cny",
    "circ_mv",
    "adjusted_close",
    "median_amount_20d",
    "amount_ratio_5d",
    "amount_ratio_20d",
    "turnover_rate",
    "turnover_ratio_20d",
)


def build_amount_tail_scores(
    rows: pd.DataFrame,
    *,
    top_k: int = 5,
    industry_max_share: float = 0.25,
) -> pd.DataFrame:
    """Build fixed point-in-time amount diagnostics and one registered candidate."""
    _require_columns(rows, SCORE_INPUT_COLUMNS, "amount-tail feature rows")
    if not 0 < float(industry_max_share) <= 1:
        raise ValueError("industry_max_share must be in (0, 1]")
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    result["symbol"] = _normalise_symbols(result["symbol"])
    if result.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("amount-tail feature rows contain duplicate trade_date and symbol keys")

    amount = _positive_numeric(result["amount_cny"])
    circ_mv = _positive_numeric(result["circ_mv"])
    result["score__amount_raw"] = np.log1p(amount)
    for source in (
        "amount_ratio_5d",
        "amount_ratio_20d",
        "turnover_rate",
        "turnover_ratio_20d",
    ):
        result[f"score__{source}"] = pd.to_numeric(result[source], errors="coerce")
    result["score__amount_to_float_mv"] = np.log1p(amount) - np.log1p(circ_mv * 10_000.0)
    result["score__industry_amount_rank"] = result.groupby(
        ["trade_date", result["industry_l1"].fillna("__UNKNOWN__")],
        sort=False,
    )["score__amount_raw"].rank(method="average", pct=True)
    result["score__neutral_amount_tail"] = _cross_sectional_neutral_residual(result)
    result["score__neutral_amount_tail_diversified"] = np.nan
    for _, index in result.groupby("trade_date", sort=True).groups.items():
        current = result.loc[index]
        result.loc[index, "score__neutral_amount_tail_diversified"] = _diversified_order_score(
            current,
            source_col="score__neutral_amount_tail",
            top_k=top_k,
            industry_max_share=industry_max_share,
        )
    return result


def build_quantile_curve(
    rows: pd.DataFrame,
    score_columns: Iterable[str],
    *,
    quantile_count: int = 20,
) -> pd.DataFrame:
    """Summarise fixed scores in daily cross-sectional quantiles."""
    quantile_count = int(quantile_count)
    if quantile_count < 2:
        raise ValueError("quantile_count must be at least 2")
    required = (
        "trade_date",
        "quadrant",
        "alpha_top10_10d",
        "net_return_after_cost_10d",
        "severe_negative_10d",
        "mae_10d",
        *tuple(score_columns),
    )
    _require_columns(rows, required, "quantile rows")
    outputs = []
    for score_col in score_columns:
        current = rows.loc[rows[score_col].notna()].copy()
        percent_rank = current.groupby(["quadrant", "trade_date"], sort=False)[score_col].rank(
            method="first", pct=True
        )
        current["quantile"] = np.ceil(percent_rank * quantile_count).clip(1, quantile_count).astype(int)
        current["positive_return"] = pd.to_numeric(
            current["net_return_after_cost_10d"], errors="coerce"
        ).gt(0)
        grouped = current.groupby(["quadrant", "quantile"], sort=True, dropna=False)
        summary = grouped.agg(
            row_count=("symbol", "size"),
            date_count=("trade_date", "nunique"),
            top10_hit_rate=("alpha_top10_10d", "mean"),
            mean_net_return=("net_return_after_cost_10d", "mean"),
            median_net_return=("net_return_after_cost_10d", "median"),
            positive_return_rate=("positive_return", "mean"),
            severe_negative_rate=("severe_negative_10d", "mean"),
            mean_mae=("mae_10d", "mean"),
        ).reset_index()
        summary.insert(1, "score", score_col.removeprefix("score__"))
        outputs.append(summary)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def build_daily_metric_frame(
    rows: pd.DataFrame,
    score_columns: Iterable[str],
) -> pd.DataFrame:
    """Precompute daily ranking metrics once for bootstrap and gate checks."""
    score_columns = tuple(score_columns)
    required = (
        "trade_date",
        "symbol",
        "fold",
        "quadrant",
        "market_state",
        "alpha_relevance_grade_10d",
        "alpha_top10_10d",
        "net_return_after_cost_10d",
        *score_columns,
    )
    _require_columns(rows, required, "daily metric rows")
    output = []
    group_columns = ["quadrant", "fold", "trade_date", "market_state"]
    for keys, daily in rows.groupby(group_columns, sort=True, dropna=False):
        context = dict(zip(group_columns, keys, strict=True))
        for score_col in score_columns:
            metrics = _daily_ranking_metrics(
                daily,
                score_col,
                grade_col="alpha_relevance_grade_10d",
                strong_col="alpha_top10_10d",
            )
            output.append(
                {
                    **context,
                    "score": score_col.removeprefix("score__"),
                    **metrics,
                }
            )
    return pd.DataFrame(output)


def circular_block_metric_uplift(
    daily_metrics: pd.DataFrame,
    *,
    candidate: str,
    baseline: str,
    metric: str,
    iterations: int = 2_000,
    block_length: int = 10,
    seed: int = 17,
) -> dict[str, Any]:
    """Bootstrap an uplift by resampling precomputed complete date blocks."""
    _require_columns(daily_metrics, ("trade_date", "score", metric), "daily bootstrap metrics")
    working = daily_metrics.loc[daily_metrics["score"].isin((candidate, baseline))]
    pivot = working.pivot_table(index="trade_date", columns="score", values=metric, aggfunc="mean")
    missing = sorted({candidate, baseline} - set(pivot.columns))
    if missing:
        raise ValueError("daily bootstrap metrics missing scores: " + ", ".join(missing))
    differences = (pivot[candidate] - pivot[baseline]).dropna().sort_index()
    if differences.empty:
        raise ValueError("daily bootstrap metrics have no comparable dates")
    values = differences.to_numpy(dtype="float64")
    sample_size = len(values)
    block_length = max(1, min(int(block_length), sample_size))
    iterations = max(1, int(iterations))
    generator = np.random.default_rng(seed)
    means = np.empty(iterations, dtype="float64")
    block_count = math.ceil(sample_size / block_length)
    for offset in range(iterations):
        starts = generator.integers(0, sample_size, size=block_count)
        indexes = np.concatenate(
            [(np.arange(start, start + block_length) % sample_size) for start in starts]
        )[:sample_size]
        means[offset] = float(values[indexes].mean())
    low, high = np.quantile(means, [0.025, 0.975])
    return {
        "candidate": candidate,
        "baseline": baseline,
        "metric": metric,
        "method": "circular_trade_date_block",
        "source_date_count": sample_size,
        "iterations": iterations,
        "block_length": block_length,
        "mean_uplift": float(values.mean()),
        "ci_low": float(low),
        "ci_high": float(high),
    }


def simulate_equal_exposure_lot_portfolio(
    signals: pd.DataFrame,
    price_panel: pd.DataFrame,
    *,
    score_col: str,
    top_k: int = 5,
    hold_sessions: int = 10,
    commission: float = 0.0003,
    slippage: float = 0.001,
    daily_cohort_fraction: float = 0.10,
    per_stock_fraction: float = 0.02,
    max_gross_exposure: float = 1.0,
    require_full_cohort: bool = True,
) -> dict[str, Any]:
    """Mark repeated symbols as independent lots under a fixed daily budget."""
    _require_columns(signals, ("trade_date", "symbol", score_col), "portfolio signals")
    _require_columns(
        price_panel,
        (
            "trade_date",
            "symbol",
            "adjusted_open",
            "adjusted_close",
            "is_suspended",
            "at_up_limit_open",
        ),
        "portfolio prices",
    )
    if not all(0 < value <= 1 for value in (daily_cohort_fraction, per_stock_fraction, max_gross_exposure)):
        raise ValueError("portfolio exposure fractions must be in (0, 1]")
    top_k = max(1, int(top_k))
    hold_sessions = max(1, int(hold_sessions))
    commission = max(0.0, float(commission))
    slippage = max(0.0, float(slippage))
    prices = price_panel.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    prices["symbol"] = _normalise_symbols(prices["symbol"])
    prices = prices.sort_values(["trade_date", "symbol"], kind="stable").drop_duplicates(
        ["trade_date", "symbol"], keep="last"
    )
    calendar = tuple(sorted(prices["trade_date"].unique()))
    calendar_index = {date: index for index, date in enumerate(calendar)}
    lookup = prices.set_index(["trade_date", "symbol"])
    signal_rows = signals.copy()
    signal_rows["trade_date"] = pd.to_datetime(signal_rows["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    signal_rows["symbol"] = _normalise_symbols(signal_rows["symbol"])
    orders: dict[str, list[str]] = {}
    for signal_date, daily in signal_rows.groupby("trade_date", sort=True):
        index = calendar_index.get(signal_date)
        if index is None or index + 1 >= len(calendar):
            continue
        selected = daily.dropna(subset=[score_col]).sort_values(
            [score_col, "symbol"], ascending=[False, True], kind="stable"
        ).head(top_k)
        if require_full_cohort and len(selected) != top_k:
            continue
        orders[calendar[index + 1]] = selected["symbol"].tolist()

    cash = 1.0
    lots: list[dict[str, Any]] = []
    curve = []
    opened = closed = untradeable = incomplete = complete = 0
    turnover_notional = 0.0
    prior_equity = 1.0
    for date_index, trade_date in enumerate(calendar):
        opening_values = []
        for lot in lots:
            row = _lookup_price(lookup, trade_date, lot["symbol"])
            if row is not None:
                opening_values.append(float(lot["quantity"]) * float(row["adjusted_open"]))
        capacity = max(0.0, max_gross_exposure * prior_equity - sum(opening_values))
        candidates = []
        for symbol in orders.get(trade_date, []):
            row = _lookup_price(lookup, trade_date, symbol)
            if row is None or bool(row["is_suspended"]) or bool(row["at_up_limit_open"]):
                untradeable += 1
                continue
            opening = float(row["adjusted_open"])
            if not np.isfinite(opening) or opening <= 0:
                untradeable += 1
                continue
            candidates.append((symbol, opening))
        if candidates and (not require_full_cohort or len(candidates) == top_k):
            cohort_budget = min(cash, prior_equity * daily_cohort_fraction, capacity)
            per_position = min(prior_equity * per_stock_fraction, cohort_budget / len(candidates))
            if per_position > 0 and cash + 1e-12 >= per_position * len(candidates):
                for symbol, opening in candidates:
                    execution_price = opening * (1.0 + slippage)
                    quantity = per_position / (execution_price * (1.0 + commission))
                    cash -= per_position
                    lots.append({"symbol": symbol, "quantity": quantity, "entry_index": date_index})
                    turnover_notional += per_position
                    opened += 1
                complete += 1
            else:
                incomplete += 1
        elif orders.get(trade_date):
            incomplete += 1

        close_values = []
        survivors = []
        for lot in lots:
            row = _lookup_price(lookup, trade_date, lot["symbol"])
            if row is None:
                survivors.append(lot)
                continue
            close = float(row["adjusted_close"])
            if not np.isfinite(close) or close <= 0:
                survivors.append(lot)
                continue
            value = float(lot["quantity"]) * close
            if date_index - int(lot["entry_index"]) + 1 >= hold_sessions:
                proceeds = value * (1.0 - slippage) * (1.0 - commission)
                cash += proceeds
                turnover_notional += proceeds
                closed += 1
            else:
                close_values.append(value)
                survivors.append(lot)
        lots = survivors
        equity = cash + sum(close_values)
        prior_equity = equity
        curve.append(
            {
                "trade_date": trade_date,
                "equity": float(equity),
                "cash": float(cash),
                "lot_count": len(lots),
                "gross_exposure": float(sum(close_values) / equity) if equity > 0 else 0.0,
            }
        )
    equity_values = np.asarray([row["equity"] for row in curve], dtype="float64")
    if len(equity_values):
        drawdown = equity_values / np.maximum.accumulate(equity_values) - 1.0
        total_return = float(equity_values[-1] - 1.0)
        maximum_drawdown = float(drawdown.min())
        average_equity = float(equity_values.mean())
    else:
        total_return = maximum_drawdown = average_equity = 0.0
    return {
        "total_return": total_return,
        "maximum_drawdown": maximum_drawdown,
        "opened_trade_count": opened,
        "closed_trade_count": closed,
        "open_lot_count": len(lots),
        "complete_cohort_count": complete,
        "incomplete_cohort_count": incomplete,
        "duplicate_position_skip_count": 0,
        "untradeable_entry_count": untradeable,
        "turnover": float(turnover_notional / average_equity) if average_equity > 0 else 0.0,
        "equity_curve": curve,
    }


def evaluate_amount_tail_gate(
    daily_metrics: pd.DataFrame,
    *,
    industry_concentration: Mapping[str, Mapping[str, float]],
    portfolios: Mapping[str, Mapping[str, Mapping[str, float]]],
    bootstrap_iterations: int = 2_000,
) -> dict[str, Any]:
    """Apply the pre-registered joint gate without post-result model selection."""
    required_scores = {REGISTERED_CANDIDATE, "amount_raw", "adjusted_return_20d", "random"}
    _require_columns(
        daily_metrics,
        (
            "trade_date",
            "fold",
            "quadrant",
            "market_state",
            "score",
            *PRIMARY_METRIC_BASELINES,
        ),
        "amount-tail gate metrics",
    )
    missing_scores = sorted(required_scores - set(daily_metrics["score"].astype(str)))
    if missing_scores:
        raise ValueError("amount-tail gate metrics missing scores: " + ", ".join(missing_scores))
    gates = []

    fold_details: dict[str, Any] = {}
    fold_pass = True
    a_rows = daily_metrics.loc[daily_metrics["quadrant"].eq("A")]
    for metric, baseline in PRIMARY_METRIC_BASELINES.items():
        table = a_rows.loc[a_rows["score"].isin((REGISTERED_CANDIDATE, baseline))].pivot_table(
            index="fold", columns="score", values=metric, aggfunc="mean"
        )
        positive = int((table[REGISTERED_CANDIDATE] > table[baseline]).sum())
        fold_details[metric] = {"baseline": baseline, "positive_folds": positive, "required": 4}
        fold_pass = fold_pass and positive >= 4
    gates.append({"name": "walk_forward_joint_improvement", "passed": fold_pass, "details": fold_details})

    bootstrap_details: dict[str, Any] = {}
    bootstrap_pass = True
    for metric, baseline in PRIMARY_METRIC_BASELINES.items():
        result = circular_block_metric_uplift(
            a_rows,
            candidate=REGISTERED_CANDIDATE,
            baseline=baseline,
            metric=metric,
            iterations=bootstrap_iterations,
        )
        bootstrap_details[metric] = result
        bootstrap_pass = bootstrap_pass and result["ci_low"] > 0
    gates.append({"name": "bootstrap_joint_uplift", "passed": bootstrap_pass, "details": bootstrap_details})

    retention_details: dict[str, Any] = {}
    retention_pass = True
    for metric, baseline in PRIMARY_METRIC_BASELINES.items():
        uplifts = {}
        for quadrant in ("A", "C"):
            current = daily_metrics.loc[
                daily_metrics["quadrant"].eq(quadrant)
                & daily_metrics["score"].isin((REGISTERED_CANDIDATE, baseline))
            ]
            means = current.groupby("score")[metric].mean()
            uplifts[quadrant] = float(means.get(REGISTERED_CANDIDATE, np.nan) - means.get(baseline, np.nan))
        ratio = uplifts["C"] / uplifts["A"] if uplifts["A"] > 0 else None
        passed = ratio is not None and np.isfinite(ratio) and ratio >= 0.80
        retention_details[metric] = {"baseline": baseline, "uplifts": uplifts, "retention": ratio, "passed": passed}
        retention_pass = retention_pass and passed
    gates.append({"name": "unseen_stock_retention", "passed": retention_pass, "details": retention_details})

    concentration_values = {
        quadrant: float(scores.get(REGISTERED_CANDIDATE, 1.0))
        for quadrant, scores in industry_concentration.items()
    }
    concentration_pass = bool(concentration_values) and all(value <= 0.25 for value in concentration_values.values())
    gates.append(
        {
            "name": "industry_concentration",
            "passed": concentration_pass,
            "details": {"maximum_allowed": 0.25, "observed": concentration_values},
        }
    )

    drawdown_details = {}
    drawdown_pass = True
    for quadrant in ("A", "C"):
        current = portfolios.get(quadrant, {})
        candidate = current.get(REGISTERED_CANDIDATE, {}).get("maximum_drawdown")
        baseline = current.get("amount_raw", {}).get("maximum_drawdown")
        passed = candidate is not None and baseline is not None and float(candidate) >= float(baseline)
        drawdown_details[quadrant] = {"candidate": candidate, "amount_raw": baseline, "passed": passed}
        drawdown_pass = drawdown_pass and passed
    gates.append({"name": "maximum_drawdown", "passed": drawdown_pass, "details": drawdown_details})

    state_details: dict[str, Any] = {}
    state_pass = True
    for quadrant in ("A", "C"):
        for state, current in daily_metrics.loc[daily_metrics["quadrant"].eq(quadrant)].groupby(
            "market_state", dropna=False
        ):
            key = f"{quadrant}:{state}"
            state_details[key] = {}
            for metric, baseline in PRIMARY_METRIC_BASELINES.items():
                means = current.loc[current["score"].isin((REGISTERED_CANDIDATE, baseline))].groupby("score")[metric].mean()
                uplift = float(means.get(REGISTERED_CANDIDATE, np.nan) - means.get(baseline, np.nan))
                passed = np.isfinite(uplift) and uplift >= 0
                state_details[key][metric] = {"baseline": baseline, "uplift": uplift, "passed": passed}
                state_pass = state_pass and passed
    gates.append({"name": "market_state_robustness", "passed": state_pass, "details": state_details})

    passed = all(bool(gate["passed"]) for gate in gates)
    return {
        "status": "research_only_passed_development_gate" if passed else "research_only_failed_gate",
        "registered_candidate": REGISTERED_CANDIDATE,
        "passed": passed,
        "production_integration_allowed": False,
        "gates": gates,
    }


def industry_topk_concentration(
    rows: pd.DataFrame,
    score_columns: Iterable[str],
    *,
    top_k: int = 5,
) -> dict[str, dict[str, float]]:
    """Return the maximum daily Top-K industry share by quadrant and score."""
    _require_columns(rows, ("trade_date", "symbol", "industry_l1", "quadrant", *score_columns), "concentration rows")
    output: dict[str, dict[str, float]] = {}
    for quadrant, quadrant_rows in rows.groupby("quadrant", sort=True):
        output[str(quadrant)] = {}
        for score_col in score_columns:
            daily_shares = []
            for _, daily in quadrant_rows.groupby("trade_date", sort=True):
                selected = daily.sort_values(
                    [score_col, "symbol"], ascending=[False, True], kind="stable"
                ).head(top_k)
                shares = selected["industry_l1"].fillna("__UNKNOWN__").value_counts(normalize=True)
                daily_shares.append(float(shares.max()) if not shares.empty else 1.0)
            output[str(quadrant)][score_col.removeprefix("score__")] = max(daily_shares, default=1.0)
    return output


def _cross_sectional_neutral_residual(rows: pd.DataFrame) -> pd.Series:
    result = pd.Series(np.nan, index=rows.index, dtype="float64")
    for _, index in rows.groupby("trade_date", sort=True).groups.items():
        daily = rows.loc[index]
        y = np.log1p(_positive_numeric(daily["amount_cny"]))
        numeric = pd.DataFrame(
            {
                "circ_mv": np.log1p(_positive_numeric(daily["circ_mv"])),
                "close": np.log(_positive_numeric(daily["adjusted_close"])),
                "trailing_amount": np.log1p(_positive_numeric(daily["median_amount_20d"])),
            },
            index=daily.index,
        )
        numeric = numeric.rank(method="average", pct=True).fillna(0.5)
        board = _board_series(daily["symbol"])
        categorical = pd.get_dummies(
            pd.DataFrame(
                {
                    "industry": daily["industry_l1"].fillna("__UNKNOWN__").astype(str),
                    "board": board,
                },
                index=daily.index,
            ),
            drop_first=True,
            dtype="float64",
        )
        design = pd.concat([numeric, categorical], axis=1)
        valid = y.notna()
        if valid.sum() < max(10, design.shape[1] + 2):
            industry_median = y.groupby(daily["industry_l1"].fillna("__UNKNOWN__")).transform("median")
            result.loc[index] = y - industry_median
            continue
        x = np.column_stack([np.ones(int(valid.sum())), design.loc[valid].to_numpy(dtype="float64")])
        target = y.loc[valid].to_numpy(dtype="float64")
        penalty = np.eye(x.shape[1], dtype="float64") * 1e-6
        penalty[0, 0] = 0.0
        coefficients = np.linalg.solve(x.T @ x + penalty, x.T @ target)
        result.loc[y.loc[valid].index] = target - x @ coefficients
    return result.groupby(rows["trade_date"], sort=False).rank(method="average", pct=True)


def _diversified_order_score(
    rows: pd.DataFrame,
    *,
    source_col: str,
    top_k: int,
    industry_max_share: float,
) -> pd.Series:
    ordered = rows.dropna(subset=[source_col]).sort_values(
        [source_col, "symbol"], ascending=[False, True], kind="stable"
    )
    if ordered.empty:
        return pd.Series(np.nan, index=rows.index, dtype="float64")
    max_per_industry = max(1, int(math.floor(max(1, top_k) * industry_max_share)))
    counts: Counter[str] = Counter()
    selected: list[Any] = []
    deferred: list[Any] = []
    for index, row in ordered.iterrows():
        industry = str(row.get("industry_l1") or "__UNKNOWN__")
        if len(selected) < top_k and counts[industry] < max_per_industry:
            selected.append(index)
            counts[industry] += 1
        else:
            deferred.append(index)
    if len(selected) < min(top_k, len(ordered)):
        needed = min(top_k, len(ordered)) - len(selected)
        selected.extend(deferred[:needed])
        deferred = deferred[needed:]
    order = [*selected, *deferred]
    values = pd.Series(np.nan, index=rows.index, dtype="float64")
    values.loc[order] = np.arange(len(order), 0, -1, dtype="float64")
    return values


def _normalise_symbols(values: pd.Series) -> pd.Series:
    return values.astype("string").str.split(".", regex=False).str[0].str.zfill(6)


def _board_series(symbols: pd.Series) -> pd.Series:
    values = _normalise_symbols(symbols)
    return pd.Series(
        np.select(
            [values.str.startswith(("300", "301")), values.str.startswith(("688", "689"))],
            ["CHINEXT", "STAR"],
            default="MAIN",
        ),
        index=symbols.index,
    )


def _positive_numeric(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.where(numeric > 0)


def _lookup_price(lookup: pd.DataFrame, trade_date: str, symbol: str):
    try:
        return lookup.loc[(trade_date, symbol)]
    except KeyError:
        return None


def _require_columns(rows: pd.DataFrame, required: Iterable[str], label: str) -> None:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError(f"{label} must be a pandas DataFrame")
    missing = sorted(set(required) - set(rows.columns))
    if missing:
        raise ValueError(f"{label} missing columns: " + ", ".join(missing))
