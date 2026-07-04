"""Read-only offline recall candidate generation for research experiments.

This module builds candidate rows from persisted full-market snapshots. It does
not call live data sources, persist picks, or change production strategy logic.
"""
from __future__ import annotations

import copy
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app.evaluation.recall_experiments import DEFAULT_EXPERIMENTS


CHANNELS = [
    "trend_breakout",
    "pullback_repair",
    "theme_strength",
    "volume_price_acceleration",
    "money_flow_activity",
    "low_drawdown_stability",
]


def generate_offline_recall_rows(
    store,
    experiment_key: str,
    strategy_code: str,
    risk_level: str,
    start_date: str,
    end_date: str,
    user_id: str = "default",
    max_rows_per_day: Optional[int] = None,
    min_market_snapshot_count: int = 1,
) -> Dict[str, Any]:
    """Generate offline experiment candidate rows from persisted market snapshots."""
    experiment = _experiment_config(experiment_key)
    requested_dates = _date_range(start_date, end_date)
    available_dates: List[str] = []
    rows: List[Dict[str, Any]] = []
    for trade_date in requested_dates:
        snapshot = _read_same_day_snapshot(store, trade_date, min_market_snapshot_count)
        items = list((snapshot or {}).get("items") or [])
        if not items:
            continue
        candidates = _daily_candidates(items, experiment, risk_level, max_rows_per_day)
        if not candidates:
            continue
        available_dates.append(trade_date)
        rows.extend(
            _candidate_row(
                trade_date=trade_date,
                item=item,
                rank_no=index,
                experiment=experiment,
                strategy_code=strategy_code,
                risk_level=risk_level,
                user_id=user_id,
            )
            for index, item in enumerate(candidates, start=1)
        )
    return {
        "rows": rows,
        "coverage": {
            **offline_recall_coverage(requested_dates, available_dates),
            "source": "persisted_market_snapshots",
            "same_day_market_snapshot_required": True,
        },
        "experiment": experiment,
    }


def offline_recall_coverage(requested_dates: Iterable[str], available_dates: Iterable[str]) -> Dict[str, Any]:
    requested = [str(item) for item in requested_dates or []]
    available = sorted(set(str(item) for item in available_dates or []))
    available_set = set(available)
    missing = [item for item in requested if item not in available_set]
    if not requested or not available:
        status = "blocked"
    elif not missing:
        status = "complete"
    else:
        status = "partial"
    return {
        "coverage_status": status,
        "requested_date_count": len(requested),
        "covered_date_count": len(available),
        "requested_dates": requested,
        "available_dates": available,
        "missing_dates": missing,
    }


def _read_same_day_snapshot(store, trade_date: str, min_count: int) -> Dict[str, Any]:
    if not store or not hasattr(store, "get_latest_valid_market_snapshot_items"):
        return {}
    snapshot = store.get_latest_valid_market_snapshot_items(trade_date=trade_date, min_count=max(1, int(min_count or 1))) or {}
    if _normalize_date(snapshot.get("trade_date")) != _normalize_date(trade_date):
        return {}
    return snapshot


def _daily_candidates(
    items: List[Dict[str, Any]],
    experiment: Dict[str, Any],
    risk_level: str,
    max_rows_per_day: Optional[int],
) -> List[Dict[str, Any]]:
    rules = _risk_rules(risk_level)
    filtered = [_scored_item(item, rules) for item in items]
    filtered = [item for item in filtered if item]
    recall_size = max(1, int(experiment.get("recall_size") or 220))
    deep_size = max(1, int(experiment.get("deep_analysis_size") or recall_size))
    if max_rows_per_day is not None:
        deep_size = min(deep_size, max(1, int(max_rows_per_day)))
    if experiment.get("recall_method") == "multi_channel_union":
        recalled = _multi_channel_union(filtered, recall_size)
    else:
        recalled = sorted(filtered, key=lambda item: (-item["offline_scores"]["production_pre_score"], item["symbol"]))[:recall_size]
    return sorted(recalled, key=lambda item: (-item["offline_scores"]["selected_score"], item["symbol"]))[:deep_size]


def _scored_item(item: Dict[str, Any], rules: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = str(item.get("symbol") or item.get("code") or "").strip()
    if len(symbol) != 6 or not symbol.isdigit() or symbol[0] not in {"0", "3", "6"}:
        return None
    name = str(item.get("name") or symbol)
    if _excluded_name(name):
        return None
    price = _safe_float(item.get("price"), 0.0)
    if price < rules["min_price"]:
        return None
    amount_yi = _safe_float(item.get("amount"), 0.0) / 100000000
    if amount_yi < rules["min_amount_yi"]:
        return None
    turnover = _safe_float(item.get("turnover_rate"), 0.0)
    if turnover <= 0:
        circ_mv = _safe_float(item.get("circ_mv"), 0.0)
        turnover = _clamp((_safe_float(item.get("amount"), 0.0) / circ_mv) * 100, 0, 60) if circ_mv > 0 else _clamp(amount_yi * 0.35, 0.2, 25)
    if turnover < rules["min_turnover_rate"] or turnover > rules["max_turnover_rate"]:
        return None
    pct_change = _safe_float(item.get("pct_change"), 0.0)
    if abs(pct_change) > rules["max_abs_pct_change"]:
        return None
    scored = copy.deepcopy(item)
    scored["symbol"] = symbol
    scored["name"] = name
    scored["turnover_rate"] = turnover
    scored["industry"] = str(item.get("industry") or _infer_board_industry(symbol))
    scored["offline_scores"] = _channel_scores(scored, amount_yi, turnover, pct_change)
    scored["recall_channels"] = ["production_pre_score"]
    return scored


def _channel_scores(item: Dict[str, Any], amount_yi: float, turnover: float, pct_change: float) -> Dict[str, float]:
    liquidity = _clamp(amount_yi * 6, 0, 100)
    turnover_score = _turnover_score(turnover)
    intraday_position = _intraday_position(item)
    trend_momentum = _clamp(12 - abs(pct_change - 2.5), 0, 12) * 8.2
    trend_intraday = _clamp((0.25 + intraday_position) * 80, 0, 100)
    production_pre_score = 0.38 * liquidity + 0.26 * turnover_score + 0.20 * trend_intraday + 0.16 * trend_momentum
    pullback_momentum = _clamp(12 - abs(pct_change + 1.8), 0, 12) * 8.2
    pullback_intraday = _clamp((1 - abs(intraday_position - 0.45)) * 100, 0, 100)
    pullback = 0.34 * liquidity + 0.24 * turnover_score + 0.22 * pullback_intraday + 0.20 * pullback_momentum
    volume_price = 0.35 * liquidity + 0.30 * turnover_score + 0.35 * _clamp((pct_change + 3.0) * 10, 0, 100)
    money_flow = 0.55 * liquidity + 0.25 * turnover_score + 0.20 * _clamp(max(pct_change, 0) * 10, 0, 100)
    stability = 0.45 * liquidity + 0.30 * _clamp(100 - abs(pct_change) * 12, 0, 100) + 0.25 * _clamp(100 - max(turnover - 6, 0) * 8, 0, 100)
    theme_strength = 0.45 * _clamp((pct_change + 1.0) * 12, 0, 100) + 0.35 * liquidity + 0.20 * turnover_score
    selected = production_pre_score
    return {
        "production_pre_score": round(production_pre_score, 6),
        "trend_breakout": round(production_pre_score, 6),
        "pullback_repair": round(pullback, 6),
        "theme_strength": round(theme_strength, 6),
        "volume_price_acceleration": round(volume_price, 6),
        "money_flow_activity": round(money_flow, 6),
        "low_drawdown_stability": round(stability, 6),
        "selected_score": round(selected, 6),
    }


def _multi_channel_union(items: List[Dict[str, Any]], recall_size: int) -> List[Dict[str, Any]]:
    selected: Dict[str, Dict[str, Any]] = {}
    per_channel = max(1, int(math.ceil(max(1, recall_size) / len(CHANNELS))))
    for channel in CHANNELS:
        ranked = sorted(items, key=lambda item: (-item["offline_scores"].get(channel, 0.0), item["symbol"]))
        for item in ranked[:per_channel]:
            symbol = item["symbol"]
            current = selected.get(symbol)
            channel_score = float(item["offline_scores"].get(channel, 0.0))
            if current is None:
                current = copy.deepcopy(item)
                current["recall_channels"] = []
                selected[symbol] = current
            current["recall_channels"].append(channel)
            if channel_score > float(current["offline_scores"].get("selected_score", 0.0)):
                current["offline_scores"]["selected_score"] = round(channel_score, 6)
    return sorted(selected.values(), key=lambda item: (-item["offline_scores"]["selected_score"], item["symbol"]))[:recall_size]


def _candidate_row(
    trade_date: str,
    item: Dict[str, Any],
    rank_no: int,
    experiment: Dict[str, Any],
    strategy_code: str,
    risk_level: str,
    user_id: str,
) -> Dict[str, Any]:
    scores = item.get("offline_scores") or {}
    return {
        "trade_date": trade_date,
        "pick_id": f"offline-{experiment['key']}-{trade_date}-{item['symbol']}",
        "symbol": item["symbol"],
        "name": item.get("name") or item["symbol"],
        "rank_no": int(rank_no),
        "score": round(_safe_float(scores.get("selected_score"), 0.0), 4),
        "source": f"offline_recall:{experiment['key']}",
        "experiment_key": experiment["key"],
        "strategy_code": strategy_code,
        "risk_level": risk_level,
        "user_id": user_id,
        "market_state_tag": "offline_research",
        "was_bought": False,
        "action_type": None,
        "recall_channels": list(item.get("recall_channels") or []),
        "factor_total_score": round(_safe_float(scores.get("selected_score"), 0.0), 4),
        "factor_ranking_score": round(_safe_float(scores.get("production_pre_score"), 0.0), 4),
        "factor_trend": round(_safe_float(scores.get("trend_breakout"), 0.0), 4),
        "factor_money_flow": round(_safe_float(scores.get("money_flow_activity"), 0.0), 4),
        "factor_turnover_liquidity": _turnover_score(_safe_float(item.get("turnover_rate"), 0.0)),
        "factor_swing_score": round(_safe_float(scores.get("pullback_repair"), 0.0), 4),
        "factor_continuation_score": round(_safe_float(scores.get("volume_price_acceleration"), 0.0), 4),
        "factor_risk_control_score": round(_safe_float(scores.get("low_drawdown_stability"), 0.0), 4),
        "factor_theme_rank_score": round(_safe_float(scores.get("theme_strength"), 0.0), 4),
        "factor_up_prob": 0.0,
        "factor_dd_prob": 0.0,
        "factor_expected_edge_pct": 0.0,
        "factor_profit_factor_proxy": 0.0,
    }


def _experiment_config(experiment_key: str) -> Dict[str, Any]:
    for item in DEFAULT_EXPERIMENTS:
        if item.get("key") == experiment_key:
            return dict(item)
    raise ValueError(f"unknown recall experiment: {experiment_key}")


def _risk_rules(risk_level: str) -> Dict[str, Any]:
    level = str(risk_level or "medium").lower()
    base = {"min_amount_yi": 2.0, "min_turnover_rate": 0.8, "max_turnover_rate": 20.0, "max_abs_pct_change": 12.0, "min_price": 2.0}
    if level == "low":
        return {**base, "min_amount_yi": 4.0, "max_turnover_rate": 12.0, "max_abs_pct_change": 8.0}
    if level == "high":
        return {**base, "min_amount_yi": 1.0, "min_turnover_rate": 0.5, "max_turnover_rate": 35.0, "max_abs_pct_change": 15.0, "min_price": 1.6}
    return base


def _turnover_score(turnover_rate: float) -> float:
    if turnover_rate <= 2:
        score = 45 + turnover_rate * 6
    elif turnover_rate <= 10:
        score = 57 + (turnover_rate - 2) * 3.5
    elif turnover_rate <= 20:
        score = 85 - (turnover_rate - 10) * 2
    else:
        score = 65 - (turnover_rate - 20) * 2
    return round(_clamp(score, 0, 100), 6)


def _intraday_position(item: Dict[str, Any]) -> float:
    price = _safe_float(item.get("price"), 0.0)
    high = _safe_float(item.get("high"), 0.0)
    low = _safe_float(item.get("low"), 0.0)
    day_range = high - low
    if price <= 0 or day_range <= 0:
        return 0.5
    return _clamp((price - low) / day_range, 0, 1)


def _date_range(start_date: str, end_date: str) -> List[str]:
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start > end:
        return []
    dates = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return dates


def _parse_date(value: Any) -> date:
    normalized = _normalize_date(value)
    if not normalized:
        raise ValueError(f"invalid date: {value}")
    return datetime.strptime(normalized, "%Y-%m-%d").date()


def _normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _excluded_name(name: str) -> bool:
    value = str(name or "").upper()
    return "ST" in value or "退" in value or "退市" in value


def _infer_board_industry(symbol: str) -> str:
    if str(symbol).startswith("688"):
        return "科创板"
    if str(symbol).startswith(("300", "301")):
        return "创业板"
    if str(symbol).startswith("6"):
        return "沪市主板"
    return "深市主板"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
