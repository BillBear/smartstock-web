from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from app.evaluation.local_ml_v2 import V2_FEATURE_NAMES, build_local_core_v2_features
from app.evaluation.rule_baseline_comparison import run_rule_baseline_comparison, write_rule_comparison_artifacts


DEFAULT_ENRICHMENT_FEATURES = [
    "return_20d_rank",
    "return_60d_rank",
    "amount_pct_rank",
    "amount_ratio_5_20",
    "macd_hist",
    "rsi",
    "volatility_20d",
    "atr_14_pct",
    "large_down_day_count_20d",
    "intraday_range_pct",
    "trend_slope_20d",
    "trend_r2_20d",
]


def enrich_candidate_features(
    candidate_df: pd.DataFrame,
    history_provider: Any = None,
    history_panel_df: Optional[pd.DataFrame] = None,
    lookback_calendar_days: int = 180,
    min_history_rows: int = 61,
    workers: int = 1,
) -> Dict[str, Any]:
    """Build read-only rule feature rows for every historical candidate row."""
    candidates = _normalize_candidates(candidate_df)
    if candidates.empty:
        return {
            "candidate_features": pd.DataFrame(),
            "history_panel": pd.DataFrame(),
            "summary": _empty_summary(),
        }
    start_date = _history_start_date(candidates["trade_date"].min(), lookback_calendar_days)
    end_date = str(candidates["trade_date"].max())
    symbols = sorted(candidates["symbol"].dropna().unique().tolist())

    if history_panel_df is not None:
        history_panel = _normalize_history_panel(history_panel_df)
    else:
        if history_provider is None:
            raise ValueError("history_provider or history_panel_df is required")
        history_panel = fetch_candidate_history_panel(
            symbols=symbols,
            history_provider=history_provider,
            start_date=start_date,
            end_date=end_date,
            workers=workers,
        )

    history_panel = history_panel[
        history_panel["symbol"].isin(symbols)
        & (history_panel["date"] >= start_date)
        & (history_panel["date"] <= end_date)
    ].copy()
    history_panel = _add_price_volume_indicators(history_panel)
    featured, _ = build_local_core_v2_features(history_panel)
    featured = _attach_history_depth(featured, min_history_rows=min_history_rows)
    feature_cols = [column for column in DEFAULT_ENRICHMENT_FEATURES if column in featured.columns]
    optional_cols = [
        "date",
        "symbol",
        "history_observation_count",
        "has_60d_lookback",
        *feature_cols,
        *[f"{column}_missing" for column in V2_FEATURE_NAMES if f"{column}_missing" in featured.columns],
    ]
    feature_rows = featured.loc[:, list(dict.fromkeys(optional_cols))].copy() if not featured.empty else pd.DataFrame()
    if "return_60d_rank" in feature_rows.columns and "has_60d_lookback" in feature_rows.columns:
        feature_rows.loc[~feature_rows["has_60d_lookback"].astype(bool), "return_60d_rank"] = np.nan
    enriched = candidates.merge(
        feature_rows,
        left_on=["trade_date", "symbol"],
        right_on=["date", "symbol"],
        how="left",
        indicator="feature_join_status",
    ).drop(columns=["date"], errors="ignore")
    if "has_60d_lookback" not in enriched.columns:
        enriched["has_60d_lookback"] = False
    enriched["has_60d_lookback"] = enriched["has_60d_lookback"].where(enriched["has_60d_lookback"].notna(), False).astype(bool)
    summary = _build_summary(
        candidates=candidates,
        enriched=enriched,
        history_panel=history_panel,
        start_date=start_date,
        end_date=end_date,
        min_history_rows=min_history_rows,
    )
    return {
        "candidate_features": enriched,
        "history_panel": history_panel,
        "summary": summary,
    }


def fetch_candidate_history_panel(
    symbols: Iterable[str],
    history_provider: Any,
    start_date: str,
    end_date: str,
    workers: int = 1,
) -> pd.DataFrame:
    normalized_symbols = sorted({_normalize_symbol(symbol) for symbol in symbols if _normalize_symbol(symbol)})
    if not normalized_symbols:
        return pd.DataFrame()
    max_workers = max(1, int(workers or 1))
    frames: List[pd.DataFrame] = []
    if max_workers == 1:
        for symbol in normalized_symbols:
            frame = _fetch_one_history(history_provider, symbol, start_date, end_date)
            if not frame.empty:
                frames.append(frame)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_fetch_one_history, history_provider, symbol, start_date, end_date): symbol
                for symbol in normalized_symbols
            }
            for future in as_completed(future_map):
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_candidate_feature_artifacts(
    enrichment: Dict[str, Any],
    output_dir: str | Path,
    horizon: int = 10,
    round_trip_cost_pct: float = 0.13,
    min_margin_pct: float = 0.30,
) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    candidate_features = enrichment.get("candidate_features")
    if not isinstance(candidate_features, pd.DataFrame):
        candidate_features = pd.DataFrame()
    summary = enrichment.get("summary") or {}
    feature_path = root / "candidate_features.csv"
    summary_path = root / "feature_enrichment_summary.json"
    report_path = root / "feature_enrichment_report.md"
    candidate_features.to_csv(feature_path, index=False)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_feature_enrichment_markdown(summary), encoding="utf-8")

    candidate_input = _candidate_columns_for_comparison(candidate_features)
    compare_features = _feature_columns_for_comparison(candidate_features)
    comparison = run_rule_baseline_comparison(
        candidate_input,
        compare_features,
        horizon=horizon,
        round_trip_cost_pct=round_trip_cost_pct,
        min_margin_pct=min_margin_pct,
    )
    comparison_paths = write_rule_comparison_artifacts(comparison, root)
    return {
        "candidate_features": str(feature_path),
        "feature_enrichment_summary": str(summary_path),
        "feature_enrichment_report": str(report_path),
        **comparison_paths,
    }


def _candidate_columns_for_comparison(candidate_features: pd.DataFrame) -> pd.DataFrame:
    feature_like = set(DEFAULT_ENRICHMENT_FEATURES)
    feature_like.update(
        {
            "date",
            "history_observation_count",
            "has_60d_lookback",
            "feature_join_status",
            *[f"{column}_missing" for column in V2_FEATURE_NAMES],
        }
    )
    keep = [column for column in candidate_features.columns if column not in feature_like]
    return candidate_features.loc[:, keep].copy()


def _feature_columns_for_comparison(candidate_features: pd.DataFrame) -> pd.DataFrame:
    columns = ["trade_date", "symbol", *[column for column in DEFAULT_ENRICHMENT_FEATURES if column in candidate_features.columns]]
    feature_frame = candidate_features.loc[:, list(dict.fromkeys(columns))].copy()
    feature_frame["date"] = feature_frame["trade_date"]
    return feature_frame.drop(columns=["trade_date"])


def render_feature_enrichment_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Candidate Feature Enrichment",
        "",
        f"status: `{summary.get('status')}`",
        f"candidate_row_count: `{summary.get('candidate_row_count')}`",
        f"candidate_symbol_count: `{summary.get('candidate_symbol_count')}`",
        f"candidate_date_count: `{summary.get('candidate_date_count')}`",
        f"history_start_date: `{summary.get('history_start_date')}`",
        f"history_end_date: `{summary.get('history_end_date')}`",
        f"history_symbol_count: `{summary.get('history_symbol_count')}`",
        f"feature_joined_row_count: `{summary.get('feature_joined_row_count')}`",
        f"feature_complete_row_count: `{summary.get('feature_complete_row_count')}`",
        f"feature_complete_row_rate: `{summary.get('feature_complete_row_rate')}`",
        f"feature_rank_scope: `{summary.get('feature_rank_scope')}`",
        "",
        "This enrichment is read-only. It does not modify production selection, ranking, buy/sell, stops, or position sizing.",
    ]
    if summary.get("blocking_reasons"):
        lines.extend(["", "## Blocking Reasons", ""])
        lines.extend([f"- `{item}`" for item in summary.get("blocking_reasons") or []])
    return "\n".join(lines) + "\n"


def _fetch_one_history(history_provider: Any, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    if not hasattr(history_provider, "get_history_data_range"):
        return pd.DataFrame()
    frame = history_provider.get_history_data_range(symbol, start_date=start_date, end_date=end_date)
    if frame is not None and not getattr(frame, "empty", True) and "symbol" not in frame.columns:
        frame = frame.copy()
        frame["symbol"] = symbol
    frame = _normalize_history_panel(frame)
    if frame.empty:
        return frame
    frame["symbol"] = symbol
    return frame


def _normalize_candidates(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "trade_date" not in local.columns and "date" in local.columns:
        local["trade_date"] = local["date"]
    local["trade_date"] = pd.to_datetime(local["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local = local[local["trade_date"].notna()].copy()
    local["symbol"] = local["symbol"].map(_normalize_symbol)
    local = local[local["symbol"] != ""].copy()
    return local.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _normalize_history_panel(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "trade_date" in local.columns and "date" not in local.columns:
        local["date"] = local["trade_date"]
    if "date" not in local.columns or "symbol" not in local.columns:
        return pd.DataFrame()
    local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local["symbol"] = local["symbol"].map(_normalize_symbol)
    local = local[(local["date"].notna()) & (local["symbol"] != "")].copy()
    rename_map = {"pct_chg": "pct_change"}
    for old, new in rename_map.items():
        if old in local.columns and new not in local.columns:
            local[new] = local[old]
    for column in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
        if column not in local.columns:
            local[column] = 0.0
        local[column] = pd.to_numeric(local[column], errors="coerce")
    return local.sort_values(["symbol", "date"]).reset_index(drop=True)


def _add_price_volume_indicators(history_panel: pd.DataFrame) -> pd.DataFrame:
    if history_panel is None or history_panel.empty:
        return pd.DataFrame()
    parts = []
    for _, group in history_panel.groupby("symbol", sort=False):
        group = group.copy().sort_values("date")
        close = pd.to_numeric(group["close"], errors="coerce")
        high = pd.to_numeric(group["high"], errors="coerce")
        low = pd.to_numeric(group["low"], errors="coerce")
        returns = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if "macd_hist" not in group.columns or group["macd_hist"].isna().all():
            ema12 = close.ewm(span=12, adjust=False, min_periods=1).mean()
            ema26 = close.ewm(span=26, adjust=False, min_periods=1).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False, min_periods=1).mean()
            group["macd_hist"] = macd - signal
        if "rsi" not in group.columns or group["rsi"].isna().all():
            group["rsi"] = _rsi(returns, 14)
        group["intraday_range_pct"] = _safe_div(high - low, close, 0.0) * 100.0
        group["volatility_20d"] = returns.rolling(20, min_periods=5).std() * math.sqrt(252) * 100.0
        group["ma20_gap_pct"] = _safe_div(close, close.rolling(20, min_periods=5).mean(), 1.0).sub(1.0) * 100.0
        group["ma60_gap_pct"] = _safe_div(close, close.rolling(60, min_periods=20).mean(), 1.0).sub(1.0) * 100.0
        group["ma_alignment"] = (
            (close > close.rolling(20, min_periods=5).mean()).astype(int)
            + (close.rolling(20, min_periods=5).mean() > close.rolling(60, min_periods=20).mean()).astype(int)
        )
        parts.append(group)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _attach_history_depth(featured: pd.DataFrame, min_history_rows: int) -> pd.DataFrame:
    if featured is None or featured.empty:
        return pd.DataFrame()
    local = featured.copy().sort_values(["symbol", "date"]).reset_index(drop=True)
    local["history_observation_count"] = local.groupby("symbol").cumcount() + 1
    local["has_60d_lookback"] = local["history_observation_count"] >= max(1, int(min_history_rows or 61))
    return local


def _build_summary(
    candidates: pd.DataFrame,
    enriched: pd.DataFrame,
    history_panel: pd.DataFrame,
    start_date: str,
    end_date: str,
    min_history_rows: int,
) -> Dict[str, Any]:
    joined = enriched[enriched.get("feature_join_status").astype(str) == "both"] if "feature_join_status" in enriched.columns else enriched.iloc[0:0]
    complete = joined[joined.get("has_60d_lookback", False).astype(bool)] if not joined.empty else joined
    row_count = int(len(candidates))
    complete_count = int(len(complete))
    blocking = []
    if complete_count < row_count:
        blocking.append("candidate_feature_rows_incomplete")
    if history_panel.empty:
        blocking.append("history_panel_empty")
    return {
        "status": "completed" if not history_panel.empty else "blocked",
        "candidate_row_count": row_count,
        "candidate_symbol_count": int(candidates["symbol"].nunique()) if not candidates.empty else 0,
        "candidate_date_count": int(candidates["trade_date"].nunique()) if not candidates.empty else 0,
        "candidate_min_date": str(candidates["trade_date"].min()) if not candidates.empty else "",
        "candidate_max_date": str(candidates["trade_date"].max()) if not candidates.empty else "",
        "history_start_date": start_date,
        "history_end_date": end_date,
        "history_symbol_count": int(history_panel["symbol"].nunique()) if not history_panel.empty else 0,
        "history_row_count": int(len(history_panel)),
        "min_history_rows": int(min_history_rows),
        "feature_joined_row_count": int(len(joined)),
        "feature_complete_row_count": complete_count,
        "feature_complete_row_rate": _round(complete_count / row_count) if row_count else 0.0,
        "missing_feature_row_count": int(row_count - complete_count),
        "feature_rank_scope": "candidate_symbol_panel",
        "blocking_reasons": blocking,
    }


def _empty_summary() -> Dict[str, Any]:
    return {
        "status": "blocked",
        "candidate_row_count": 0,
        "candidate_symbol_count": 0,
        "candidate_date_count": 0,
        "feature_complete_row_count": 0,
        "blocking_reasons": ["candidate_rows_empty"],
    }


def _history_start_date(candidate_min_date: str, lookback_calendar_days: int) -> str:
    parsed = pd.to_datetime(candidate_min_date, errors="coerce")
    if pd.isna(parsed):
        return ""
    return (parsed.date() - timedelta(days=max(1, int(lookback_calendar_days or 180)))).isoformat()


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else ""


def _rsi(returns: pd.Series, window: int) -> pd.Series:
    gains = returns.clip(lower=0.0)
    losses = -returns.clip(upper=0.0)
    avg_gain = gains.rolling(window, min_periods=1).mean()
    avg_loss = losses.rolling(window, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.replace([np.inf, -np.inf], np.nan).fillna(50.0)


def _safe_div(left: pd.Series, right: pd.Series, default: float) -> pd.Series:
    return (left / right.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(default)


def _round(value: float) -> float:
    try:
        if not math.isfinite(float(value)):
            return 0.0
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0
