"""Read-only ranking-quality diagnostics for persisted pick snapshots.

This module only consumes already-persisted candidate snapshots and explicitly
requested OHLCV data.  It does not import CoachService or mutate ranking,
strategy, model, or persistence state.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
import math
from statistics import mean, median
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


HORIZONS = (3, 5, 10, 20)
PRIMARY_HORIZON = 10
FACTOR_FIELDS = (
    "raw_total",
    "total",
    "up_prob",
    "dd_prob",
    "expected_edge_pct",
    "profit_factor_proxy",
    "trend",
    "money_flow",
    "turnover_liquidity",
    "quality",
    "risk_adjusted",
    "news",
)
DEFAULT_EXECUTION_CONFIG = {
    "commission": 0.0003,
    "slippage": 0.001,
    "take_profit_pct": 15.0,
    "stop_loss_pct": 8.0,
}


HistoryFetcher = Callable[[str, str, str], Any]


class SnapshotIntegrityError(ValueError):
    """Persisted snapshot data is ambiguous or violates evaluation invariants."""

    def __init__(self, message: str, diagnostics: Dict[str, Any]):
        super().__init__(message)
        self.diagnostics = diagnostics


class DuplicateSnapshotKeyError(SnapshotIntegrityError):
    """Persisted snapshot keys are ambiguous and must not be deduplicated."""


def quarantine_ambiguous_dates(rows: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Explicit opt-in whole-date exclusion, independent of future outcomes."""
    rejected_dates = []
    kept, rejected = [], []
    for trade_date, items in _by_date(rows).items():
        try:
            validate_snapshot_identity(items)
        except DuplicateSnapshotKeyError as exc:
            rejected.extend(items)
            rejected_dates.append({"trade_date": trade_date, "reason": "ambiguous_snapshot_keys",
                                   "candidate_count": len(items), "diagnostics": exc.diagnostics})
        else:
            kept.extend(items)
    raw = json.dumps(list(rows), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return kept, rejected, {"policy": "whole_date_no_rank_repair", "raw_candidate_count": len(rows),
                            "raw_date_count": len(_by_date(rows)), "excluded_dates": rejected_dates,
                            "original_sha256": hashlib.sha256(raw.encode()).hexdigest()}


def label_snapshot_rows(
    snapshots: Sequence[Dict[str, Any]],
    history_fetcher: HistoryFetcher,
    execution_config: Optional[Dict[str, Any]] = None,
    max_calendar_days: int = 60,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Attach point-in-time forward labels without using a trade calendar.

    The first row whose date is strictly after the candidate snapshot date is
    the T+1 entry bar.  Incomplete horizons remain ``None`` instead of being
    coerced to zero, so rank metrics cannot accidentally credit missing data.
    """
    config = _execution_config(execution_config)
    labeled: List[Dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    missing_reasons: Counter[str] = Counter()

    for snapshot in snapshots:
        row = _flatten_snapshot(snapshot)
        trade_date = _iso_date(row.get("trade_date"))
        symbol = str(row.get("symbol") or "").strip()
        if not trade_date or not symbol:
            row.update(_empty_label("invalid_snapshot_identity"))
            missing_reasons[row["label_missing_reason"]] += 1
            labeled.append(row)
            continue

        end_date = (datetime.strptime(trade_date, "%Y-%m-%d").date() + timedelta(days=max_calendar_days)).isoformat()
        try:
            fetched = history_fetcher(symbol, trade_date, end_date)
            history, source, fetch_reason = _unpack_history_fetch(fetched)
        except Exception as exc:  # defensive boundary around external data
            history, source, fetch_reason = pd.DataFrame(), "fetch_error", type(exc).__name__

        source_counts[str(source or "unknown")] += 1
        future = _normalize_history(history)
        row["snapshot_has_same_date_bar"] = bool((future["date"] == trade_date).any()) if not future.empty and not fetch_reason else None
        future = future[future["date"] > trade_date].reset_index(drop=True) if not future.empty else future
        if future.empty:
            reason = fetch_reason or "no_post_snapshot_bar"
            row.update(_empty_label(reason, source=source))
            missing_reasons[reason] += 1
            labeled.append(row)
            continue

        entry = future.iloc[0]
        entry_price = _number(entry.get("open"))
        if entry_price is None or entry_price <= 0:
            row.update(_empty_label("invalid_entry_open", source=source))
            missing_reasons["invalid_entry_open"] += 1
            labeled.append(row)
            continue

        valid_ohlcv = all((_number(entry.get(column)) or 0) > 0 for column in ("high", "low", "close", "volume"))
        if not valid_ohlcv:
            row.update(_empty_label("invalid_entry_bar", source=source))
            missing_reasons["invalid_entry_bar"] += 1
            labeled.append(row)
            continue

        if entry["high"] == entry["low"]:
            row.update(_empty_label("one_price_entry_execution_unknown", source=source))
            missing_reasons[row["label_missing_reason"]] += 1
            labeled.append(row)
            continue
        adjusted = future.copy()
        if "adj_factor" in adjusted.columns:
            factors = pd.to_numeric(adjusted["adj_factor"], errors="coerce")
            if factors.isna().any() or (factors <= 0).any():
                row.update(_empty_label("adjustment_factor_missing", source=source))
                missing_reasons[row["label_missing_reason"]] += 1
                labeled.append(row)
                continue
            for field in ("open", "high", "low", "close"):
                adjusted[field] = adjusted[field] * factors / factors.iloc[0]
            row["adjustment_basis"] = "adj_factor_entry_anchor"
        else:
            row["adjustment_basis"] = "caller_supplied_prices"
        label = _label_future_path(adjusted, entry_price, config)
        label["execution_assumption"] = "next_available_bar_open_proxy_not_verified_fill"
        label["entry_date"] = str(entry["date"])
        label["entry_price"] = round(entry_price, 6)
        label["history_source"] = source
        label["label_missing_reason"] = None
        row.update(label)
        labeled.append(row)

    coverage = {
        "snapshot_row_count": len(snapshots),
        "labeled_row_count": sum(1 for row in labeled if row.get("label_missing_reason") is None),
        "label_missing_row_count": sum(1 for row in labeled if row.get("label_missing_reason") is not None),
        "label_missing_rate": _ratio(sum(1 for row in labeled if row.get("label_missing_reason") is not None), len(labeled)),
        "source_counts": dict(sorted(source_counts.items())),
        "missing_reason_counts": dict(sorted(missing_reasons.items())),
    }
    return labeled, coverage


def validate_labeled_snapshot_sample(rows: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Reject ambiguous snapshots and exclude dates absent from all candidate bars.

    Snapshot dates are validated only against each candidate's persisted-history
    response.  This deliberately avoids calendar or weekday inference.
    """
    normalized = _normalize_snapshot_identity_rows(rows)
    diagnostics = validate_snapshot_identity(normalized)

    by_date = _by_date(normalized)
    diagnostics.update({"daily_candidate_set_hashes": [], "adjacent_date_candidate_set_comparisons": [], "excluded_dates": []})

    valid_rows: List[Dict[str, Any]] = []
    previous_date: Optional[str] = None
    previous_symbols: Optional[List[str]] = None
    for trade_date, items in by_date.items():
        symbols = sorted(row["symbol"] for row in items)
        candidate_set_hash = _candidate_set_hash(symbols)
        same_as_previous = previous_symbols == symbols if previous_symbols is not None else False
        diagnostics["daily_candidate_set_hashes"].append(
            {"trade_date": trade_date, "candidate_count": len(items), "candidate_set_hash": candidate_set_hash}
        )
        if previous_date is not None:
            diagnostics["adjacent_date_candidate_set_comparisons"].append(
                {
                    "previous_trade_date": previous_date,
                    "trade_date": trade_date,
                    "same_candidate_set": same_as_previous,
                }
            )

        has_same_day_bar = [row.get("snapshot_has_same_date_bar") for row in items]
        if not any(has_same_day_bar):
            diagnostics["excluded_dates"].append(
                {
                    "trade_date": trade_date,
                    "reason": "non_trading_snapshot" if all(value is False for value in has_same_day_bar) else "history_unavailable",
                    "candidate_count": len(items),
                    "candidate_set_hash": candidate_set_hash,
                    "previous_trade_date": previous_date,
                    "same_candidate_set_as_previous_date": same_as_previous,
                }
            )
        else:
            valid_rows.extend(items)
        previous_date = trade_date
        previous_symbols = symbols

    valid_dates = sorted({row["trade_date"] for row in valid_rows})
    rank_1_5_count = sum(1 for row in valid_rows if 1 <= row["rank_no"] <= 5)
    rank_1_10_count = sum(1 for row in valid_rows if 1 <= row["rank_no"] <= 10)
    rank_band_checks = {
        "rank_1_5_count": rank_1_5_count,
        "rank_1_5_limit": len(valid_dates) * 5,
        "rank_1_10_count": rank_1_10_count,
        "rank_1_10_limit": len(valid_dates) * 10,
        "status": "passed" if rank_1_5_count <= len(valid_dates) * 5 and rank_1_10_count <= len(valid_dates) * 10 else "failed",
    }
    diagnostics.update(
        {
            "valid_trading_snapshot_date_count": len(valid_dates),
            "valid_trading_snapshot_dates": valid_dates,
            "final_candidate_count": len(valid_rows),
            "unique_symbol_count": len({row["symbol"] for row in valid_rows}),
            "rank_band_assertions": rank_band_checks,
        }
    )
    if rank_band_checks["status"] != "passed":
        raise SnapshotIntegrityError("rank-band count invariant failed; evaluation stopped", diagnostics)
    return valid_rows, diagnostics


def validate_snapshot_identity(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Stop before history access when persisted snapshot keys are ambiguous."""
    normalized = _normalize_snapshot_identity_rows(rows)
    duplicate_checks = {
        "trade_date_symbol": _duplicate_key_check(normalized, ("trade_date", "symbol")),
        "trade_date_rank_no": _duplicate_key_check(normalized, ("trade_date", "rank_no")),
    }
    diagnostics = {
        "raw_date_count": len(_by_date(normalized)),
        "raw_candidate_count": len(normalized),
        "duplicate_key_checks": duplicate_checks,
    }
    if any(check["status"] == "failed" for check in duplicate_checks.values()):
        raise DuplicateSnapshotKeyError("duplicate persisted snapshot keys; evaluation stopped without deduplication", diagnostics)
    return diagnostics


def build_ranking_quality_diagnosis(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a read-only diagnosis from labeled snapshot rows."""
    normalized = [_normalize_labeled_row(row) for row in rows]
    return {
        "methodology": {
            "primary_horizon_days": PRIMARY_HORIZON,
            "relevance_definition": "tradable candidate with future_return_10d > 0 after configured entry/exit costs",
            "rank_direction": "smaller rank_no is better; a negative Spearman(rank_no, future return) is favorable",
            "market_state_note": "market-state analysis requires a persisted market_state_tag on candidate snapshots",
        },
        "ranking_quality": _ranking_quality(normalized),
        "error_samples": _error_samples(normalized),
        "factor_analysis": _factor_analysis(normalized),
        "counterfactual": _counterfactual(normalized),
        "funnel_assessment": _funnel_assessment(normalized),
    }


def _flatten_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(snapshot or {})
    breakdown = dict(item.get("score_breakdown") or {})
    decision = dict(item.get("decision") or {})
    model_probability = dict(item.get("model_probability") or {})
    market_state = dict(item.get("market_state") or {})
    return {
        "trade_date": _iso_date(item.get("trade_date")),
        "symbol": str(item.get("symbol") or "").strip(),
        "name": item.get("name") or item.get("symbol") or "",
        "pick_id": item.get("pick_id"),
        "rank_no": _int(item.get("rank_no"), 999999),
        "action": item.get("action"),
        "decision_executable": bool(decision.get("executable")),
        "decision_grade": decision.get("grade"),
        "decision_mode": decision.get("mode"),
        "market_state_tag": market_state.get("state_tag") or (item.get("evidence_summary") or {}).get("state_tag") or "unknown",
        "raw_total": _number(breakdown.get("raw_total")),
        "total": _number(breakdown.get("total")),
        "up_prob": _number(item.get("up_prob")),
        "dd_prob": _number(item.get("dd_prob")),
        "expected_edge_pct": _number(item.get("expected_edge_pct")),
        "profit_factor_proxy": _number(item.get("profit_factor_proxy")),
        "trend": _number(breakdown.get("trend")),
        "money_flow": _number(breakdown.get("money_flow")),
        "turnover_liquidity": _number(breakdown.get("turnover_liquidity")),
        "quality": _number(breakdown.get("quality")),
        "risk_adjusted": _number(breakdown.get("risk_adjusted")),
        "news": _number(breakdown.get("news")),
        "model_probability": model_probability or None,
        "model_final_score": _number(model_probability.get("final_score")),
        "ml_enrichment": item.get("ml_enrichment"),
    }


def _unpack_history_fetch(value: Any) -> Tuple[pd.DataFrame, str, Optional[str]]:
    if isinstance(value, tuple):
        history = value[0] if len(value) > 0 else pd.DataFrame()
        source = str(value[1] if len(value) > 1 else "unknown")
        reason = str(value[2]) if len(value) > 2 and value[2] else None
        return history if isinstance(history, pd.DataFrame) else pd.DataFrame(history), source, reason
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame(value), "unknown", None


def _normalize_history(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount"])
    rows = history.copy()
    if "date" not in rows.columns:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount"])
    rows["date"] = rows["date"].map(_iso_date)
    rows = rows.dropna(subset=["date"])
    for field in ("open", "high", "low", "close", "volume", "amount"):
        rows[field] = pd.to_numeric(rows[field], errors="coerce") if field in rows.columns else 0.0
    return rows.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def _label_future_path(rows: pd.DataFrame, entry_price: float, config: Dict[str, float]) -> Dict[str, Any]:
    entry_cost_price = entry_price * (1 + config["commission"] + config["slippage"])
    available = rows.head(max(HORIZONS)).reset_index(drop=True)
    result: Dict[str, Any] = {
        "tradable_label": "tradable",
        "incomplete_horizons": [],
        "max_favorable_excursion": _return_pct(_number(available["high"].max()), entry_price),
        "max_adverse_excursion": _return_pct(_number(available["low"].min()), entry_price),
    }
    result.update(_first_hit(available, entry_price, config))
    for horizon in HORIZONS:
        key = f"future_return_{horizon}d"
        if len(rows) < horizon:
            result[key] = None
            result["incomplete_horizons"].append(horizon)
            continue
        exit_close = _number(rows.iloc[horizon - 1].get("close"))
        if exit_close is None or exit_close <= 0:
            result[key] = None
            result["incomplete_horizons"].append(horizon)
            continue
        exit_net = exit_close * (1 - config["commission"] - config["slippage"])
        result[key] = round((exit_net / entry_cost_price - 1) * 100, 6)
    return result


def _first_hit(rows: pd.DataFrame, entry_price: float, config: Dict[str, float]) -> Dict[str, Any]:
    take_price = entry_price * (1 + config["take_profit_pct"] / 100)
    stop_price = entry_price * (1 - config["stop_loss_pct"] / 100)
    for _, bar in rows.iterrows():
        hit_take = (_number(bar.get("high")) or 0) >= take_price
        hit_stop = (_number(bar.get("low")) or 0) <= stop_price
        if hit_take and hit_stop:
            return {
                "first_hit_take_profit": False,
                "first_hit_stop_loss": True,
                "first_hit_path": "both_same_day_stop_loss_first",
                "first_hit_date": str(bar.get("date")),
            }
        if hit_take:
            return {"first_hit_take_profit": True, "first_hit_stop_loss": False, "first_hit_path": "take_profit_first", "first_hit_date": str(bar.get("date"))}
        if hit_stop:
            return {"first_hit_take_profit": False, "first_hit_stop_loss": True, "first_hit_path": "stop_loss_first", "first_hit_date": str(bar.get("date"))}
    return {"first_hit_take_profit": False, "first_hit_stop_loss": False, "first_hit_path": "not_hit", "first_hit_date": None}


def _empty_label(reason: str, source: Optional[str] = None) -> Dict[str, Any]:
    values = {
        "entry_date": None,
        "entry_price": None,
        "tradable_label": "untradable",
        "label_missing_reason": reason,
        "history_source": source,
        "max_favorable_excursion": None,
        "max_adverse_excursion": None,
        "first_hit_take_profit": None,
        "first_hit_stop_loss": None,
        "first_hit_path": None,
        "first_hit_date": None,
        "incomplete_horizons": list(HORIZONS),
    }
    values.update({f"future_return_{horizon}d": None for horizon in HORIZONS})
    return values


def _ranking_quality(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return_key = f"future_return_{PRIMARY_HORIZON}d"
    complete_dates = {trade_date for trade_date, items in _by_date(rows).items()
                      if len(_usable_rows(items, return_key)) == len(items)}
    usable = [row for row in rows if row["trade_date"] in complete_dates]
    per_date = [_daily_rank_metrics(items, return_key) for _, items in _by_date(usable).items()]
    return {
        "horizon_days": PRIMARY_HORIZON,
        "labeled_tradable_rows": len(usable),
        "evaluated_dates": len(per_date),
        "incomplete_date_count": len(_by_date(rows)) - len(complete_dates),
        "missing_policy": "whole_daily_pool_complete_no_refill",
        "macro_daily_metrics": _average_dicts(per_date),
        "rank_groups": _rank_groups(usable, return_key),
        "spearman_rank_vs_future_return": _spearman([float(row["rank_no"]) for row in usable], [float(row[return_key]) for row in usable]),
        "monotonic_rank_groups": _is_monotonic(_rank_groups(usable, return_key)),
    }


def _daily_rank_metrics(rows: List[Dict[str, Any]], return_key: str) -> Dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["rank_no"], row["symbol"]))
    relevant = [row for row in ordered if float(row[return_key]) > 0]
    metric: Dict[str, Any] = {"candidate_count": len(ordered), "positive_return_count": len(relevant)}
    for k in (3, 5, 10):
        top = ordered[:k]
        returns = [float(row[return_key]) for row in top]
        metric[f"precision_at_{k}"] = _ratio(sum(value > 0 for value in returns), len(returns))
        metric[f"top_{k}_avg_return"] = _mean_or_none(returns)
        metric[f"top_{k}_median_return"] = _median_or_none(returns)
        metric[f"top_{k}_positive_return_rate"] = _ratio(sum(value > 0 for value in returns), len(returns))
        metric[f"top_{k}_severe_loss_rate"] = _ratio(sum(value <= -8.0 for value in returns), len(returns))
    metric["ndcg_at_10"] = _ndcg(ordered, return_key, 10)
    metric["mrr"] = next((round(1 / (index + 1), 6) for index, row in enumerate(ordered) if float(row[return_key]) > 0), 0.0)
    return metric


def _rank_groups(rows: List[Dict[str, Any]], return_key: str) -> List[Dict[str, Any]]:
    groups = (("1-5", 1, 5), ("6-10", 6, 10), ("11-20", 11, 20), ("21+", 21, None))
    result = []
    for label, low, high in groups:
        group = [row for row in rows if row["rank_no"] >= low and (high is None or row["rank_no"] <= high)]
        values = [float(row[return_key]) for row in group]
        result.append({
            "rank_group": label,
            "row_count": len(group),
            "avg_return": _mean_or_none(values),
            "median_return": _median_or_none(values),
            "positive_return_rate": _ratio(sum(value > 0 for value in values), len(values)),
            "severe_loss_rate": _ratio(sum(value <= -8.0 for value in values), len(values)),
        })
    return result


def _is_monotonic(groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    populated = [group for group in groups if group["row_count"] and group["avg_return"] is not None]
    if len(populated) < 2:
        return {"status": "insufficient_groups", "is_monotonic": None}
    values = [float(group["avg_return"]) for group in populated]
    return {"status": "evaluated", "is_monotonic": all(left >= right for left, right in zip(values, values[1:]))}


def _error_samples(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    key = f"future_return_{PRIMARY_HORIZON}d"
    usable = _usable_rows(rows, key)
    sample = lambda values: [_sample_row(row) for row in values[:20]]
    top5 = sorted((row for row in usable if row["rank_no"] <= 5), key=lambda row: float(row[key]))
    late = sorted((row for row in usable if row["rank_no"] > 10), key=lambda row: float(row[key]), reverse=True)
    not_buy = sorted((row for row in usable if str(row.get("action") or "") != "buy" and float(row[key]) > 0), key=lambda row: float(row[key]), reverse=True)
    gate = sorted((row for row in usable if not bool(row.get("decision_executable")) and float(row[key]) > 0), key=lambda row: float(row[key]), reverse=True)
    return {
        "top5_worst_10d": sample(top5),
        "rank_gt_10_best_10d": sample(late),
        "in_pool_not_buy_but_positive_10d": sample(not_buy),
        "buy_gate_excluded_but_positive_10d": sample(gate),
    }


def _factor_analysis(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for factor in FACTOR_FIELDS:
        factor_report: Dict[str, Any] = {"missing_rate": _ratio(sum(row.get(factor) is None for row in rows), len(rows)), "horizons": {}}
        for horizon in (5, 10, 20):
            return_key = f"future_return_{horizon}d"
            usable = [row for row in _usable_rows(rows, return_key) if row.get(factor) is not None]
            values = [float(row[factor]) for row in usable]
            returns = [float(row[return_key]) for row in usable]
            factor_report["horizons"][str(horizon)] = {
                "row_count": len(usable),
                "spearman": _spearman(values, returns),
                "quantile_returns": _quantile_returns(usable, factor, return_key),
                "market_state_direction": _market_state_direction(usable, factor, return_key),
            }
        output[factor] = factor_report
    return output


def _counterfactual(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    current = _strategy_metrics(rows, lambda row: row["rank_no"])
    raw_available = [row for row in rows if row.get("raw_total") is not None]
    probability_available = [row for row in rows if row.get("up_prob") is not None and row.get("dd_prob") is not None]
    no_model_missing = ["pre_model_rule_score", "model_adjustment", "per_candidate_ml_weight", "ml_enrichment"]
    return {
        "current_final_rank": {"status": "available", "metrics": current},
        "no_model_rule_rank": {
            "status": "unavailable",
            "reason": "Persisted snapshots do not retain a verifiable pre-model rule score or model adjustment; raw_total cannot be asserted to exclude weak-model influence.",
            "missing_fields": no_model_missing,
            "model_probability_coverage": _ratio(sum(row.get("model_probability") is not None for row in rows), len(rows)),
        },
        "raw_total_proxy_rank": {
            "status": "proxy_only_not_no_model_counterfactual" if len(raw_available) == len(rows) else "unavailable",
            "row_count": len(raw_available),
            "metrics": _strategy_metrics(rows, lambda row: -float(row["raw_total"])) if len(raw_available) == len(rows) else {},
        },
        "up_minus_dd_rank": {
            "status": "available" if rows and len(probability_available) == len(rows) else "unavailable",
            "row_count": len(probability_available),
            "metrics": _strategy_metrics(rows, lambda row: -(float(row["up_prob"]) - float(row["dd_prob"]))) if len(probability_available) == len(rows) else {},
        },
        "minimum_shadow_capture": [
            "persisted pre_model_rule_score and its rank before any ML-related adjustment",
            "per-candidate model_score, adjustment weight, and resulting delta",
            "model version/readiness plus explicit enrichment payload for every candidate",
        ],
    }


def _strategy_metrics(rows: List[Dict[str, Any]], key_fn: Callable[[Dict[str, Any]], Any]) -> Dict[str, Any]:
    reranked: List[Dict[str, Any]] = []
    for _, items in _by_date(rows).items():
        ordered = sorted(items, key=lambda row: (key_fn(row), row["symbol"]))
        for rank, row in enumerate(ordered, start=1):
            copied = dict(row)
            copied["rank_no"] = rank
            reranked.append(copied)
    return _ranking_quality(reranked)


def _funnel_assessment(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    key = f"future_return_{PRIMARY_HORIZON}d"
    usable = _usable_rows(rows, key)
    early_losers = sum(1 for row in usable if row["rank_no"] <= 5 and float(row[key]) <= -8.0)
    late_winners = sum(1 for row in usable if row["rank_no"] > 10 and float(row[key]) > 0)
    gate_winners = sum(1 for row in usable if not row.get("decision_executable") and float(row[key]) > 0)
    return {
        "recall": {"finding": "暂无证据", "evidence": "pick_snapshots only retain final candidates, not the full eligible universe or rejected recall pool."},
        "ranking": {
            "finding": "主要问题" if early_losers or late_winners else "暂无证据",
            "evidence": f"{early_losers} Top5 severe losers and {late_winners} rank>10 positive 10d candidates among {len(usable)} labeled tradable rows.",
        },
        "buy_gate": {
            "finding": "次要问题" if gate_winners else "暂无证据",
            "evidence": f"{gate_winners} decision.executable=false candidates had positive 10d returns; this is conditional on the persisted final pool only.",
        },
        "exit_holding_period": {"finding": "暂无证据", "evidence": "Fixed 3/5/10/20-day labels and TP/SL first-hit paths do not reproduce actual exit execution or a holding-rule counterfactual."},
        "data_sufficiency": {"finding": "次要问题" if len(usable) < 500 else "暂无证据", "evidence": f"Only {len(usable)} labeled tradable rows are available; market_state_tag is persisted as unknown unless supplied in snapshot JSON."},
    }


def _usable_rows(rows: Iterable[Dict[str, Any]], return_key: str) -> List[Dict[str, Any]]:
    return [row for row in rows if row.get("tradable_label") == "tradable" and row.get(return_key) is not None]


def _normalize_labeled_row(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    result["rank_no"] = _int(result.get("rank_no"), 999999)
    result["market_state_tag"] = str(result.get("market_state_tag") or "unknown")
    result["symbol"] = str(result.get("symbol") or "")
    for field in FACTOR_FIELDS:
        result[field] = _number(result.get(field))
    for horizon in HORIZONS:
        result[f"future_return_{horizon}d"] = _number(result.get(f"future_return_{horizon}d"))
    return result


def _quantile_returns(rows: List[Dict[str, Any]], factor: str, return_key: str) -> List[Dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (float(row[factor]), row["symbol"]))
    if not ordered:
        return []
    bucket_count = min(5, len(ordered))
    buckets: List[List[Dict[str, Any]]] = [[] for _ in range(bucket_count)]
    for index, row in enumerate(ordered):
        buckets[min(bucket_count - 1, index * bucket_count // len(ordered))].append(row)
    return [
        {
            "quantile": index + 1,
            "row_count": len(bucket),
            "factor_min": round(float(bucket[0][factor]), 6),
            "factor_max": round(float(bucket[-1][factor]), 6),
            "avg_return": _mean_or_none([float(row[return_key]) for row in bucket]),
        }
        for index, bucket in enumerate(buckets)
        if bucket
    ]


def _market_state_direction(rows: List[Dict[str, Any]], factor: str, return_key: str) -> Dict[str, Any]:
    grouped = _by_key(rows, "market_state_tag")
    usable = {state: values for state, values in grouped.items() if len(values) >= 3}
    if len(usable) < 2:
        return {"status": "insufficient_market_state_variation", "states": {state: len(values) for state, values in grouped.items()}}
    return {
        "status": "evaluated",
        "states": {
            state: {"row_count": len(values), "spearman": _spearman([float(row[factor]) for row in values], [float(row[return_key]) for row in values])}
            for state, values in sorted(usable.items())
        },
    }


def _sample_row(row: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("trade_date", "symbol", "name", "rank_no", "action", "decision_executable", "future_return_10d", "max_favorable_excursion", "max_adverse_excursion", "first_hit_path", "raw_total", "total", "up_prob", "dd_prob")
    return {key: row.get(key) for key in keys}


def _normalize_snapshot_identity_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for source in rows:
        row = dict(source)
        row["trade_date"] = _iso_date(row.get("trade_date"))
        row["symbol"] = str(row.get("symbol") or "").strip()
        row["rank_no"] = _int(row.get("rank_no"), 999999)
        normalized.append(row)
    return normalized


def _duplicate_key_check(rows: Sequence[Dict[str, Any]], fields: Sequence[str]) -> Dict[str, Any]:
    counts: Counter[Tuple[str, ...]] = Counter(
        tuple(str(row.get(field) or "") for field in fields) for row in rows
    )
    duplicates = [
        {field: value for field, value in zip(fields, key)} | {"row_count": count}
        for key, count in sorted(counts.items())
        if count > 1
    ]
    return {"status": "failed" if duplicates else "passed", "duplicate_keys": duplicates}


def _candidate_set_hash(symbols: Sequence[str]) -> str:
    canonical = json.dumps(list(symbols), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _by_date(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return _by_key(rows, "trade_date")


def _by_key(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return dict(sorted(grouped.items()))


def _execution_config(config: Optional[Dict[str, Any]]) -> Dict[str, float]:
    result = dict(DEFAULT_EXECUTION_CONFIG)
    for key in result:
        value = _number((config or {}).get(key))
        if value is not None:
            result[key] = value
    return result


def _average_dicts(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    keys = {key for row in rows for key, value in row.items() if isinstance(value, (int, float))}
    return {key: round(mean(float(row[key]) for row in rows if isinstance(row.get(key), (int, float))), 6) for key in sorted(keys)}


def _ndcg(rows: List[Dict[str, Any]], return_key: str, k: int) -> float:
    top = rows[:k]
    gains = [max(0.0, float(row[return_key])) for row in top]
    ideal = sorted((max(0.0, float(row[return_key])) for row in rows), reverse=True)[:k]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    return round(dcg / idcg, 6) if idcg else 0.0


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return round(_pearson(_ranks(xs), _ranks(ys)), 6)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    x_mean, y_mean = mean(xs), mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def _ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[start][0]:
            end += 1
        rank = (start + end + 2) / 2.0
        for _, index in ordered[start : end + 1]:
            ranks[index] = rank
        start = end + 1
    return ranks


def _return_pct(price: Optional[float], entry_price: float) -> Optional[float]:
    if price is None or price <= 0 or entry_price <= 0:
        return None
    return round((price / entry_price - 1) * 100, 6)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    parsed = pd.to_datetime(str(value), errors="coerce")
    return None if pd.isna(parsed) else parsed.date().isoformat()


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _mean_or_none(values: Sequence[float]) -> Optional[float]:
    return round(mean(values), 6) if values else None


def _median_or_none(values: Sequence[float]) -> Optional[float]:
    return round(median(values), 6) if values else None
