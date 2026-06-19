"""Structured diagnostics for candidate ranking failures."""
from __future__ import annotations

import math
from statistics import mean
from typing import Any, Dict, List, Optional


DEFAULT_FACTOR_FIELDS = [
    "factor_ranking_score",
    "factor_swing_score",
    "factor_continuation_score",
    "factor_risk_control_score",
    "factor_leader_score",
    "factor_theme_rank_score",
    "factor_up_prob",
    "factor_dd_prob",
    "factor_expected_edge_pct",
    "factor_profit_factor_proxy",
    "factor_total_score",
    "factor_trend",
    "factor_money_flow",
    "factor_turnover_liquidity",
    "factor_volume_ratio_20",
    "factor_rsi",
    "factor_ma20_gap_pct",
]


def build_ranking_diagnostics(rows: List[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    """Return diagnostic sections for ranking quality review."""
    h = int(horizon)
    return_key = f"return_{h}d_pct"
    strong_key = f"strong_{h}d"
    normalized = [dict(row) for row in rows or []]
    sorted_by_return = sorted(normalized, key=lambda row: _safe_float(row.get(return_key), 0.0), reverse=True)
    top_decile_cutoff = _quantile([_safe_float(row.get(return_key), 0.0) for row in normalized], 0.9)
    bottom_decile_cutoff = _quantile([_safe_float(row.get(return_key), 0.0) for row in normalized], 0.1)

    late_winners = [
        row
        for row in sorted_by_return
        if _rank_no(row) > 10 and (_safe_float(row.get(return_key), 0.0) >= top_decile_cutoff or bool(row.get(strong_key)))
    ]
    early_losers = [
        row
        for row in sorted(normalized, key=lambda item: _rank_no(item))
        if _rank_no(row) <= 10
        and (
            _safe_float(row.get(return_key), 0.0) <= bottom_decile_cutoff
            or str(row.get("tp_sl_path") or "") == "sl_before_tp"
        )
    ]
    unbought_strong = [
        row
        for row in sorted_by_return
        if bool(row.get(strong_key)) and not bool(row.get("was_bought"))
    ]

    return {
        "horizon": h,
        "unbought_strong_samples": [_sample(row, return_key, normalized) for row in unbought_strong[:20]],
        "late_winner_samples": [_sample(row, return_key, normalized) for row in late_winners[:20]],
        "early_loser_samples": [_sample(row, return_key, normalized) for row in early_losers[:20]],
        "factor_correlations": factor_correlations(normalized, h),
        "market_state_breakdown": _market_state_breakdown(normalized, h),
        "buy_trigger_conservatism": _buy_trigger_conservatism(normalized, h),
    }


def factor_correlations(
    rows: List[Dict[str, Any]],
    horizon: int,
    factor_fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Return Pearson and Spearman correlations for factor fields vs future returns."""
    h = int(horizon)
    return_key = f"return_{h}d_pct"
    fields = factor_fields or DEFAULT_FACTOR_FIELDS
    results = []
    for field in fields:
        pairs = [
            (_safe_float(row.get(field), None), _safe_float(row.get(return_key), None))
            for row in rows or []
        ]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        if len(pairs) < 2:
            continue
        xs = [item[0] for item in pairs]
        ys = [item[1] for item in pairs]
        results.append(
            {
                "horizon": h,
                "factor": field,
                "sample_count": len(pairs),
                "pearson": round(_pearson(xs, ys), 6),
                "spearman": round(_pearson(_ranks(xs), _ranks(ys)), 6),
            }
        )
    return results


def _market_state_breakdown(rows: List[Dict[str, Any]], horizon: int) -> Dict[str, Dict[str, Any]]:
    h = int(horizon)
    return_key = f"return_{h}d_pct"
    strong_key = f"strong_{h}d"
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows or []:
        grouped.setdefault(str(row.get("market_state_tag") or "unknown"), []).append(row)
    output = {}
    for state, items in grouped.items():
        returns = [_safe_float(row.get(return_key), 0.0) for row in items]
        strong_count = sum(1 for row in items if bool(row.get(strong_key)))
        top10 = [row for row in items if _rank_no(row) <= 10]
        top10_strong = sum(1 for row in top10 if bool(row.get(strong_key)))
        output[state] = {
            "row_count": len(items),
            "strong_count": strong_count,
            "avg_return_pct": round(mean(returns), 6) if returns else 0.0,
            "top10_count": len(top10),
            "top10_strong_count": top10_strong,
            "top10_precision": round(top10_strong / len(top10), 6) if top10 else 0.0,
            "failure_modes": _failure_modes(items, h),
        }
    return output


def _buy_trigger_conservatism(rows: List[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    h = int(horizon)
    strong_key = f"strong_{h}d"
    return_key = f"return_{h}d_pct"
    unbought_strong = [row for row in rows if bool(row.get(strong_key)) and not bool(row.get("was_bought"))]
    unbought_strong_top10 = [row for row in unbought_strong if _rank_no(row) <= 10]
    bought_strong = [row for row in rows if bool(row.get(strong_key)) and bool(row.get("was_bought"))]
    return {
        "diagnostic_only": True,
        "unbought_strong_count": len(unbought_strong),
        "unbought_strong_top10_count": len(unbought_strong_top10),
        "bought_strong_count": len(bought_strong),
        "unbought_strong_avg_return_pct": _avg_return(unbought_strong, return_key),
        "bought_strong_avg_return_pct": _avg_return(bought_strong, return_key),
        "interpretation": "Diagnostic only; this does not change buy triggers or recommend parameter updates.",
    }


def _failure_modes(rows: List[Dict[str, Any]], horizon: int) -> List[Dict[str, Any]]:
    return_key = f"return_{int(horizon)}d_pct"
    top10 = [row for row in rows if _rank_no(row) <= 10]
    late_strong = [row for row in rows if _rank_no(row) > 10 and bool(row.get(f"strong_{int(horizon)}d"))]
    sl_first = [row for row in top10 if str(row.get("tp_sl_path") or "") == "sl_before_tp"]
    negative_top10 = [row for row in top10 if _safe_float(row.get(return_key), 0.0) < 0]
    modes = []
    if late_strong:
        modes.append({"key": "late_strong_candidates", "count": len(late_strong), "description": "strong future performers ranked outside Top 10"})
    if sl_first:
        modes.append({"key": "top10_stop_loss_first", "count": len(sl_first), "description": "Top 10 candidates hit stop-loss before take-profit"})
    if negative_top10:
        modes.append({"key": "negative_top10_returns", "count": len(negative_top10), "description": "Top 10 candidates had negative forward returns"})
    return modes


def _sample(row: Dict[str, Any], return_key: str, all_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    sample = {
        "trade_date": row.get("trade_date"),
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "rank_no": _rank_no(row),
        "rank_percentile": _rank_percentile(row, all_rows),
        return_key: _safe_float(row.get(return_key), 0.0),
        "max_floating_profit_pct": _safe_float(row.get("max_floating_profit_pct"), 0.0),
        "max_adverse_excursion_pct": _safe_float(row.get("max_adverse_excursion_pct"), 0.0),
        "tp_sl_path": row.get("tp_sl_path"),
        "was_bought": bool(row.get("was_bought")),
        "market_state_tag": row.get("market_state_tag"),
    }
    for field in DEFAULT_FACTOR_FIELDS:
        if field in row:
            sample[field] = row.get(field)
    return sample


def _rank_percentile(row: Dict[str, Any], rows: List[Dict[str, Any]]) -> float:
    ranked = sorted(rows or [], key=lambda item: _rank_no(item))
    total = len(ranked)
    if total <= 1:
        return 0.0
    rank = _rank_no(row)
    return round((rank - 1) / max(total - 1, 1), 6)


def _avg_return(rows: List[Dict[str, Any]], return_key: str) -> float:
    if not rows:
        return 0.0
    return round(mean(_safe_float(row.get(return_key), 0.0) for row in rows), 6)


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[int(pos)]
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _pearson(xs: List[float], ys: List[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mean_x = mean(xs)
    mean_y = mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x <= 0 or denom_y <= 0:
        return 0.0
    return numerator / (denom_x * denom_y)


def _ranks(values: List[float]) -> List[float]:
    ordered = sorted((value, idx) for idx, value in enumerate(values))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[cursor][0]:
            end += 1
        avg_rank = (cursor + end + 2) / 2.0
        for item_idx in range(cursor, end + 1):
            ranks[ordered[item_idx][1]] = avg_rank
        cursor = end + 1
    return ranks


def _rank_no(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("rank_no") or 999999)
    except (TypeError, ValueError):
        return 999999


def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result
