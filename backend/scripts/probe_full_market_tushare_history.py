#!/usr/bin/env python3
"""Probe TuShare permissions and historical freshness without exposing credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_ENDPOINTS = (
    "daily",
    "daily_basic",
    "adj_factor",
    "stk_limit",
    "suspend_d",
    "moneyflow",
    "index_daily",
    "index_dailybasic",
)
STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_status,"
    "list_date,delist_date,is_hs"
)


def probe_tushare_history(
    pro: Any,
    *,
    start_date: str,
    end_date: str,
    endpoints: Iterable[str] = DEFAULT_ENDPOINTS,
) -> dict[str, Any]:
    calendar = pro.query("trade_cal", exchange="SSE", start_date=start_date, end_date=end_date)
    open_dates = _open_dates(calendar)
    if not open_dates:
        raise RuntimeError("trade_cal returned no open dates for requested range")
    earliest, latest = open_dates[0], open_dates[-1]
    stock_basic = fetch_stock_basic_history(pro)
    endpoint_results = {
        endpoint: _probe_endpoint(pro, endpoint, earliest, latest)
        for endpoint in endpoints
    }
    return {
        "requested_date_range": [str(start_date), str(end_date)],
        "open_date_range": [earliest, latest],
        "open_date_count": len(open_dates),
        "stock_basic": _stock_basic_status(stock_basic),
        "endpoints": endpoint_results,
    }


def fetch_stock_basic_history(pro: Any) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for list_status in ("L", "D", "P"):
        frame = _safe_query(
            pro,
            "stock_basic",
            list_status=list_status,
            fields=STOCK_BASIC_FIELDS,
        ).copy()
        if "list_status" not in frame.columns:
            frame["list_status"] = list_status
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _stock_basic_status(frame: pd.DataFrame) -> dict[str, Any]:
    result = _status_for_frames([frame])
    statuses = frame.get("list_status", pd.Series(dtype=str)).astype(str).str.upper()
    result["list_status_counts"] = {
        key: int(value) for key, value in statuses.value_counts().sort_index().items()
    }
    delisted = statuses.eq("D")
    valid_delist = frame.get("delist_date", pd.Series("", index=frame.index)).fillna("").astype(str).str.strip().ne("")
    result["historical_intervals_ready"] = bool((~delisted | valid_delist).all())
    result["delisted_without_delist_date_count"] = int((delisted & ~valid_delist).sum())
    return result


def _probe_endpoint(pro: Any, endpoint: str, earliest: str, latest: str) -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    returned_dates: list[str] = []
    scope_mismatches: list[dict[str, str]] = []
    try:
        for date in dict.fromkeys((earliest, latest)):
            frame = _safe_query(pro, endpoint, **_endpoint_params(endpoint, date))
            frames.append(frame)
            if not frame.empty:
                frame_dates = _returned_dates(frame, date)
                returned_dates.extend(frame_dates)
                if frame_dates != [date]:
                    scope_mismatches.append(
                        {"requested_date": date, "returned_min": min(frame_dates), "returned_max": max(frame_dates)}
                    )
    except Exception as exc:
        message = str(exc)
        status = "permission_denied" if _permission_error(message) else "query_failed"
        return {"status": status, "error_type": type(exc).__name__, "message": _sanitise(message)}
    result = _status_for_frames(frames)
    if scope_mismatches:
        result["status"] = "query_scope_mismatch"
        result["scope_mismatches"] = scope_mismatches
    result["earliest_returned_date"] = min(returned_dates) if returned_dates else None
    result["latest_returned_date"] = max(returned_dates) if returned_dates else None
    return result


def _safe_query(pro: Any, endpoint: str, **kwargs: Any) -> pd.DataFrame:
    frame = pro.query(endpoint, **kwargs)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)


def _endpoint_params(endpoint: str, date: str) -> dict[str, str]:
    if endpoint in {"index_daily", "index_dailybasic"}:
        return {"ts_code": "000001.SH", "start_date": date, "end_date": date}
    return {"trade_date": date}


def _open_dates(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "cal_date" not in frame.columns:
        return []
    opened = frame if "is_open" not in frame.columns else frame[pd.to_numeric(frame["is_open"], errors="coerce").eq(1)]
    return sorted(opened["cal_date"].astype(str).str.replace("-", "", regex=False).unique().tolist())


def _returned_dates(frame: pd.DataFrame, fallback: str) -> list[str]:
    for column in ("trade_date", "cal_date", "suspend_date"):
        if column in frame.columns and frame[column].notna().any():
            return sorted(
                frame.loc[frame[column].notna(), column]
                .astype(str)
                .str.replace("-", "", regex=False)
                .unique()
                .tolist()
            )
    return [fallback]


def _status_for_frames(frames: list[pd.DataFrame]) -> dict[str, Any]:
    rows = sum(len(frame) for frame in frames)
    return {"status": "valid_with_rows" if rows else "valid_but_empty", "sample_row_count": int(rows)}


def _permission_error(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in ("permission", "denied", "权限", "积分"))


def _sanitise(message: str) -> str:
    token = os.environ.get("TUSHARE_TOKEN", "")
    return message.replace(token, "[redacted]") if token else message


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stock-basic-output", type=Path)
    args = parser.parse_args()
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        parser.error("TUSHARE_TOKEN is not configured")
    import tushare as ts

    pro = ts.pro_api(token)
    report = probe_tushare_history(pro, start_date=args.start_date, end_date=args.end_date)
    _write_json_atomic(args.output, report)
    if args.stock_basic_output:
        args.stock_basic_output.parent.mkdir(parents=True, exist_ok=True)
        fetch_stock_basic_history(pro).to_parquet(args.stock_basic_output, index=False, compression="zstd")
    print(json.dumps({"output": str(args.output), "open_date_range": report["open_date_range"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
