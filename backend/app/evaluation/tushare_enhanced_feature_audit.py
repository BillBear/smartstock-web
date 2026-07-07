from __future__ import annotations

from typing import Any, Dict, Iterable

import pandas as pd


DEFAULT_ENDPOINTS = [
    "daily_basic",
    "adj_factor",
    "trade_cal",
    "stk_limit",
    "suspend_d",
    "index_daily",
    "index_dailybasic",
    "moneyflow_hsgt",
    "moneyflow",
]


def audit_tushare_endpoint_availability(
    client: Any,
    sample_date: str,
    sample_ts_code: str = "000001.SZ",
    endpoints: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Probe TuShare-like client methods without raising endpoint errors."""
    normalized_date = _normalize_date(sample_date)
    trade_date = normalized_date.replace("-", "")
    summary: Dict[str, Any] = {
        "audit_type": "tushare_endpoint_availability",
        "sample_date": normalized_date,
        "sample_ts_code": sample_ts_code,
        "endpoints": {},
    }
    for endpoint in list(endpoints or DEFAULT_ENDPOINTS):
        method = getattr(client, endpoint, None)
        if method is None:
            summary["endpoints"][endpoint] = {
                "status": "missing_method",
                "row_count": 0,
                "columns": [],
                "error": "",
            }
            continue
        try:
            df = method(trade_date=trade_date, ts_code=sample_ts_code)
        except Exception as exc:  # endpoint probes must not interrupt audits
            summary["endpoints"][endpoint] = {
                "status": "error",
                "row_count": 0,
                "columns": [],
                "error": str(exc),
            }
            continue
        frame = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df or [])
        summary["endpoints"][endpoint] = {
            "status": "empty" if frame.empty else "available",
            "row_count": int(len(frame)),
            "columns": [str(column) for column in frame.columns],
            "error": "",
        }
    return summary


def _normalize_date(value: Any) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")
