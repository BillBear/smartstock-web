"""Ranking-quality metrics for labeled candidate pools."""
from __future__ import annotations

import math
from statistics import mean
from typing import Any, Dict, Iterable, List


def evaluate_daily_ranking(rows: List[Dict[str, Any]], horizon: int, include_untradable: bool = False) -> Dict[str, Any]:
    """Return Precision/Recall/NDCG/MRR and Top-K return metrics for one day."""
    h = int(horizon)
    all_rows = _sort_rows(rows)
    tradable_rows = all_rows if include_untradable else [row for row in all_rows if _is_tradable(row)]
    strong_key = f"strong_{h}d"
    return_key = f"return_{h}d_pct"
    strong_rows = [row for row in tradable_rows if bool(row.get(strong_key))]
    top10 = [row for row in tradable_rows if _rank_no(row) <= 10]
    first_strong = next((row for row in tradable_rows if bool(row.get(strong_key))), None)

    metrics = {
        "horizon": h,
        "candidate_count": len(all_rows),
        "tradable_candidate_count": len(tradable_rows),
        "strong_candidate_count": len(strong_rows),
        "precision_at_3": _precision_at_k(tradable_rows, strong_key, 3),
        "precision_at_5": _precision_at_k(tradable_rows, strong_key, 5),
        "precision_at_10": _precision_at_k(tradable_rows, strong_key, 10),
        "recall_at_10": _round_ratio(
            sum(1 for row in top10 if bool(row.get(strong_key))),
            len(strong_rows),
        ),
        "ndcg_at_10": _ndcg_at_k(tradable_rows, return_key, 10),
        "mrr": round(1.0 / _rank_no(first_strong), 6) if first_strong else 0.0,
        "top_3_avg_return_pct": _top_k_avg_return(tradable_rows, return_key, 3),
        "top_5_avg_return_pct": _top_k_avg_return(tradable_rows, return_key, 5),
        "top_10_avg_return_pct": _top_k_avg_return(tradable_rows, return_key, 10),
    }
    return metrics


def rank_percentile_return_curve(rows: List[Dict[str, Any]], horizon: int, buckets: int = 10) -> List[Dict[str, Any]]:
    """Return average forward return by rank-percentile bucket."""
    h = int(horizon)
    bucket_count = max(1, int(buckets or 10))
    return_key = f"return_{h}d_pct"
    tradable_rows = [row for row in _sort_rows(rows) if _is_tradable(row)]
    total = len(tradable_rows)
    if total == 0:
        return []

    grouped: Dict[int, List[float]] = {bucket: [] for bucket in range(1, bucket_count + 1)}
    for index, row in enumerate(tradable_rows):
        percentile = index / max(total - 1, 1)
        bucket = min(bucket_count, int(percentile * bucket_count) + 1)
        grouped[bucket].append(_safe_float(row.get(return_key), 0.0))

    curve = []
    for bucket in range(1, bucket_count + 1):
        values = grouped[bucket]
        curve.append(
            {
                "horizon": h,
                "bucket": bucket,
                "rank_percentile_min": round((bucket - 1) / bucket_count, 6),
                "rank_percentile_max": round(bucket / bucket_count, 6),
                "row_count": len(values),
                f"avg_return_{h}d_pct": round(mean(values), 6) if values else 0.0,
            }
        )
    return curve


def _precision_at_k(rows: List[Dict[str, Any]], strong_key: str, k: int) -> float:
    denominator = min(int(k), len(rows))
    if denominator <= 0:
        return 0.0
    top_rows = [row for row in rows if _rank_no(row) <= int(k)]
    return _round_ratio(sum(1 for row in top_rows if bool(row.get(strong_key))), denominator)


def _ndcg_at_k(rows: List[Dict[str, Any]], return_key: str, k: int) -> float:
    top_rows = [row for row in rows if _rank_no(row) <= int(k)]
    dcg = sum(_gain(row.get(return_key)) / math.log2(_rank_no(row) + 1) for row in top_rows)
    ideal_gains = sorted((_gain(row.get(return_key)) for row in rows), reverse=True)[: max(0, int(k))]
    idcg = _discounted_gain(ideal_gains)
    if idcg <= 0:
        return 0.0
    return round(dcg / idcg, 6)


def _discounted_gain(gains: Iterable[float]) -> float:
    total = 0.0
    for index, gain in enumerate(gains, start=1):
        total += gain / math.log2(index + 1)
    return total


def _gain(value: Any) -> float:
    return min(max(_safe_float(value, 0.0), 0.0), 60.0)


def _top_k_avg_return(rows: List[Dict[str, Any]], return_key: str, k: int) -> float:
    top_rows = [row for row in rows if _rank_no(row) <= int(k)]
    if not top_rows:
        return 0.0
    return round(mean(_safe_float(row.get(return_key), 0.0) for row in top_rows), 6)


def _sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(list(rows or []), key=lambda row: (_rank_no(row), str(row.get("symbol") or "")))


def _rank_no(row: Dict[str, Any] | None) -> int:
    if not row:
        return 999999
    try:
        return int(row.get("rank_no") or 999999)
    except (TypeError, ValueError):
        return 999999


def _is_tradable(row: Dict[str, Any]) -> bool:
    return str(row.get("tradability_status") or "tradable") == "tradable"


def _round_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result
