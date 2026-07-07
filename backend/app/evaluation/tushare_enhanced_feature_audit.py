from __future__ import annotations

from typing import Any, Dict, Iterable, List

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


def build_tushare_enhanced_feature_panel(
    base_panel: pd.DataFrame,
    daily_basic_panel: pd.DataFrame | None = None,
    adj_factor_panel: pd.DataFrame | None = None,
    stk_limit_panel: pd.DataFrame | None = None,
    suspend_panel: pd.DataFrame | None = None,
    index_panel: pd.DataFrame | None = None,
    moneyflow_panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a read-only pre-signal feature panel from optional TuShare panels."""
    panel = _normalize_symbol_date_panel(base_panel)
    if panel.empty:
        return panel
    panel = _merge_optional_panel(
        panel,
        daily_basic_panel,
        [
            "turnover_rate",
            "turnover_rate_f",
            "volume_ratio",
            "pe",
            "pe_ttm",
            "pb",
            "ps",
            "ps_ttm",
            "dv_ratio",
            "dv_ttm",
            "total_share",
            "float_share",
            "free_share",
            "total_mv",
            "circ_mv",
        ],
    )
    panel = _merge_optional_panel(panel, adj_factor_panel, ["adj_factor"])
    panel = _merge_optional_panel(panel, stk_limit_panel, ["up_limit", "down_limit"])
    panel = _merge_suspend_flags(panel, suspend_panel)
    panel = _merge_optional_panel(
        panel,
        moneyflow_panel,
        [
            "net_mf_amount",
            "buy_lg_amount",
            "buy_elg_amount",
            "sell_lg_amount",
            "sell_elg_amount",
        ],
    )
    panel = _attach_index_context(panel, index_panel)
    panel = _attach_daily_basic_features(panel)
    panel = _attach_adjusted_return_features(panel)
    panel = _attach_limit_features(panel)
    panel = _attach_moneyflow_features(panel)
    return panel.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _normalize_date(value: Any) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _normalize_symbol_date_panel(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "symbol" not in local.columns and "ts_code" in local.columns:
        local["symbol"] = local["ts_code"]
    if "trade_date" not in local.columns and "date" in local.columns:
        local["trade_date"] = local["date"]
    if "symbol" not in local.columns or "trade_date" not in local.columns:
        return pd.DataFrame()
    local["symbol"] = local["symbol"].map(_normalize_symbol)
    local["trade_date"] = local["trade_date"].map(_normalize_date)
    local = local[(local["symbol"] != "") & (local["trade_date"] != "")].copy()
    return local


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return text


def _merge_optional_panel(panel: pd.DataFrame, optional: pd.DataFrame | None, columns: List[str]) -> pd.DataFrame:
    other = _normalize_symbol_date_panel(optional)
    if other.empty:
        for column in columns:
            if column not in panel.columns:
                panel[column] = pd.NA
        return panel
    keep = ["symbol", "trade_date"] + [column for column in columns if column in other.columns]
    if len(keep) <= 2:
        return panel
    slim = other[keep].drop_duplicates(["symbol", "trade_date"], keep="last")
    overlapping = [column for column in keep[2:] if column in panel.columns]
    if overlapping:
        panel = panel.drop(columns=overlapping)
    return panel.merge(slim, on=["symbol", "trade_date"], how="left")


def _merge_suspend_flags(panel: pd.DataFrame, suspend_panel: pd.DataFrame | None) -> pd.DataFrame:
    other = _normalize_symbol_date_panel(suspend_panel)
    if other.empty:
        panel["suspend_risk_flag"] = False
        return panel
    flags = other[["symbol", "trade_date"]].drop_duplicates().copy()
    flags["suspend_risk_flag"] = True
    merged = panel.merge(flags, on=["symbol", "trade_date"], how="left")
    merged["suspend_risk_flag"] = merged["suspend_risk_flag"].eq(True)
    return merged


def _attach_daily_basic_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    for column in [
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_mv",
        "circ_mv",
        "free_share",
    ]:
        if column in local.columns:
            local[column] = _num(local[column])
    for column in ["turnover_rate", "turnover_rate_f", "volume_ratio", "pe_ttm", "pb", "total_mv", "circ_mv"]:
        if column in local.columns:
            local[f"{column}_rank"] = _date_pct_rank(local, column)
    if "turnover_rate" in local.columns:
        grouped = local.sort_values(["symbol", "trade_date"]).groupby("symbol")["turnover_rate"]
        avg_5 = grouped.transform(lambda values: values.rolling(5, min_periods=1).mean())
        avg_20 = grouped.transform(lambda values: values.rolling(20, min_periods=1).mean())
        local["turnover_ratio_5_20"] = avg_5 / avg_20.replace(0, pd.NA)
        local["turnover_persistence_5d"] = grouped.transform(lambda values: values.diff().gt(0).rolling(5, min_periods=1).sum())
    return local


def _attach_adjusted_return_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    if "close" not in local.columns:
        return local
    local["close"] = _num(local["close"])
    if "adj_factor" in local.columns:
        local["adj_factor"] = _num(local["adj_factor"]).fillna(1.0)
    else:
        local["adj_factor"] = 1.0
    local = local.sort_values(["symbol", "trade_date"]).copy()
    local["adj_close"] = local["close"] * local["adj_factor"]
    grouped = local.groupby("symbol")["adj_close"]
    for horizon in [5, 20, 60]:
        column = f"adj_return_{horizon}d_pct"
        local[column] = grouped.pct_change(horizon) * 100.0
        local[f"adj_return_{horizon}d_rank"] = _date_pct_rank(local, column)
    return local


def _attach_limit_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    if not {"close", "up_limit", "down_limit"}.issubset(local.columns):
        local["distance_to_up_limit_pct"] = pd.NA
        local["distance_to_down_limit_pct"] = pd.NA
        local["hit_limit_up_today"] = False
        return local
    close = _num(local["close"])
    up = _num(local["up_limit"])
    down = _num(local["down_limit"])
    local["distance_to_up_limit_pct"] = ((up - close) / close.replace(0, pd.NA)) * 100.0
    local["distance_to_down_limit_pct"] = ((close - down) / close.replace(0, pd.NA)) * 100.0
    local["hit_limit_up_today"] = close.ge(up * 0.999)
    local["near_limit_up_3pct"] = local["distance_to_up_limit_pct"].le(3.0)
    return local


def _attach_moneyflow_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    for column in ["net_mf_amount", "buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"]:
        if column in local.columns:
            local[column] = _num(local[column])
            local[f"{column}_rank"] = _date_pct_rank(local, column)
    if {"net_mf_amount", "buy_lg_amount", "buy_elg_amount"}.issubset(local.columns):
        positive = local["buy_lg_amount"].fillna(0.0) + local["buy_elg_amount"].fillna(0.0)
        local["main_net_inflow_ratio"] = local["net_mf_amount"] / positive.replace(0, pd.NA)
        local["main_net_inflow_ratio_rank"] = _date_pct_rank(local, "main_net_inflow_ratio")
    return local


def _attach_index_context(panel: pd.DataFrame, index_panel: pd.DataFrame | None) -> pd.DataFrame:
    if index_panel is None or index_panel.empty:
        return panel
    local_index = index_panel.copy()
    if "trade_date" not in local_index.columns:
        return panel
    local_index["trade_date"] = local_index["trade_date"].map(_normalize_date)
    market_columns = [column for column in ["index_return_5d", "index_return_20d", "index_volatility_20d"] if column in local_index.columns]
    if not market_columns:
        return panel
    context = local_index[["trade_date"] + market_columns].drop_duplicates("trade_date", keep="last")
    return panel.merge(context, on="trade_date", how="left")


def _date_pct_rank(df: pd.DataFrame, column: str) -> pd.Series:
    if "trade_date" not in df.columns or column not in df.columns:
        return pd.Series(pd.NA, index=df.index)
    values = _num(df[column])
    return values.groupby(df["trade_date"]).rank(method="average", pct=True)


def _num(values: Any) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")
