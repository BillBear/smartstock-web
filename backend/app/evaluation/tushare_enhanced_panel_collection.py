from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd


STOCK_DATE_ENDPOINTS = ["daily", "daily_basic", "adj_factor", "stk_limit", "suspend_d", "moneyflow", "moneyflow_hsgt"]
INDEX_ENDPOINTS = ["index_daily", "index_dailybasic"]
DEFAULT_ENDPOINTS = ["daily", "daily_basic", "adj_factor", "stk_limit", "suspend_d", "moneyflow", "index_daily"]
DEFAULT_INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000905.SH", "000852.SH"]


def collect_tushare_enhanced_panels(
    pro_client: Any,
    trade_dates: Iterable[Any],
    symbols: Iterable[Any] | None = None,
    endpoints: Iterable[str] | None = None,
    index_codes: Iterable[str] | None = None,
    sleep_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Collect read-only TuShare panels for selected historical dates."""
    dates = _normalize_dates(trade_dates)
    symbol_set = {_normalize_symbol(symbol) for symbol in (symbols or []) if _normalize_symbol(symbol)}
    selected_endpoints = list(endpoints or DEFAULT_ENDPOINTS)
    panels: Dict[str, pd.DataFrame] = {}
    endpoint_status: Dict[str, Dict[str, Any]] = {}
    for endpoint in selected_endpoints:
        if endpoint in INDEX_ENDPOINTS:
            frame, status = _collect_index_endpoint(
                pro_client,
                endpoint=endpoint,
                trade_dates=dates,
                index_codes=list(index_codes or DEFAULT_INDEX_CODES),
                sleep_seconds=sleep_seconds,
            )
        else:
            frame, status = _collect_stock_date_endpoint(
                pro_client,
                endpoint=endpoint,
                trade_dates=dates,
                symbols=symbol_set,
                sleep_seconds=sleep_seconds,
            )
        panels[endpoint] = frame
        endpoint_status[endpoint] = status
    return {
        "audit_type": "tushare_enhanced_panel_collection",
        "production_evidence": False,
        "strategy_impact": False,
        "summary": {
            "audit_type": "tushare_enhanced_panel_collection",
            "production_evidence": False,
            "strategy_impact": False,
            "trade_date_count": int(len(dates)),
            "min_trade_date": dates[0] if dates else "",
            "max_trade_date": dates[-1] if dates else "",
            "symbol_count": int(len(symbol_set)),
            "endpoint_count": int(len(selected_endpoints)),
        },
        "endpoint_status": endpoint_status,
        "panels": panels,
    }


def write_tushare_panel_collection_artifacts(collection: Dict[str, Any], output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "collection_summary.json"
    endpoint_path = root / "endpoint_status.json"
    summary = collection.get("summary") or {}
    endpoint_status = collection.get("endpoint_status") or {}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    endpoint_path.write_text(json.dumps(endpoint_status, ensure_ascii=False, indent=2), encoding="utf-8")
    paths: Dict[str, str] = {
        "summary": str(summary_path),
        "endpoint_status": str(endpoint_path),
    }
    for endpoint, frame in (collection.get("panels") or {}).items():
        path = root / f"{_artifact_stem(endpoint)}_panel.csv"
        if not isinstance(frame, pd.DataFrame):
            frame = pd.DataFrame()
        frame.to_csv(path, index=False)
        paths[endpoint] = str(path)
    return paths


def candidate_dates_and_symbols(candidate_df: pd.DataFrame) -> Dict[str, List[str]]:
    if candidate_df is None or candidate_df.empty:
        return {"trade_dates": [], "symbols": []}
    local = candidate_df.copy()
    if "trade_date" not in local.columns and "date" in local.columns:
        local["trade_date"] = local["date"]
    trade_dates = _normalize_dates(local.get("trade_date", []))
    symbols = sorted({_normalize_symbol(value) for value in local.get("symbol", []) if _normalize_symbol(value)})
    return {"trade_dates": trade_dates, "symbols": symbols}


def _collect_stock_date_endpoint(
    pro_client: Any,
    endpoint: str,
    trade_dates: List[str],
    symbols: set[str],
    sleep_seconds: float,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    method = getattr(pro_client, endpoint, None)
    if method is None:
        return pd.DataFrame(), _status("missing_method", 0, error="")
    frames = []
    errors = []
    for date in trade_dates:
        try:
            frame = method(trade_date=date.replace("-", ""))
            frame = _normalize_panel(frame)
            if symbols and "symbol" in frame.columns:
                frame = frame[frame["symbol"].isin(symbols)].copy()
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            errors.append(f"{date}: {exc}")
        _sleep(sleep_seconds)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if errors and combined.empty:
        return combined, _status("error", 0, error="; ".join(errors[:3]))
    if errors:
        return combined, _status("partial_error", len(combined), error="; ".join(errors[:3]), columns=combined.columns)
    return combined, _status("empty" if combined.empty else "available", len(combined), columns=combined.columns)


def _collect_index_endpoint(
    pro_client: Any,
    endpoint: str,
    trade_dates: List[str],
    index_codes: List[str],
    sleep_seconds: float,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    method = getattr(pro_client, endpoint, None)
    if method is None:
        return pd.DataFrame(), _status("missing_method", 0, error="")
    if not trade_dates:
        return pd.DataFrame(), _status("empty", 0, error="")
    frames = []
    errors = []
    start_date = trade_dates[0].replace("-", "")
    end_date = trade_dates[-1].replace("-", "")
    for code in index_codes:
        try:
            frame = method(ts_code=code, start_date=start_date, end_date=end_date)
            frame = _normalize_panel(frame)
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            errors.append(f"{code}: {exc}")
        _sleep(sleep_seconds)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if errors and combined.empty:
        return combined, _status("error", 0, error="; ".join(errors[:3]))
    if errors:
        return combined, _status("partial_error", len(combined), error="; ".join(errors[:3]), columns=combined.columns)
    return combined, _status("empty" if combined.empty else "available", len(combined), columns=combined.columns)


def _normalize_panel(frame: Any) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    local = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    if local.empty:
        return pd.DataFrame(columns=list(local.columns))
    local = local.copy()
    if "symbol" not in local.columns and "ts_code" in local.columns:
        local["symbol"] = local["ts_code"].map(_normalize_symbol)
    if "trade_date" in local.columns:
        local["trade_date"] = local["trade_date"].map(_normalize_date)
    return local


def _normalize_dates(values: Iterable[Any]) -> List[str]:
    normalized = []
    for value in values:
        date = _normalize_date(value)
        if date:
            normalized.append(date)
    return sorted(set(normalized))


def _normalize_date(value: Any) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return ""


def _artifact_stem(endpoint: str) -> str:
    mapping = {
        "daily_basic": "daily_basic",
        "adj_factor": "adj_factor",
        "stk_limit": "stk_limit",
        "suspend_d": "suspend",
        "index_daily": "index",
        "index_dailybasic": "index_dailybasic",
        "moneyflow": "moneyflow",
        "moneyflow_hsgt": "moneyflow_hsgt",
        "daily": "daily",
    }
    return mapping.get(endpoint, endpoint)


def _status(status: str, row_count: int, error: str = "", columns: Iterable[Any] | None = None) -> Dict[str, Any]:
    column_values = [] if columns is None else list(columns)
    return {
        "status": status,
        "row_count": int(row_count),
        "columns": [str(column) for column in column_values],
        "error": error,
    }


def _sleep(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(float(seconds))
