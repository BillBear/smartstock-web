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


REQUIRED_ENDPOINTS = (
    "stock_basic",
    "namechange",
    "trade_cal",
    "daily",
    "daily_basic",
    "adj_factor",
    "stk_limit",
    "suspend_d",
    "index_daily",
    "index_dailybasic",
    "index_classify",
    "index_member_all",
)
EXPERIMENTAL_ENDPOINTS = (
    "moneyflow",
    "margin",
    "margin_detail",
    "top_list",
    "top_inst",
    "block_trade",
    "fina_indicator",
    "income",
    "balancesheet",
    "cashflow",
    "forecast",
    "express",
    "stk_holdernumber",
    "top10_holders",
    "top10_floatholders",
    "hk_hold",
)
DEFAULT_ENDPOINTS = REQUIRED_ENDPOINTS + EXPERIMENTAL_ENDPOINTS
STOCK_BASIC_FIELDS = (
    "ts_code,symbol,name,area,industry,market,exchange,list_status,"
    "list_date,delist_date,is_hs"
)

_TIMESTAMP_FIELDS = {
    "stock_basic": ("list_date", "delist_date"),
    "namechange": ("start_date", "end_date", "ann_date"),
    "trade_cal": ("cal_date",),
    "daily": ("trade_date",),
    "daily_basic": ("trade_date",),
    "adj_factor": ("trade_date",),
    "stk_limit": ("trade_date",),
    "suspend_d": ("trade_date", "suspend_date", "resume_date"),
    "moneyflow": ("trade_date",),
    "margin": ("trade_date",),
    "margin_detail": ("trade_date",),
    "top_list": ("trade_date",),
    "top_inst": ("trade_date",),
    "block_trade": ("trade_date",),
    "index_daily": ("trade_date",),
    "index_dailybasic": ("trade_date",),
    "index_classify": (),
    "index_member_all": ("in_date", "out_date"),
    "fina_indicator": ("ann_date", "end_date"),
    "income": ("ann_date", "f_ann_date", "end_date"),
    "balancesheet": ("ann_date", "f_ann_date", "end_date"),
    "cashflow": ("ann_date", "f_ann_date", "end_date"),
    "forecast": ("ann_date", "first_ann_date", "end_date"),
    "express": ("ann_date", "end_date"),
    "stk_holdernumber": ("ann_date", "enddate"),
    "top10_holders": ("ann_date", "end_date"),
    "top10_floatholders": ("ann_date", "end_date"),
    "hk_hold": ("trade_date",),
}
_STATIC_ENDPOINTS = {"stock_basic", "index_classify", "index_member_all"}
_WINDOW_ENDPOINTS = {
    "namechange",
    "fina_indicator",
    "income",
    "balancesheet",
    "cashflow",
    "forecast",
    "express",
    "stk_holdernumber",
    "top10_holders",
    "top10_floatholders",
}
_SYMBOL_COLUMNS = ("ts_code", "symbol", "con_code")


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
    endpoint_results = {}
    for endpoint in dict.fromkeys(endpoints):
        if endpoint == "trade_cal":
            endpoint_results[endpoint] = _probe_trade_calendar(calendar, open_dates)
        elif endpoint == "stock_basic":
            endpoint_results[endpoint] = _stock_basic_status(stock_basic)
        else:
            endpoint_results[endpoint] = _probe_endpoint(
                pro,
                endpoint,
                earliest,
                latest,
                start_date=start_date,
                end_date=end_date,
            )
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
    result = _result_for_frames(
        [frame],
        endpoint="stock_basic",
        requested_dates=(),
    )
    statuses = frame.get("list_status", pd.Series(dtype=str)).astype(str).str.upper()
    result["list_status_counts"] = {
        key: int(value) for key, value in statuses.value_counts().sort_index().items()
    }
    delisted = statuses.eq("D")
    valid_delist = frame.get("delist_date", pd.Series("", index=frame.index)).fillna("").astype(str).str.strip().ne("")
    result["historical_intervals_ready"] = bool((~delisted | valid_delist).all())
    result["delisted_without_delist_date_count"] = int((delisted & ~valid_delist).sum())
    return result


def _probe_trade_calendar(frame: pd.DataFrame, open_dates: list[str]) -> dict[str, Any]:
    result = _result_for_frames(
        [frame],
        endpoint="trade_cal",
        requested_dates=tuple(open_dates[:1] + open_dates[-1:]),
    )
    result["earliest_date"] = min(open_dates) if open_dates else None
    result["latest_date"] = max(open_dates) if open_dates else None
    result["earliest_returned_date"] = result["earliest_date"]
    result["latest_returned_date"] = result["latest_date"]
    return result


def _probe_endpoint(
    pro: Any,
    endpoint: str,
    earliest: str,
    latest: str,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    returned_dates: list[str] = []
    scope_mismatches: list[dict[str, str]] = []
    requested_dates = () if endpoint in (_STATIC_ENDPOINTS | _WINDOW_ENDPOINTS) else tuple(dict.fromkeys((earliest, latest)))
    try:
        probe_dates = requested_dates or (None,)
        for trade_date in probe_dates:
            frame = _safe_query(
                pro,
                endpoint,
                **_endpoint_params(endpoint, trade_date, start_date=start_date, end_date=end_date),
            )
            frames.append(frame)
            if not frame.empty:
                frame_dates = _returned_dates(frame)
                returned_dates.extend(frame_dates)
                if trade_date and frame_dates and frame_dates != [trade_date]:
                    scope_mismatches.append(
                        {"requested_date": trade_date, "returned_min": min(frame_dates), "returned_max": max(frame_dates)}
                    )
    except Exception as exc:
        message = str(exc)
        status = _error_status(message)
        return {
            "status": status,
            "error_code": status,
            "error_type": type(exc).__name__,
            "message": _sanitise(message),
            "row_count": 0,
            "sample_row_count": 0,
            "earliest_date": None,
            "latest_date": None,
            "earliest_returned_date": None,
            "latest_returned_date": None,
            "required_timestamp_fields": list(_TIMESTAMP_FIELDS.get(endpoint, ())),
            "timestamp_contract_satisfied": False,
            "date_coverage": _date_coverage(requested_dates, ()),
            "symbol_coverage": _symbol_coverage(frames),
        }
    result = _result_for_frames(frames, endpoint=endpoint, requested_dates=requested_dates)
    if scope_mismatches:
        result["status"] = "query_scope_mismatch"
        result["error_code"] = "query_scope_mismatch"
        result["scope_mismatches"] = scope_mismatches
    result["earliest_date"] = min(returned_dates) if returned_dates else None
    result["latest_date"] = max(returned_dates) if returned_dates else None
    result["earliest_returned_date"] = result["earliest_date"]
    result["latest_returned_date"] = result["latest_date"]
    return result


def _safe_query(pro: Any, endpoint: str, **kwargs: Any) -> pd.DataFrame:
    frame = pro.query(endpoint, **kwargs)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)


def _endpoint_params(
    endpoint: str,
    trade_date: str | None,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, str]:
    if endpoint in {"index_daily", "index_dailybasic"}:
        return {"ts_code": "000001.SH", "start_date": trade_date or start_date, "end_date": trade_date or end_date}
    if endpoint == "namechange":
        return {"start_date": start_date, "end_date": end_date}
    if endpoint == "index_classify":
        return {"level": "L1", "src": "SW2021"}
    if endpoint == "index_member_all":
        return {"l1_code": "801010.SI"}
    if endpoint in {"fina_indicator", "income", "balancesheet", "cashflow", "forecast", "express", "stk_holdernumber", "top10_holders", "top10_floatholders"}:
        return {"ts_code": "000001.SZ", "start_date": start_date, "end_date": end_date}
    if endpoint == "top_inst":
        return {"trade_date": trade_date or end_date}
    return {"trade_date": trade_date or end_date}


def _open_dates(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "cal_date" not in frame.columns:
        return []
    opened = frame if "is_open" not in frame.columns else frame[pd.to_numeric(frame["is_open"], errors="coerce").eq(1)]
    return sorted(opened["cal_date"].astype(str).str.replace("-", "", regex=False).unique().tolist())


def _returned_dates(frame: pd.DataFrame) -> list[str]:
    for column in ("trade_date", "cal_date", "suspend_date", "ann_date", "f_ann_date", "in_date"):
        if column in frame.columns and frame[column].notna().any():
            return sorted(
                frame.loc[frame[column].notna(), column]
                .astype(str)
                .str.replace("-", "", regex=False)
                .unique()
                .tolist()
            )
    return []


def _status_for_frames(frames: list[pd.DataFrame]) -> dict[str, Any]:
    rows = sum(len(frame) for frame in frames)
    return {"status": "valid_with_rows" if rows else "valid_but_empty", "sample_row_count": int(rows)}


def _result_for_frames(
    frames: list[pd.DataFrame],
    *,
    endpoint: str,
    requested_dates: tuple[str, ...],
) -> dict[str, Any]:
    result = _status_for_frames(frames)
    returned_dates = tuple(sorted({value for frame in frames for value in _returned_dates(frame)}))
    required_timestamp_fields = tuple(_TIMESTAMP_FIELDS.get(endpoint, ()))
    fields = {str(column) for frame in frames for column in frame.columns}
    result.update(
        {
            "error_code": None,
            "row_count": result["sample_row_count"],
            "required_timestamp_fields": list(required_timestamp_fields),
            "timestamp_contract_satisfied": (
                not required_timestamp_fields or any(field in fields for field in required_timestamp_fields)
            ),
            "date_coverage": _date_coverage(requested_dates, returned_dates),
            "symbol_coverage": _symbol_coverage(frames),
        }
    )
    return result


def _date_coverage(requested_dates: tuple[str, ...], returned_dates: tuple[str, ...]) -> dict[str, Any]:
    requested = tuple(sorted(set(requested_dates)))
    returned = tuple(sorted(set(returned_dates)))
    matched = len(set(requested) & set(returned))
    return {
        "requested_count": len(requested),
        "returned_count": len(returned),
        "matched_count": matched,
        "fraction": (matched / len(requested)) if requested else None,
    }


def _symbol_coverage(frames: list[pd.DataFrame]) -> dict[str, int]:
    symbols = set()
    for frame in frames:
        for column in _SYMBOL_COLUMNS:
            if column in frame.columns:
                symbols.update(value for value in frame[column].dropna().astype(str) if value)
                break
    return {"unique_symbol_count": len(symbols)}


def _permission_error(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in ("permission", "denied", "权限", "积分"))


def _error_status(message: str) -> str:
    if _permission_error(message):
        return "permission_denied"
    lowered = message.lower()
    if any(term in lowered for term in ("正确的接口名", "invalid endpoint", "unknown api", "not support api")):
        return "invalid_endpoint"
    return "request_failed"


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
