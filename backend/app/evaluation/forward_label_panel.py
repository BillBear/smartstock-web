from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd


DEFAULT_HORIZONS = [3, 5, 10, 20]


def build_forward_label_panel(
    history_df: pd.DataFrame,
    horizons: Iterable[int] | None = None,
    take_profit_pct: float = 10.0,
    stop_loss_pct: float = -6.0,
    strong_return_pct: float = 5.0,
    limit_threshold_pct: float = 9.8,
) -> pd.DataFrame:
    """Build forward labels using explicit future trading rows only."""
    df = _normalize_history(history_df)
    if df.empty:
        return pd.DataFrame()
    local = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    horizon_values = sorted({int(value) for value in (horizons or DEFAULT_HORIZONS) if int(value) > 0})
    labeled_frames = []
    for _, rows in local.groupby("symbol", sort=True):
        labeled_frames.append(
            _label_symbol_rows(
                rows.reset_index(drop=True),
                horizons=horizon_values,
                take_profit_pct=float(take_profit_pct),
                stop_loss_pct=float(stop_loss_pct),
                strong_return_pct=float(strong_return_pct),
                limit_threshold_pct=float(limit_threshold_pct),
            )
        )
    return pd.concat(labeled_frames, ignore_index=True) if labeled_frames else pd.DataFrame()


def summarize_forward_label_panel(panel: pd.DataFrame, horizons: Iterable[int] | None = None) -> Dict[str, Any]:
    horizon_values = sorted({int(value) for value in (horizons or DEFAULT_HORIZONS) if int(value) > 0})
    summary: Dict[str, Any] = {
        "status": "completed" if panel is not None and not panel.empty else "empty",
        "row_count": int(len(panel)) if panel is not None else 0,
        "date_count": int(panel["trade_date"].nunique()) if panel is not None and not panel.empty else 0,
        "symbol_count": int(panel["symbol"].nunique()) if panel is not None and not panel.empty else 0,
        "horizons": horizon_values,
    }
    for horizon in horizon_values:
        incomplete_col = f"incomplete_{horizon}d"
        strong_col = f"strong_{horizon}d"
        if panel is not None and not panel.empty and incomplete_col in panel.columns:
            complete = panel[~panel[incomplete_col].astype(bool)]
            summary[f"complete_{horizon}d_row_count"] = int(len(complete))
            summary[f"incomplete_{horizon}d_row_count"] = int(panel[incomplete_col].astype(bool).sum())
            summary[f"strong_{horizon}d_count"] = int(complete[strong_col].astype(bool).sum()) if strong_col in complete.columns else 0
    return summary


def write_forward_label_artifacts(
    panel: pd.DataFrame,
    output_csv: str | Path,
    horizons: Iterable[int] | None = None,
    summary_json: str | Path | None = None,
) -> Dict[str, str]:
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output_path, index=False)
    summary = summarize_forward_label_panel(panel, horizons=horizons)
    summary_path = Path(summary_json) if summary_json else output_path.with_suffix(".summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"label_panel": str(output_path), "summary": str(summary_path)}


def _label_symbol_rows(
    rows: pd.DataFrame,
    horizons: List[int],
    take_profit_pct: float,
    stop_loss_pct: float,
    strong_return_pct: float,
    limit_threshold_pct: float,
) -> pd.DataFrame:
    labeled = rows.copy()
    for horizon in horizons:
        values = [_label_one(rows, index, horizon, take_profit_pct, stop_loss_pct, strong_return_pct, limit_threshold_pct) for index in range(len(rows))]
        for key in values[0].keys() if values else []:
            labeled[key] = [item[key] for item in values]
    return labeled


def _label_one(
    rows: pd.DataFrame,
    index: int,
    horizon: int,
    take_profit_pct: float,
    stop_loss_pct: float,
    strong_return_pct: float,
    limit_threshold_pct: float,
) -> Dict[str, Any]:
    current = rows.iloc[index]
    entry = _safe_float(current.get("close"))
    future = rows.iloc[index + 1 : index + horizon + 1].copy()
    incomplete = len(future) < int(horizon)
    prefix = f"{horizon}d"
    if future.empty or not math.isfinite(entry) or entry <= 0:
        return _empty_label(prefix, incomplete=True)
    final_close = _safe_float(future.iloc[-1].get("close"))
    future_high = pd.to_numeric(future.get("high"), errors="coerce") if "high" in future.columns else future["close"]
    future_low = pd.to_numeric(future.get("low"), errors="coerce") if "low" in future.columns else future["close"]
    return_pct = (final_close / entry - 1.0) * 100.0 if math.isfinite(final_close) else math.nan
    max_profit_pct = (float(future_high.max()) / entry - 1.0) * 100.0 if not future_high.dropna().empty else math.nan
    max_drawdown_pct = (float(future_low.min()) / entry - 1.0) * 100.0 if not future_low.dropna().empty else math.nan
    first_event = _first_event(future, entry, take_profit_pct=take_profit_pct, stop_loss_pct=stop_loss_pct)
    limit_up_blocked = _limit_flag(future, threshold=limit_threshold_pct, side="up")
    limit_down_blocked = _limit_flag(future, threshold=limit_threshold_pct, side="down")
    return {
        f"return_{prefix}_pct": _round(return_pct),
        f"strong_{prefix}": bool(math.isfinite(return_pct) and return_pct >= strong_return_pct),
        f"max_profit_{prefix}_pct": _round(max_profit_pct),
        f"max_drawdown_{prefix}_pct": _round(max_drawdown_pct),
        f"first_event_{prefix}": first_event,
        f"incomplete_{prefix}": bool(incomplete),
        f"limit_up_blocked_{prefix}": bool(limit_up_blocked),
        f"limit_down_blocked_{prefix}": bool(limit_down_blocked),
        f"suspended_or_missing_{prefix}": bool(incomplete or future["close"].isna().any()),
    }


def _empty_label(prefix: str, incomplete: bool) -> Dict[str, Any]:
    return {
        f"return_{prefix}_pct": math.nan,
        f"strong_{prefix}": False,
        f"max_profit_{prefix}_pct": math.nan,
        f"max_drawdown_{prefix}_pct": math.nan,
        f"first_event_{prefix}": "none",
        f"incomplete_{prefix}": bool(incomplete),
        f"limit_up_blocked_{prefix}": False,
        f"limit_down_blocked_{prefix}": False,
        f"suspended_or_missing_{prefix}": bool(incomplete),
    }


def _first_event(future: pd.DataFrame, entry: float, take_profit_pct: float, stop_loss_pct: float) -> str:
    for _, row in future.iterrows():
        high = _safe_float(row.get("high", row.get("close")))
        low = _safe_float(row.get("low", row.get("close")))
        low_return = (low / entry - 1.0) * 100.0 if math.isfinite(low) else math.nan
        high_return = (high / entry - 1.0) * 100.0 if math.isfinite(high) else math.nan
        if math.isfinite(low_return) and low_return <= float(stop_loss_pct):
            return "stop_loss"
        if math.isfinite(high_return) and high_return >= float(take_profit_pct):
            return "take_profit"
    return "none"


def _limit_flag(future: pd.DataFrame, threshold: float, side: str) -> bool:
    pct_col = "pct_chg" if "pct_chg" in future.columns else "pct_change" if "pct_change" in future.columns else ""
    if not pct_col:
        return False
    values = pd.to_numeric(future[pct_col], errors="coerce")
    if side == "up":
        return bool((values >= float(threshold)).any())
    return bool((values <= -float(threshold)).any())


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
    for column in ["open", "high", "low", "close", "pct_chg", "pct_change", "amount", "volume"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]
    return df.drop_duplicates(["trade_date", "symbol"], keep="last").sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return text


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _round(value: float) -> float:
    if not math.isfinite(float(value)):
        return math.nan
    return round(float(value), 6)
