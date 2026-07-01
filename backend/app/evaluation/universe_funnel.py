"""
Read-only full-market funnel diagnostics for SmartStock strategy evidence.

This module must not be used as a production picker. It explains coverage and
recall loss points so strategy changes can be evaluated before changing rules.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_MIN_FULL_UNIVERSE_COUNT = 5000
DEFAULT_MIN_AMOUNT = 30_000_000
DEFAULT_DEEP_ANALYSIS_BUDGETS = (72, 150, 300, 500)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _stock_symbol(item: Dict[str, Any]) -> str:
    return str(item.get("symbol") or item.get("code") or "").strip()


def _stock_name(item: Dict[str, Any]) -> str:
    symbol = _stock_symbol(item)
    return str(item.get("name") or item.get("stock_name") or symbol).strip()


def _is_st_or_delisting(name: str) -> bool:
    normalized = name.upper().replace(" ", "")
    return "ST" in normalized or "退" in name


def _limit_pct_for_symbol(symbol: str) -> float:
    if symbol.startswith(("300", "301", "688", "689")):
        return 19.8
    return 9.8


def _basic_filter_rejection(item: Dict[str, Any], min_amount: float) -> Optional[str]:
    symbol = _stock_symbol(item)
    name = _stock_name(item)
    if len(symbol) != 6 or not symbol.isdigit():
        return "invalid_symbol"
    if _is_st_or_delisting(name):
        return "st_or_delisting"

    price = _to_float(item.get("price") or item.get("close") or item.get("current_price"))
    if price <= 1.0:
        return "price_abnormal"

    amount = _to_float(item.get("amount") or item.get("turnover") or item.get("成交额"))
    if amount < min_amount:
        return "amount_too_low"

    pct_change = _to_float(item.get("pct_change") or item.get("change_pct") or item.get("涨跌幅"))
    limit_pct = _limit_pct_for_symbol(symbol)
    if pct_change >= limit_pct or pct_change <= -limit_pct:
        return "limit_move_not_buyable"

    status = str(item.get("status") or item.get("trade_status") or "").strip()
    if status in {"停牌", "paused", "suspended", "SUSPENDED"}:
        return "suspended"

    return None


def _channel_hits(item: Dict[str, Any]) -> List[str]:
    pct_change = _to_float(item.get("pct_change") or item.get("change_pct") or item.get("涨跌幅"))
    volume_ratio = _to_float(item.get("volume_ratio") or item.get("量比"), 1.0)
    turnover_rate = _to_float(item.get("turnover_rate") or item.get("换手率"))
    amount = _to_float(item.get("amount") or item.get("turnover") or item.get("成交额"))
    momentum = _to_float(item.get("momentum_score") or item.get("momentum") or item.get("上涨广度"))
    trend_strength = _to_float(item.get("trend_strength") or item.get("trend_score") or item.get("趋势评分"))
    drawdown = _to_float(item.get("drawdown_pct") or item.get("recent_drawdown_pct") or item.get("回撤概率"))
    industry_pct = _to_float(item.get("industry_pct_change") or item.get("industry_change_pct") or item.get("行业涨幅"))
    theme_heat = _to_float(item.get("theme_heat_score") or item.get("theme_score") or item.get("concept_heat_score"))
    money_flow = _to_float(item.get("money_flow_score") or item.get("net_inflow_score") or item.get("资金评分"))

    channels: List[str] = []
    if trend_strength >= 75 or (pct_change >= 4.0 and volume_ratio >= 1.8 and momentum >= 65):
        channels.append("trend_breakout")
    if -1.5 <= pct_change <= 2.5 and 3.0 <= drawdown <= 12.0 and momentum >= 55:
        channels.append("pullback_repair")
    if industry_pct >= 2.0 or theme_heat >= 65:
        channels.append("theme_industry_strength")
    if pct_change >= 3.0 and volume_ratio >= 2.0:
        channels.append("volume_price_acceleration")
    if money_flow >= 60 or (amount >= 150_000_000 and turnover_rate >= 3.0):
        channels.append("money_flow_activity")
    if drawdown <= 3.0 and momentum >= 55 and pct_change >= 0:
        channels.append("low_drawdown_stable")
    return channels


def _diagnostic_score(item: Dict[str, Any], channels: List[str]) -> float:
    pct_change = _to_float(item.get("pct_change") or item.get("change_pct") or item.get("涨跌幅"))
    volume_ratio = _to_float(item.get("volume_ratio") or item.get("量比"), 1.0)
    amount = _to_float(item.get("amount") or item.get("turnover") or item.get("成交额"))
    momentum = _to_float(item.get("momentum_score") or item.get("momentum") or item.get("上涨广度"))
    trend_strength = _to_float(item.get("trend_strength") or item.get("trend_score") or item.get("趋势评分"))
    drawdown = _to_float(item.get("drawdown_pct") or item.get("recent_drawdown_pct") or item.get("回撤概率"))
    pre_score = _to_float(item.get("pre_score") or item.get("score") or item.get("综合分"))
    amount_score = min(20.0, amount / 50_000_000)
    channel_bonus = min(30.0, len(channels) * 6.0)
    return round(
        min(
            100.0,
            pre_score * 0.25
            + trend_strength * 0.20
            + momentum * 0.18
            + max(0.0, pct_change) * 1.4
            + min(12.0, volume_ratio * 2.0)
            + amount_score
            + channel_bonus
            - min(16.0, max(0.0, drawdown) * 0.45),
        ),
        4,
    )


def _sample_row(item: Dict[str, Any], channels: Optional[List[str]] = None, reason: Optional[str] = None) -> Dict[str, Any]:
    row = {
        "symbol": _stock_symbol(item),
        "name": _stock_name(item),
        "industry": str(item.get("industry") or item.get("行业") or ""),
        "pct_change": round(_to_float(item.get("pct_change") or item.get("change_pct") or item.get("涨跌幅")), 4),
        "amount": round(_to_float(item.get("amount") or item.get("turnover") or item.get("成交额")), 2),
    }
    if channels is not None:
        row["channels"] = channels
    if reason:
        row["reason"] = reason
    return row


def build_universe_funnel_report(
    items: Iterable[Dict[str, Any]],
    *,
    min_full_universe_count: int = DEFAULT_MIN_FULL_UNIVERSE_COUNT,
    min_amount: float = DEFAULT_MIN_AMOUNT,
    deep_analysis_budgets: Tuple[int, ...] = DEFAULT_DEEP_ANALYSIS_BUDGETS,
) -> Dict[str, Any]:
    """Build a deterministic diagnostics report from a full-market snapshot."""
    rows = [dict(item or {}) for item in items or []]
    total = len(rows)
    min_count = max(1, int(min_full_universe_count or DEFAULT_MIN_FULL_UNIVERSE_COUNT))

    rejection_reason_counts: Counter = Counter()
    rejected_samples: List[Dict[str, Any]] = []
    basic_pass: List[Dict[str, Any]] = []
    for item in rows:
        reason = _basic_filter_rejection(item, min_amount=min_amount)
        if reason:
            rejection_reason_counts[reason] += 1
            if len(rejected_samples) < 20:
                rejected_samples.append(_sample_row(item, reason=reason))
            continue
        basic_pass.append(item)

    channel_counts: Counter = Counter()
    diagnostics_by_symbol: Dict[str, Dict[str, Any]] = {}
    recalled: List[Dict[str, Any]] = []
    for item in basic_pass:
        channels = _channel_hits(item)
        symbol = _stock_symbol(item)
        if channels:
            for channel in channels:
                channel_counts[channel] += 1
            diagnostics_by_symbol[symbol] = {
                "symbol": symbol,
                "name": _stock_name(item),
                "channels": channels,
                "diagnostic_score": _diagnostic_score(item, channels),
            }
            recalled.append(item)
        else:
            rejection_reason_counts["not_recalled_by_channel"] += 1

    recalled.sort(key=lambda item: (-_diagnostic_score(item, _channel_hits(item)), _stock_symbol(item)))
    budget_counts = {str(int(budget)): min(len(recalled), int(budget)) for budget in deep_analysis_budgets}
    coverage_ok = total >= min_count

    return {
        "schema_version": "universe_funnel_v1",
        "read_only": True,
        "coverage": {
            "status": "ok" if coverage_ok else "insufficient_coverage",
            "min_full_universe_count": min_count,
            "can_generate_trade_plan": bool(coverage_ok),
            "message": (
                "全市场样本覆盖达标，可进入策略证据评估。"
                if coverage_ok
                else "全市场样本覆盖不足，不应生成交易计划。"
            ),
        },
        "counts": {
            "full_market": total,
            "basic_filter_pass": len(basic_pass),
            "multi_channel_recall": len(recalled),
            "deep_analysis_budgets": budget_counts,
        },
        "channel_counts": dict(channel_counts),
        "rejection_reason_counts": dict(rejection_reason_counts),
        "samples": {
            "recalled": [
                {
                    **_sample_row(item, _channel_hits(item)),
                    "diagnostic_score": _diagnostic_score(item, _channel_hits(item)),
                }
                for item in recalled[:30]
            ],
            "rejected": rejected_samples,
        },
        "diagnostics_by_symbol": diagnostics_by_symbol,
        "notes": [
            "本报告仅用于候选漏斗诊断和策略证据建设，不改变生产选股、排序或交易动作。",
            "deep_analysis_budgets 仅用于离线容量比较，不代表当前生产默认值已变更。",
        ],
    }
