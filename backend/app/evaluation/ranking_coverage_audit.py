"""Read-only coverage audit for historical ranking evaluation inputs."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.evaluation.ranking_replay import _date_range, _normalize_date_value


def build_ranking_snapshot_coverage_audit(
    store,
    strategy_code: str,
    risk_level: str,
    start_date: str,
    end_date: str,
    horizons: Optional[Iterable[int]] = None,
    user_id: str = "default",
    as_of_date: Optional[str] = None,
    min_market_snapshot_count: int = 500,
    min_covered_dates: int = 30,
) -> Dict[str, Any]:
    """Explain why ranking evaluation coverage is sufficient or blocked.

    This audit only reads persisted snapshots. It does not regenerate candidates,
    fetch market data, or change strategy parameters.
    """
    requested_dates = _date_range(start_date, end_date)
    horizon_values = sorted({int(item) for item in (horizons or [3, 5, 10, 20]) if int(item) > 0})
    as_of = _parse_date(as_of_date or end_date)
    date_rows: List[Dict[str, Any]] = []

    for trade_date in requested_dates:
        pick_rows = _list_pick_snapshots(
            store=store,
            strategy_code=strategy_code,
            risk_level=risk_level,
            trade_date=trade_date,
            user_id=user_id,
        )
        market_snapshot = _latest_market_snapshot(store, trade_date, min_market_snapshot_count)
        complete_horizons, incomplete_horizons = _estimated_horizon_status(trade_date, horizon_values, as_of)
        market_trade_date = market_snapshot.get("trade_date") if market_snapshot else None
        row = {
            "trade_date": trade_date,
            "pick_snapshot_count": len(pick_rows),
            "pick_status": "present" if pick_rows else "missing",
            "market_snapshot_status": _market_snapshot_status(trade_date, market_trade_date),
            "market_snapshot_trade_date": market_trade_date,
            "market_snapshot_count": int(market_snapshot.get("snapshot_count") or 0) if market_snapshot else 0,
            "market_snapshot_quality_status": market_snapshot.get("quality_status") if market_snapshot else None,
            "market_snapshot_source": market_snapshot.get("source") if market_snapshot else None,
            "complete_horizons_estimate": complete_horizons,
            "incomplete_horizons_estimate": incomplete_horizons,
            "label_window_status_estimate": "complete" if not incomplete_horizons else "incomplete",
        }
        date_rows.append(row)

    pick_covered_dates = [row["trade_date"] for row in date_rows if row["pick_snapshot_count"] > 0]
    missing_pick_dates = [row["trade_date"] for row in date_rows if row["pick_snapshot_count"] <= 0]
    market_summary = {
        "same_day_count": sum(1 for row in date_rows if row["market_snapshot_status"] == "same_day"),
        "prior_only_count": sum(1 for row in date_rows if row["market_snapshot_status"] == "prior_snapshot"),
        "missing_count": sum(1 for row in date_rows if row["market_snapshot_status"] == "missing"),
    }
    incomplete_label_dates = [
        row["trade_date"] for row in date_rows
        if row["pick_snapshot_count"] > 0 and row["incomplete_horizons_estimate"]
    ]
    blocking_reasons = _blocking_reasons(
        covered_count=len(pick_covered_dates),
        min_covered_dates=min_covered_dates,
        market_summary=market_summary,
        incomplete_label_dates=incomplete_label_dates,
        requested_count=len(requested_dates),
    )

    return {
        "audit_schema_version": "1.0",
        "strategy_code": str(strategy_code or ""),
        "risk_level": str(risk_level or ""),
        "user_id": str(user_id or "default"),
        "start_date": _normalize_date_value(start_date) or str(start_date),
        "end_date": _normalize_date_value(end_date) or str(end_date),
        "as_of_date": as_of.isoformat(),
        "horizons": horizon_values,
        "requested_date_count": len(requested_dates),
        "pick_covered_date_count": len(pick_covered_dates),
        "missing_pick_date_count": len(missing_pick_dates),
        "missing_pick_dates": missing_pick_dates,
        "market_snapshot_summary": market_summary,
        "incomplete_label_date_count": len(incomplete_label_dates),
        "incomplete_label_dates": incomplete_label_dates,
        "coverage_status": _coverage_status(requested_dates, pick_covered_dates),
        "production_evidence_ready": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "date_rows": date_rows,
    }


def write_ranking_snapshot_coverage_audit(path: str | Path, audit: Dict[str, Any]) -> None:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _list_pick_snapshots(store, strategy_code: str, risk_level: str, trade_date: str, user_id: str) -> List[Dict[str, Any]]:
    if not store or not hasattr(store, "list_pick_snapshots"):
        return []
    try:
        rows = store.list_pick_snapshots(
            strategy_code=strategy_code,
            risk_level=risk_level,
            trade_date=trade_date,
            user_id=user_id,
        )
    except TypeError:
        rows = store.list_pick_snapshots(
            strategy_code=strategy_code,
            risk_level=risk_level,
            trade_date=trade_date,
        )
    return list(rows or [])


def _latest_market_snapshot(store, trade_date: str, min_count: int) -> Dict[str, Any]:
    if not store or not hasattr(store, "get_latest_valid_market_snapshot"):
        return {}
    try:
        snapshot = store.get_latest_valid_market_snapshot(trade_date=trade_date, min_count=min_count)
    except TypeError:
        snapshot = store.get_latest_valid_market_snapshot(trade_date=trade_date)
    return dict(snapshot or {})


def _market_snapshot_status(trade_date: str, market_trade_date: Any) -> str:
    normalized_market_date = _normalize_date_value(market_trade_date)
    if not normalized_market_date:
        return "missing"
    if normalized_market_date == trade_date:
        return "same_day"
    if normalized_market_date < trade_date:
        return "prior_snapshot"
    return "future_snapshot"


def _estimated_horizon_status(trade_date: str, horizons: List[int], as_of: date) -> tuple[List[int], List[int]]:
    complete: List[int] = []
    incomplete: List[int] = []
    start = _parse_date(trade_date)
    for horizon in horizons:
        required_date = _add_weekdays(start, int(horizon))
        if required_date <= as_of:
            complete.append(int(horizon))
        else:
            incomplete.append(int(horizon))
    return complete, incomplete


def _add_weekdays(start: date, count: int) -> date:
    remaining = max(0, int(count))
    cursor = start
    while remaining > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor


def _blocking_reasons(
    covered_count: int,
    min_covered_dates: int,
    market_summary: Dict[str, int],
    incomplete_label_dates: List[str],
    requested_count: int,
) -> List[str]:
    reasons: List[str] = []
    if requested_count <= 0:
        reasons.append("requested_dates_empty")
    if covered_count <= 0:
        reasons.append("pick_snapshots_empty")
    if covered_count < int(min_covered_dates or 30):
        reasons.append(f"covered_dates_below_{int(min_covered_dates or 30)}")
    if int(market_summary.get("missing_count") or 0) > 0:
        reasons.append("market_snapshots_missing")
    if incomplete_label_dates:
        reasons.append("label_windows_incomplete")
    return reasons


def _coverage_status(requested_dates: List[str], pick_covered_dates: List[str]) -> str:
    if not requested_dates or not pick_covered_dates:
        return "blocked"
    if len(pick_covered_dates) == len(requested_dates):
        return "complete"
    return "partial"


def _parse_date(value: Any) -> date:
    normalized = _normalize_date_value(value)
    if not normalized:
        raise ValueError(f"invalid date: {value}")
    return datetime.strptime(normalized, "%Y-%m-%d").date()
