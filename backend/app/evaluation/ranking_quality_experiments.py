"""Read-only single-variable ranking experiments over labeled snapshots."""
from __future__ import annotations

from collections import defaultdict
import math
import random
from statistics import mean, median
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


HORIZONS = (5, 10, 20)
PRIMARY_HORIZON = 10
TOP_KS = (3, 5, 10)
SEVERE_LOSS_PCT = -8.0


def run_ranking_experiments(
    rows: Sequence[Dict[str, Any]],
    dd_prob_veto_threshold: Optional[float],
    threshold_source: Optional[str],
    bootstrap_iterations: int = 10_000,
    bootstrap_seed: int = 20260830,
) -> Dict[str, Any]:
    """Compare fixed offline ranking variants without changing production logic."""
    usable = [dict(row) for row in rows if row.get("tradable_label") == "tradable"]
    segments = {
        "all_sources": usable,
        "tushare_only": [row for row in usable if str(row.get("history_source") or "").lower() == "tushare"],
    }
    output = {
        "methodology": {
            "primary_horizon_days": PRIMARY_HORIZON,
            "daily_aggregation": "macro_equal_weight",
            "relevance_definition": "future net return is greater than zero after persisted execution costs",
            "severe_loss_definition": f"future net return <= {SEVERE_LOSS_PCT:.1f}%",
            "bootstrap": {"unit": "trade_date", "iterations": bootstrap_iterations, "seed": bootstrap_seed},
            "experiment_c": {
                "dd_prob_veto_threshold": dd_prob_veto_threshold,
                "threshold_source": threshold_source,
                "rule": "retain current rank_no order, remove dd_prob above the existing threshold, and never refill",
            },
        },
        "segments": {},
    }
    for source_name, source_rows in segments.items():
        output["segments"][source_name] = {
            "all_candidates": _evaluate_segment(source_rows, dd_prob_veto_threshold, threshold_source, bootstrap_iterations, bootstrap_seed),
            "action_buy": _evaluate_segment(_filter_action(source_rows, "buy"), dd_prob_veto_threshold, threshold_source, bootstrap_iterations, bootstrap_seed),
            "action_watch": _evaluate_segment(_filter_action(source_rows, "watch"), dd_prob_veto_threshold, threshold_source, bootstrap_iterations, bootstrap_seed),
        }
    output["shadow_selection"] = _shadow_selection(output["segments"])
    return output


def _evaluate_segment(
    rows: Sequence[Dict[str, Any]],
    dd_prob_veto_threshold: Optional[float],
    threshold_source: Optional[str],
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> Dict[str, Any]:
    candidate_pool = _candidate_pool_metrics(rows)
    baseline = _evaluate_variant(rows, "baseline_current_rank", lambda row: (float(row.get("rank_no") or 999999), str(row.get("symbol") or "")))
    experiments = {
        "baseline_current_rank": baseline,
        "A_dd_prob_ascending": _evaluate_variant(
            rows,
            "A_dd_prob_ascending",
            lambda row: (_number_or_inf(row.get("dd_prob")), str(row.get("symbol") or "")),
        ),
        "B_risk_adjusted_descending": _evaluate_variant(
            rows,
            "B_risk_adjusted_descending",
            lambda row: (-_number_or_neg_inf(row.get("risk_adjusted")), str(row.get("symbol") or "")),
        ),
        "C_dd_prob_veto": _evaluate_veto_variant(rows, dd_prob_veto_threshold, threshold_source),
    }
    for name, experiment in experiments.items():
        if experiment["status"] != "available":
            continue
        experiment["candidate_pool"] = candidate_pool
        experiment["paired_comparison"] = _paired_top5_comparison(
            baseline,
            experiment,
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_seed=bootstrap_seed + sum(ord(char) for char in name),
        )
    return {
        "status": "available" if rows else "unavailable",
        "row_count": len(rows),
        "date_count": len(_by_date(rows)),
        "candidate_pool": candidate_pool,
        "experiments": experiments,
    }


def _evaluate_veto_variant(rows: Sequence[Dict[str, Any]], threshold: Optional[float], source: Optional[str]) -> Dict[str, Any]:
    if threshold is None or not source:
        return {
            "status": "unavailable",
            "reason": "A single existing dd_prob veto threshold is unavailable; no threshold was invented.",
            "coverage": {"input_row_count": len(rows), "accepted_row_count": 0, "coverage": 0.0},
            "metrics": {},
            "selection_by_date": {},
        }
    accepted = [row for row in rows if _as_float(row.get("dd_prob")) is not None and float(row["dd_prob"]) <= threshold]
    result = _evaluate_variant(
        accepted,
        "C_dd_prob_veto",
        lambda row: (float(row.get("rank_no") or 999999), str(row.get("symbol") or "")),
        input_row_count=len(rows),
        input_date_count=len(_by_date(rows)),
    )
    result["threshold"] = threshold
    result["threshold_source"] = source
    result["no_refill"] = True
    return result


def _evaluate_variant(
    rows: Sequence[Dict[str, Any]],
    name: str,
    sort_key: Callable[[Dict[str, Any]], Tuple[float, str]],
    input_row_count: Optional[int] = None,
    input_date_count: Optional[int] = None,
) -> Dict[str, Any]:
    ordered_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for trade_date, items in _by_date(rows).items():
        ordered = sorted((dict(row) for row in items), key=sort_key)
        for index, row in enumerate(ordered, start=1):
            row["evaluated_rank_no"] = index
        ordered_by_date[trade_date] = ordered
    accepted_count = sum(len(items) for items in ordered_by_date.values())
    original_count = accepted_count if input_row_count is None else input_row_count
    result = {
        "status": "available",
        "name": name,
        "coverage": {
            "input_row_count": original_count,
            "accepted_row_count": accepted_count,
            "coverage": _ratio(accepted_count, original_count),
            "input_date_count": len(ordered_by_date) if input_date_count is None else input_date_count,
            "accepted_date_count": len(ordered_by_date),
        },
        "selection_by_date": {trade_date: [str(row.get("symbol") or "") for row in items] for trade_date, items in ordered_by_date.items()},
        "metrics": {str(horizon): _horizon_metrics(ordered_by_date, horizon) for horizon in HORIZONS},
        "_daily_top5_returns": {},
        "_daily_top5_symbols": {},
    }
    primary_daily = _daily_top_k(ordered_by_date, PRIMARY_HORIZON, 5)
    result["_daily_top5_returns"] = {trade_date: value["avg_return"] for trade_date, value in primary_daily.items() if value["avg_return"] is not None}
    result["_daily_top5_symbols"] = {trade_date: value["symbols"] for trade_date, value in primary_daily.items() if value["avg_return"] is not None}
    return result


def _candidate_pool_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(horizon): _pool_horizon_metrics(_by_date(rows), horizon) for horizon in HORIZONS}


def _horizon_metrics(ordered_by_date: Dict[str, List[Dict[str, Any]]], horizon: int) -> Dict[str, Any]:
    return_key = f"future_return_{horizon}d"
    eligible_by_date = {
        trade_date: [row for row in rows if _as_float(row.get(return_key)) is not None]
        for trade_date, rows in ordered_by_date.items()
    }
    eligible_by_date = {trade_date: rows for trade_date, rows in eligible_by_date.items() if rows}
    daily: Dict[str, Dict[str, Any]] = {}
    for trade_date, rows in eligible_by_date.items():
        daily[trade_date] = _daily_metrics(rows, return_key)
    return {
        "horizon_days": horizon,
        "evaluated_date_count": len(daily),
        "labeled_row_count": sum(len(rows) for rows in eligible_by_date.values()),
        "precision_at": {str(k): _mean_or_none([item["top_k"][str(k)]["positive_return_rate"] for item in daily.values()]) for k in TOP_KS},
        "ndcg_at_10": _mean_or_none([item["ndcg_at_10"] for item in daily.values()]),
        "mrr": _mean_or_none([item["mrr"] for item in daily.values()]),
        "top_k": {str(k): _aggregate_top_k(daily.values(), k) for k in TOP_KS},
        "rank_groups": _rank_groups(eligible_by_date, return_key),
        "spearman_rank_vs_future_return": _spearman(
            [float(row["evaluated_rank_no"]) for rows in eligible_by_date.values() for row in rows],
            [float(row[return_key]) for rows in eligible_by_date.values() for row in rows],
        ),
        "monotonic_rank_groups": _monotonic_rank_groups(_rank_groups(eligible_by_date, return_key)),
    }


def _pool_horizon_metrics(by_date: Dict[str, List[Dict[str, Any]]], horizon: int) -> Dict[str, Any]:
    key = f"future_return_{horizon}d"
    per_day = []
    for rows in by_date.values():
        values = [float(row[key]) for row in rows if _as_float(row.get(key)) is not None]
        if values:
            per_day.append(_return_distribution(values))
    return {
        "horizon_days": horizon,
        "evaluated_date_count": len(per_day),
        "avg_return": _mean_or_none([item["avg_return"] for item in per_day]),
        "median_return": _mean_or_none([item["median_return"] for item in per_day]),
        "positive_return_rate": _mean_or_none([item["positive_return_rate"] for item in per_day]),
        "severe_loss_rate": _mean_or_none([item["severe_loss_rate"] for item in per_day]),
        "mean_daily_candidate_count": _mean_or_none([item["candidate_count"] for item in per_day]),
    }


def _daily_metrics(rows: Sequence[Dict[str, Any]], return_key: str) -> Dict[str, Any]:
    values = [float(row[return_key]) for row in rows]
    result = {
        "candidate_pool": _return_distribution(values),
        "top_k": {},
        "ndcg_at_10": _ndcg(rows, return_key, 10),
        "mrr": next((round(1.0 / index, 6) for index, row in enumerate(rows, start=1) if float(row[return_key]) > 0), 0.0),
    }
    for k in TOP_KS:
        top = list(rows[:k])
        result["top_k"][str(k)] = _top_k_distribution(top, return_key, result["candidate_pool"])
    return result


def _daily_top_k(ordered_by_date: Dict[str, List[Dict[str, Any]]], horizon: int, k: int) -> Dict[str, Dict[str, Any]]:
    key = f"future_return_{horizon}d"
    output = {}
    for trade_date, rows in ordered_by_date.items():
        valid = [row for row in rows if _as_float(row.get(key)) is not None]
        top = valid[:k]
        values = [float(row[key]) for row in top]
        output[trade_date] = {"avg_return": _mean_or_none(values), "symbols": [str(row.get("symbol") or "") for row in top]}
    return output


def _top_k_distribution(rows: Sequence[Dict[str, Any]], return_key: str, pool: Dict[str, Any]) -> Dict[str, Any]:
    values = [float(row[return_key]) for row in rows]
    distribution = _return_distribution(values)
    pool_avg = pool.get("avg_return")
    pool_positive = pool.get("positive_return_rate")
    distribution["relative_candidate_pool_excess_return"] = round(distribution["avg_return"] - pool_avg, 6) if distribution["avg_return"] is not None and pool_avg is not None else None
    distribution["lift_at_k"] = round(distribution["positive_return_rate"] / pool_positive, 6) if pool_positive and distribution["positive_return_rate"] is not None else None
    return distribution


def _aggregate_top_k(daily: Iterable[Dict[str, Any]], k: int) -> Dict[str, Any]:
    values = [item["top_k"][str(k)] for item in daily]
    keys = (
        "candidate_count",
        "avg_return",
        "median_return",
        "positive_return_rate",
        "severe_loss_rate",
        "relative_candidate_pool_excess_return",
        "lift_at_k",
    )
    output = {key: _mean_or_none([item.get(key) for item in values]) for key in keys}
    output["mean_daily_candidate_count"] = output["candidate_count"]
    return output


def _return_distribution(values: Sequence[float]) -> Dict[str, Any]:
    return {
        "candidate_count": len(values),
        "avg_return": _mean_or_none(values),
        "median_return": _median_or_none(values),
        "positive_return_rate": _ratio(sum(value > 0 for value in values), len(values)),
        "severe_loss_rate": _ratio(sum(value <= SEVERE_LOSS_PCT for value in values), len(values)),
    }


def _rank_groups(by_date: Dict[str, List[Dict[str, Any]]], return_key: str) -> List[Dict[str, Any]]:
    bands = (("1-5", 1, 5), ("6-10", 6, 10), ("11-20", 11, 20), ("21+", 21, None))
    result = []
    for label, lower, upper in bands:
        values = [
            float(row[return_key])
            for rows in by_date.values()
            for row in rows
            if lower <= int(row["evaluated_rank_no"]) and (upper is None or int(row["evaluated_rank_no"]) <= upper)
        ]
        output = _return_distribution(values)
        output["rank_group"] = label
        result.append(output)
    return result


def _monotonic_rank_groups(groups: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    populated = [item["avg_return"] for item in groups if item.get("candidate_count") and item.get("avg_return") is not None]
    if len(populated) < 2:
        return {"status": "insufficient_groups", "is_monotonic": None}
    return {"status": "evaluated", "is_monotonic": all(left >= right for left, right in zip(populated, populated[1:]))}


def _paired_top5_comparison(
    baseline: Dict[str, Any],
    experiment: Dict[str, Any],
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> Dict[str, Any]:
    base_daily = baseline.get("_daily_top5_returns") or {}
    trial_daily = experiment.get("_daily_top5_returns") or {}
    dates = sorted(set(base_daily) & set(trial_daily))
    deltas = [float(trial_daily[trade_date]) - float(base_daily[trade_date]) for trade_date in dates]
    improved_symbols = {
        symbol
        for trade_date, delta in zip(dates, deltas)
        if delta > 0
        for symbol in (experiment.get("_daily_top5_symbols") or {}).get(trade_date, [])
    }
    return {
        "matched_date_count": len(dates),
        "baseline_only_date_count": len(set(base_daily) - set(trial_daily)),
        "experiment_only_date_count": len(set(trial_daily) - set(base_daily)),
        "mean_daily_top5_return_difference": _mean_or_none(deltas),
        "win_date_count": sum(delta > 0 for delta in deltas),
        "loss_date_count": sum(delta < 0 for delta in deltas),
        "tie_date_count": sum(delta == 0 for delta in deltas),
        "bootstrap_95pct_ci": _bootstrap_ci(deltas, bootstrap_iterations, bootstrap_seed),
        "improvement_unique_symbol_count": len(improved_symbols),
        "improvement_dates": [trade_date for trade_date, delta in zip(dates, deltas) if delta > 0],
    }


def _bootstrap_ci(values: Sequence[float], iterations: int, seed: int) -> Dict[str, Optional[float]]:
    if not values or iterations <= 0:
        return {"lower": None, "upper": None}
    generator = random.Random(seed)
    count = len(values)
    samples = sorted(mean(values[generator.randrange(count)] for _ in range(count)) for _ in range(iterations))
    return {"lower": round(samples[int((len(samples) - 1) * 0.025)], 6), "upper": round(samples[int((len(samples) - 1) * 0.975)], 6)}


def _shadow_selection(segments: Dict[str, Any]) -> Dict[str, Any]:
    all_source = ((segments.get("all_sources") or {}).get("all_candidates") or {}).get("experiments") or {}
    tushare = ((segments.get("tushare_only") or {}).get("all_candidates") or {}).get("experiments") or {}
    baseline = all_source.get("baseline_current_rank") or {}
    baseline_tushare = tushare.get("baseline_current_rank") or {}
    candidates = {}
    for name in ("A_dd_prob_ascending", "B_risk_adjusted_descending", "C_dd_prob_veto"):
        experiment = all_source.get(name) or {}
        tushare_experiment = tushare.get(name) or {}
        if experiment.get("status") != "available" or tushare_experiment.get("status") != "available":
            candidates[name] = {"status": "unavailable", "reason": "Required all-sources or TuShare-only comparison is unavailable."}
            continue
        base_metrics = _primary_metrics(baseline)
        trial_metrics = _primary_metrics(experiment)
        base_tushare = _primary_metrics(baseline_tushare)
        trial_tushare = _primary_metrics(tushare_experiment)
        paired = experiment.get("paired_comparison") or {}
        criteria = {
            "top5_median_10d_improved": _greater(trial_metrics.get("top5_median"), base_metrics.get("top5_median")),
            "top5_severe_loss_not_higher": _not_greater(trial_metrics.get("top5_severe_loss"), base_metrics.get("top5_severe_loss")),
            "ndcg_at_10_improved": _greater(trial_metrics.get("ndcg_at_10"), base_metrics.get("ndcg_at_10")),
            "top5_excess_return_improved": _greater(trial_metrics.get("top5_excess"), base_metrics.get("top5_excess")),
            "tushare_only_direction_consistent": _greater(trial_tushare.get("top5_median"), base_tushare.get("top5_median")),
            "not_single_stock_or_date": len(paired.get("improvement_dates") or []) >= 2 and int(paired.get("improvement_unique_symbol_count") or 0) >= 2,
        }
        candidates[name] = {"status": "shadow_candidate" if all(criteria.values()) else "rejected", "criteria": criteria, "all_sources": trial_metrics, "tushare_only": trial_tushare}
    selected = [name for name, value in candidates.items() if value["status"] == "shadow_candidate"]
    return {"status": "no_shadow_candidate" if not selected else "shadow_candidate", "selected": selected, "candidates": candidates}


def _primary_metrics(experiment: Dict[str, Any]) -> Dict[str, Optional[float]]:
    metrics = (experiment.get("metrics") or {}).get(str(PRIMARY_HORIZON)) or {}
    top5 = (metrics.get("top_k") or {}).get("5") or {}
    return {
        "top5_median": top5.get("median_return"),
        "top5_severe_loss": top5.get("severe_loss_rate"),
        "top5_excess": top5.get("relative_candidate_pool_excess_return"),
        "ndcg_at_10": metrics.get("ndcg_at_10"),
    }


def _filter_action(rows: Sequence[Dict[str, Any]], action: str) -> List[Dict[str, Any]]:
    return [row for row in rows if str(row.get("action") or "").lower() == action]


def _by_date(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("trade_date") or "unknown")].append(row)
    return dict(sorted(grouped.items()))


def _ndcg(rows: Sequence[Dict[str, Any]], return_key: str, k: int) -> float:
    gains = [max(0.0, float(row[return_key])) for row in rows[:k]]
    ideal = sorted((max(0.0, float(row[return_key])) for row in rows), reverse=True)[:k]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    return round(dcg / idcg, 6) if idcg else 0.0


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return round(_pearson(_ranks(xs), _ranks(ys)), 6)


def _ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    result = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[start][0]:
            end += 1
        rank = (start + end + 2) / 2.0
        for _, index in ordered[start : end + 1]:
            result[index] = rank
        start = end + 1
    return result


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    x_mean, y_mean = mean(xs), mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def _as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number_or_inf(value: Any) -> float:
    number = _as_float(value)
    return number if number is not None else float("inf")


def _number_or_neg_inf(value: Any) -> float:
    number = _as_float(value)
    return number if number is not None else float("-inf")


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _mean_or_none(values: Sequence[Optional[float]]) -> Optional[float]:
    available = [float(value) for value in values if value is not None]
    return round(mean(available), 6) if available else None


def _median_or_none(values: Sequence[float]) -> Optional[float]:
    return round(median(values), 6) if values else None


def _greater(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and float(left) > float(right)


def _not_greater(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and float(left) <= float(right)
