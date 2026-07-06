from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd


DEFAULT_RETURN_WINDOWS = [1, 5, 10, 20, 60]


def build_full_market_feature_panel(
    history_df: pd.DataFrame,
    min_symbols_per_date: int = 5000,
    return_windows: Iterable[int] | None = None,
) -> pd.DataFrame:
    """Build read-only cross-sectional full-market feature ranks."""
    df = _normalize_history(history_df)
    if df.empty:
        return pd.DataFrame()
    windows = sorted({int(window) for window in (return_windows or DEFAULT_RETURN_WINDOWS) if int(window) > 0})
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    for window in windows:
        df[f"return_{window}d_pct"] = df.groupby("symbol")["close"].pct_change(window) * 100.0
    df = _add_interval_features(df)
    feature_rows = df[df["return_1d_pct"].notna()].copy()
    feature_rows = _filter_full_market_dates(feature_rows, min_symbols_per_date=min_symbols_per_date)
    if feature_rows.empty:
        return feature_rows.reset_index(drop=True)
    rank_columns = [
        *[f"return_{window}d_pct" for window in windows if f"return_{window}d_pct" in feature_rows.columns],
        "amount",
        "turnover_rate",
        "amount_ratio_5_20",
        "turnover_ratio_5_20",
    ]
    for column in rank_columns:
        if column in feature_rows.columns:
            feature_rows[f"{_rank_prefix(column)}_rank"] = _date_rank(feature_rows, column)
    return feature_rows.reset_index(drop=True)


def summarize_full_market_feature_panel(panel: pd.DataFrame, min_symbols_per_date: int) -> Dict[str, Any]:
    if panel is None or panel.empty:
        return {
            "status": "empty",
            "row_count": 0,
            "date_count": 0,
            "symbol_count": 0,
            "min_symbols_per_date": int(min_symbols_per_date),
            "full_market_feature_scope": False,
        }
    counts = panel.groupby("trade_date")["symbol"].nunique()
    return {
        "status": "completed",
        "row_count": int(len(panel)),
        "date_count": int(panel["trade_date"].nunique()),
        "symbol_count": int(panel["symbol"].nunique()),
        "min_date": str(panel["trade_date"].min()),
        "max_date": str(panel["trade_date"].max()),
        "min_symbols_per_date": int(min_symbols_per_date),
        "min_actual_symbols_per_date": int(counts.min()) if not counts.empty else 0,
        "max_actual_symbols_per_date": int(counts.max()) if not counts.empty else 0,
        "full_market_feature_scope": bool(not counts.empty and counts.min() >= int(min_symbols_per_date)),
    }


def write_full_market_feature_panel_artifacts(
    panel: pd.DataFrame,
    output_csv: str | Path,
    min_symbols_per_date: int,
    summary_json: str | Path | None = None,
) -> Dict[str, str]:
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output_path, index=False)
    paths = {"feature_panel": str(output_path)}
    summary = summarize_full_market_feature_panel(panel, min_symbols_per_date=min_symbols_per_date)
    if summary_json:
        summary_path = Path(summary_json)
    else:
        summary_path = output_path.with_suffix(".summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["summary"] = str(summary_path)
    return paths


def _normalize_history(history_df: pd.DataFrame | None) -> pd.DataFrame:
    if history_df is None or history_df.empty:
        return pd.DataFrame()
    df = history_df.copy()
    if "trade_date" not in df.columns and "date" in df.columns:
        df["trade_date"] = df["date"]
    required = {"trade_date", "symbol", "close"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["trade_date"].notna()].copy()
    df["symbol"] = df["symbol"].map(_normalize_symbol)
    df = df[df["symbol"] != ""].copy()
    for column in ["open", "high", "low", "close", "amount", "volume", "turnover_rate"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "amount" not in df.columns:
        df["amount"] = pd.NA
    if "turnover_rate" not in df.columns:
        df["turnover_rate"] = pd.NA
    df = df[df["close"].notna()].copy()
    return df.drop_duplicates(["trade_date", "symbol"], keep="last").reset_index(drop=True)


def _add_interval_features(df: pd.DataFrame) -> pd.DataFrame:
    local = df.copy()
    for window in [5, 20]:
        local[f"amount_ma_{window}"] = local.groupby("symbol")["amount"].transform(lambda value: value.rolling(window, min_periods=1).mean())
        local[f"turnover_ma_{window}"] = local.groupby("symbol")["turnover_rate"].transform(lambda value: value.rolling(window, min_periods=1).mean())
    local["amount_ratio_5_20"] = local["amount_ma_5"] / local["amount_ma_20"]
    local["turnover_ratio_5_20"] = local["turnover_ma_5"] / local["turnover_ma_20"]
    return local


def _filter_full_market_dates(df: pd.DataFrame, min_symbols_per_date: int) -> pd.DataFrame:
    counts = df.groupby("trade_date")["symbol"].nunique()
    valid_dates = set(counts[counts >= int(min_symbols_per_date)].index)
    return df[df["trade_date"].isin(valid_dates)].copy()


def _date_rank(df: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(df[column], errors="coerce")
    return values.groupby(df["trade_date"]).rank(pct=True, method="average")


def _rank_prefix(column: str) -> str:
    if column == "turnover_rate":
        return "turnover"
    if column.endswith("_pct"):
        return column[:-4]
    return column


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return text
