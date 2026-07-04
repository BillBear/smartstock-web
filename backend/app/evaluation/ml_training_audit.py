"""Read-only audit for full-market ML training dataset readiness."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text

from app.evaluation.ml_readiness import (
    MIN_INDUSTRY_COUNT,
    MIN_SAMPLE_COUNT,
    MIN_SYMBOL_COUNT,
    MIN_TIME_SPAN_DAYS,
)


def build_ml_training_readiness_audit(
    store,
    train_start: str,
    train_end: str,
    sample_step: int = 3,
    min_full_market_count: int = 5000,
    min_symbol_count: int = MIN_SYMBOL_COUNT,
    min_time_span_days: int = MIN_TIME_SPAN_DAYS,
    min_estimated_samples: int = MIN_SAMPLE_COUNT,
    min_snapshot_dates: int = 30,
) -> Dict[str, Any]:
    """Audit whether persisted snapshots can support full-market ML training.

    This function is intentionally read-only. It does not call market data
    providers, build training rows, train a model, or alter production scoring.
    """
    normalized_start = _normalize_date(train_start)
    normalized_end = _normalize_date(train_end)
    bounded_sample_step = max(1, int(sample_step or 1))
    snapshots = _load_snapshot_rows(store, normalized_start, normalized_end)
    eligible_snapshots = [
        row for row in snapshots
        if int(row.get("snapshot_count") or 0) >= max(1, int(min_full_market_count or 1))
    ]
    latest_snapshot = eligible_snapshots[-1] if eligible_snapshots else (snapshots[-1] if snapshots else {})
    latest_items = _load_snapshot_items(store, latest_snapshot.get("snapshot_id")) if latest_snapshot else []

    symbols = sorted({str(item.get("symbol") or "").strip() for item in latest_items if str(item.get("symbol") or "").strip()})
    latest_snapshot_count = int(latest_snapshot.get("snapshot_count") or len(symbols) or 0)
    eligible_date_count = len({row.get("trade_date") for row in eligible_snapshots if row.get("trade_date")})
    estimated_samples = int((eligible_date_count * max(latest_snapshot_count, len(symbols))) / bounded_sample_step)
    span_days = _date_span_days(normalized_start, normalized_end)
    boards = _board_set(symbols)
    industries = sorted({str(item.get("industry") or "").strip() for item in latest_items if str(item.get("industry") or "").strip()})

    blocking: List[Dict[str, str]] = []
    if latest_snapshot_count < int(min_full_market_count or 5000):
        blocking.append(
            _block(
                "full_market_snapshot_count_below_5000",
                f"最新可用全市场快照 {latest_snapshot_count} 只，低于 {int(min_full_market_count or 5000)} 只要求。",
            )
        )
    if len(symbols) < int(min_symbol_count or MIN_SYMBOL_COUNT):
        blocking.append(
            _block(
                "symbol_count_below_1500",
                f"最新快照可训练股票数 {len(symbols)} 低于 {int(min_symbol_count or MIN_SYMBOL_COUNT)}。",
            )
        )
    if span_days < int(min_time_span_days or MIN_TIME_SPAN_DAYS):
        blocking.append(
            _block(
                "time_span_below_24_months",
                f"训练窗口跨度 {span_days} 天，低于 {int(min_time_span_days or MIN_TIME_SPAN_DAYS)} 天。",
            )
        )
    if eligible_date_count < int(min_snapshot_dates or 30):
        blocking.append(
            _block(
                "snapshot_date_count_below_required",
                f"满足全市场阈值的快照日期 {eligible_date_count} 个，低于 {int(min_snapshot_dates or 30)} 个。",
            )
        )
    if estimated_samples < int(min_estimated_samples or MIN_SAMPLE_COUNT):
        blocking.append(
            _block(
                "estimated_sample_count_below_required",
                f"按 sample_step={bounded_sample_step} 估算样本数 {estimated_samples}，低于 {int(min_estimated_samples or MIN_SAMPLE_COUNT)}。",
            )
        )
    if len(boards) < 3:
        blocking.append(_block("board_coverage_incomplete", "最新快照未同时覆盖主板、创业板、科创板。"))
    if len(industries) < MIN_INDUSTRY_COUNT:
        blocking.append(_block("industry_coverage_incomplete", f"最新快照行业覆盖 {len(industries)} 个，低于 {MIN_INDUSTRY_COUNT} 个。"))

    ready = not blocking
    return {
        "audit_type": "ml_training_dataset_readiness",
        "status": "ready_for_dataset_build" if ready else "blocked",
        "dataset_build_ready": ready,
        "production_ml_ready": False,
        "message": (
            "本地快照覆盖满足全市场训练数据构建前置条件；仍需实际构建数据集、训练候选模型并完成样本外验证。"
            if ready
            else "本地快照覆盖尚不足以支撑全市场训练数据构建。"
        ),
        "blocking_reasons": blocking,
        "blocking_codes": [item["code"] for item in blocking],
        "observed": {
            "train_start": normalized_start,
            "train_end": normalized_end,
            "time_span_days": span_days,
            "snapshot_date_count": len({row.get("trade_date") for row in snapshots if row.get("trade_date")}),
            "eligible_full_market_snapshot_date_count": eligible_date_count,
            "latest_snapshot_id": latest_snapshot.get("snapshot_id"),
            "latest_snapshot_trade_date": latest_snapshot.get("trade_date"),
            "latest_snapshot_count": latest_snapshot_count,
            "symbol_count": len(symbols),
            "board_count": len(boards),
            "boards": sorted(boards),
            "industry_count": len(industries),
            "sample_step": bounded_sample_step,
            "estimated_sample_count": estimated_samples,
        },
        "minimums": {
            "full_market_snapshot_count": int(min_full_market_count or 5000),
            "symbol_count": int(min_symbol_count or MIN_SYMBOL_COUNT),
            "time_span_days": int(min_time_span_days or MIN_TIME_SPAN_DAYS),
            "snapshot_dates": int(min_snapshot_dates or 30),
            "estimated_samples": int(min_estimated_samples or MIN_SAMPLE_COUNT),
            "industry_count": MIN_INDUSTRY_COUNT,
        },
        "split_requirements": {
            "walk_forward_splits": 5,
            "final_time_holdout_months": 3,
            "stock_holdout_ratio": 0.20,
        },
        "next_required_step": (
            "build_full_market_dataset_and_train_candidate_model"
            if ready
            else "collect_or_backfill_full_market_snapshot_history"
        ),
        "notes": [
            "This audit is read-only and does not train a model.",
            "production_ml_ready remains false until final holdout, stock holdout, walk-forward and bucket hit-rate metrics pass.",
        ],
    }


def write_ml_training_readiness_audit(audit: Dict[str, Any], output_json: Optional[str] = None, output_md: Optional[str] = None) -> None:
    if output_json:
        path = Path(output_json).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if output_md:
        path = Path(output_md).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_audit_to_markdown(audit), encoding="utf-8")


def _load_snapshot_rows(store, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    if not store or not hasattr(store, "engine"):
        return []
    sql = text(
        """
        SELECT snapshot_id, trade_date, source, snapshot_count, quality_status, created_at
        FROM market_snapshots
        WHERE trade_date >= :start_date
          AND trade_date <= :end_date
        ORDER BY trade_date ASC, snapshot_count ASC, created_at ASC
        """
    )
    with store.engine.connect() as conn:
        rows = conn.execute(sql, {"start_date": start_date, "end_date": end_date}).fetchall()
    deduped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        record = dict(row._mapping)
        trade_date = _normalize_date(record.get("trade_date"))
        if not trade_date:
            continue
        record["trade_date"] = trade_date
        current = deduped.get(trade_date)
        if current is None or int(record.get("snapshot_count") or 0) >= int(current.get("snapshot_count") or 0):
            deduped[trade_date] = record
    return [deduped[date] for date in sorted(deduped)]


def _load_snapshot_items(store, snapshot_id: Any) -> List[Dict[str, Any]]:
    if not snapshot_id or not store or not hasattr(store, "engine"):
        return []
    sql = text(
        """
        SELECT symbol, name, industry
        FROM market_snapshot_items
        WHERE snapshot_id = :snapshot_id
        ORDER BY symbol ASC
        """
    )
    with store.engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(sql, {"snapshot_id": str(snapshot_id)}).fetchall()]


def _audit_to_markdown(audit: Dict[str, Any]) -> str:
    observed = audit.get("observed") or {}
    lines = [
        "# ML Training Dataset Readiness Audit",
        "",
        f"- status: `{audit.get('status')}`",
        f"- dataset_build_ready: `{str(bool(audit.get('dataset_build_ready'))).lower()}`",
        f"- production_ml_ready: `{str(bool(audit.get('production_ml_ready'))).lower()}`",
        f"- latest_snapshot_trade_date: `{observed.get('latest_snapshot_trade_date') or '-'}`",
        f"- latest_snapshot_count: `{observed.get('latest_snapshot_count')}`",
        f"- eligible_full_market_snapshot_date_count: `{observed.get('eligible_full_market_snapshot_date_count')}`",
        f"- estimated_sample_count: `{observed.get('estimated_sample_count')}`",
        f"- blocking_codes: `{', '.join(audit.get('blocking_codes') or []) or '-'}`",
        "",
        "This audit is read-only. It does not train models or change production strategy logic.",
        "",
    ]
    return "\n".join(lines)


def _board_set(symbols: Iterable[str]) -> set:
    boards = set()
    for symbol in symbols:
        text_value = str(symbol or "")
        if text_value.startswith("30"):
            boards.add("chinext")
        elif text_value.startswith("68"):
            boards.add("star")
        elif text_value.startswith(("00", "60")):
            boards.add("main")
    return boards


def _block(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message}


def _normalize_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text_value = str(value or "").strip()
    for fmt, width in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(text_value[:width], fmt).date().isoformat()
        except ValueError:
            continue
    return text_value[:10]


def _date_span_days(start_date: str, end_date: str) -> int:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return 0
    if end < start:
        return 0
    return (end - start).days
