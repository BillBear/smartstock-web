"""Read-only readiness checks for ML model evidence."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


MIN_SAMPLE_COUNT = 100_000
MIN_SYMBOL_COUNT = 1_500
MIN_TIME_SPAN_DAYS = 730
MIN_STOCK_HOLDOUT_RATIO = 0.20
MIN_FINAL_HOLDOUT_MONTHS = 3
MIN_BOARD_COUNT = 3
MIN_LIQUIDITY_BUCKET_COUNT = 3
MIN_INDUSTRY_COUNT = 10
MIN_MARKET_STATE_COUNT = 3
REQUIRED_FINAL_HOLDOUT_METRICS = ("auc", "brier_score", "ece", "precision_at_3", "precision_at_5")


def assess_ml_readiness(model_record: Dict[str, Any]) -> Dict[str, Any]:
    """Classify whether an ML model has enough evidence for production trust.

    The check is intentionally read-only. It does not decide trades and does not
    change model outputs; it only labels whether the model evidence is strong
    enough to be presented as production-grade.
    """
    record = model_record or {}
    metrics = record.get("metrics") or {}
    train_config = record.get("train_config") or {}
    coverage = metrics.get("coverage") or {}
    final_holdout = metrics.get("final_holdout") or {}
    stock_holdout = metrics.get("stock_holdout") or {}

    sample_count = _safe_int(record.get("sample_count") or metrics.get("sample_count"), 0)
    symbol_count = _infer_symbol_count(record, train_config, metrics)
    span_days = _training_span_days(record.get("train_start"), record.get("train_end"))

    blocking: List[Dict[str, str]] = []
    if sample_count < MIN_SAMPLE_COUNT:
        blocking.append(_block("sample_count_below_100000", f"训练样本数 {sample_count} 低于 {MIN_SAMPLE_COUNT}"))
    if symbol_count < MIN_SYMBOL_COUNT:
        blocking.append(_block("symbol_count_below_1500", f"训练股票数 {symbol_count} 低于 {MIN_SYMBOL_COUNT}"))
    if span_days < MIN_TIME_SPAN_DAYS:
        blocking.append(_block("time_span_below_24_months", f"训练跨度 {span_days} 天低于 24 个月要求"))

    stock_holdout_ratio = _safe_float(train_config.get("stock_holdout_ratio"), 0.0)
    stock_holdout_symbols = _safe_int(stock_holdout.get("symbol_count"), 0)
    required_stock_holdout_symbols = max(1, int(symbol_count * MIN_STOCK_HOLDOUT_RATIO)) if symbol_count > 0 else 1
    if stock_holdout_ratio < MIN_STOCK_HOLDOUT_RATIO or stock_holdout_symbols < required_stock_holdout_symbols:
        blocking.append(_block("stock_holdout_missing", "缺少至少 20% 股票完全留出的样本外验证"))

    final_holdout_months = _safe_float(train_config.get("final_time_holdout_months"), 0.0)
    if final_holdout_months < MIN_FINAL_HOLDOUT_MONTHS and not final_holdout:
        blocking.append(_block("final_time_holdout_missing", "缺少最近 3 个月完全留出的最终时间 holdout"))

    missing_holdout_metrics = [
        key for key in REQUIRED_FINAL_HOLDOUT_METRICS
        if final_holdout and key not in final_holdout
    ]
    if final_holdout and missing_holdout_metrics:
        blocking.append(_block("final_holdout_metrics_incomplete", f"最终 holdout 缺少指标: {', '.join(missing_holdout_metrics)}"))
    if not final_holdout:
        blocking.append(_block("final_holdout_metrics_missing", "缺少最终 holdout 的 AUC/Brier/ECE/Precision@K 指标"))

    bucket_hit_rates = final_holdout.get("bucket_hit_rates") or metrics.get("bucket_hit_rates") or []
    if not bucket_hit_rates:
        blocking.append(_block("bucket_hit_rates_missing", "缺少概率分桶命中率样本外结果"))

    if not _has_walk_forward(metrics):
        blocking.append(_block("walk_forward_missing", "缺少 walk-forward 验证结果"))

    board_count = _safe_int(coverage.get("board_count"), 0)
    liquidity_bucket_count = _safe_int(coverage.get("liquidity_bucket_count"), 0)
    industry_count = _safe_int(coverage.get("industry_count"), 0)
    market_state_count = _safe_int(coverage.get("market_state_count"), 0)
    if board_count < MIN_BOARD_COUNT:
        blocking.append(_block("board_coverage_incomplete", "训练样本未覆盖主板、创业板、科创板"))
    if liquidity_bucket_count < MIN_LIQUIDITY_BUCKET_COUNT:
        blocking.append(_block("liquidity_coverage_incomplete", "训练样本未覆盖高/中/低流动性分层"))
    if industry_count < MIN_INDUSTRY_COUNT:
        blocking.append(_block("industry_coverage_incomplete", "训练样本行业覆盖不足"))
    if market_state_count < MIN_MARKET_STATE_COUNT:
        blocking.append(_block("market_state_coverage_incomplete", "训练样本未覆盖至少 3 类市场状态"))

    ready = len(blocking) == 0
    return {
        "status": "ready" if ready else "insufficient",
        "production_ml_ready": ready,
        "role": "ranking_confidence_factor" if ready else "weak_reference_only",
        "label": "样本外验证通过模型" if ready else "弱模型参考",
        "message": "模型训练证据满足生产准入，可作为排序和置信度辅助因子。" if ready else "模型训练证据不足，仅能作为弱参考，不应展示成可靠胜率。",
        "blocking_reasons": blocking,
        "blocking_codes": [item["code"] for item in blocking],
        "minimums": {
            "sample_count": MIN_SAMPLE_COUNT,
            "symbol_count": MIN_SYMBOL_COUNT,
            "time_span_days": MIN_TIME_SPAN_DAYS,
            "stock_holdout_ratio": MIN_STOCK_HOLDOUT_RATIO,
            "final_time_holdout_months": MIN_FINAL_HOLDOUT_MONTHS,
        },
        "observed": {
            "sample_count": sample_count,
            "symbol_count": symbol_count,
            "time_span_days": span_days,
            "stock_holdout_ratio": stock_holdout_ratio,
            "stock_holdout_symbol_count": stock_holdout_symbols,
            "final_time_holdout_months": final_holdout_months,
            "board_count": board_count,
            "liquidity_bucket_count": liquidity_bucket_count,
            "industry_count": industry_count,
            "market_state_count": market_state_count,
        },
    }


def _block(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message}


def _infer_symbol_count(record: Dict[str, Any], train_config: Dict[str, Any], metrics: Dict[str, Any]) -> int:
    explicit_symbols = train_config.get("symbols") or []
    if isinstance(explicit_symbols, list) and explicit_symbols:
        return len({str(symbol) for symbol in explicit_symbols if str(symbol).strip()})
    for value in (
        record.get("symbol_count"),
        metrics.get("symbol_count"),
        metrics.get("valid_symbol_count"),
        (metrics.get("sample_meta") or {}).get("symbol_count") if isinstance(metrics.get("sample_meta"), dict) else None,
        train_config.get("max_symbols"),
    ):
        parsed = _safe_int(value, 0)
        if parsed > 0:
            return parsed
    return 0


def _training_span_days(start: Any, end: Any) -> int:
    start_dt = _parse_date(start)
    end_dt = _parse_date(end)
    if not start_dt or not end_dt or end_dt < start_dt:
        return 0
    return (end_dt - start_dt).days


def _parse_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _has_walk_forward(metrics: Dict[str, Any]) -> bool:
    method = str(metrics.get("method") or "").lower()
    split_count = _safe_int(metrics.get("split_count"), 0)
    return "walk_forward" in method and split_count >= 2


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
