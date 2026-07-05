"""Deterministic split planning for ML training evidence.

This module is read-only. It defines how to separate training, walk-forward
validation, final time holdout, and stock holdout sets before model training.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

import pandas as pd


def build_ml_split_plan(
    df: pd.DataFrame,
    final_holdout_months: int = 3,
    stock_holdout_ratio: float = 0.20,
    walk_forward_splits: int = 5,
    label_horizon_days: int = 0,
) -> Dict[str, Any]:
    """Build non-overlapping ML split metadata from a dated symbol panel."""
    if df is None or df.empty:
        raise ValueError("ML split planning requires a non-empty dataset")
    if "date" not in df.columns or "symbol" not in df.columns:
        raise ValueError("ML split planning requires date and symbol columns")

    dates = _normalized_dates(df["date"].tolist())
    symbols = sorted({str(symbol) for symbol in df["symbol"].tolist() if str(symbol).strip()})
    if len(dates) < 4 or len(symbols) < 2:
        raise ValueError("ML split planning requires enough dates and symbols")

    holdout_months = max(1, int(final_holdout_months or 3))
    max_date = pd.Timestamp(dates[-1])
    cutoff = max_date - pd.DateOffset(months=holdout_months)
    final_dates = [date for date in dates if pd.Timestamp(date) > cutoff]
    final_start_index = dates.index(final_dates[0]) if final_dates else len(dates)
    embargo_count = max(0, int(label_horizon_days or 0))
    final_embargo_dates = dates[max(0, final_start_index - embargo_count) : final_start_index]
    training_dates = [date for date in dates if date not in set(final_dates) and date not in set(final_embargo_dates)]
    if not final_dates or not training_dates:
        raise ValueError("final holdout leaves no training or holdout dates")

    holdout_symbols = _stock_holdout_symbols(symbols, stock_holdout_ratio)
    training_symbols = [symbol for symbol in symbols if symbol not in set(holdout_symbols)]
    if not holdout_symbols or not training_symbols:
        raise ValueError("stock holdout leaves no training or holdout symbols")

    windows = _walk_forward_windows(training_dates, int(walk_forward_splits or 5), embargo_count)
    return {
        "method": "walk_forward_plus_final_time_and_stock_holdout",
        "training_dates": training_dates,
        "training_symbols": training_symbols,
        "final_holdout": {
            "start_date": final_dates[0],
            "end_date": final_dates[-1],
            "date_count": len(final_dates),
            "dates": final_dates,
        },
        "stock_holdout": {
            "ratio": round(len(holdout_symbols) / len(symbols), 6),
            "symbol_count": len(holdout_symbols),
            "symbols": holdout_symbols,
        },
        "walk_forward": {
            "split_count": len(windows),
            "windows": windows,
        },
        "embargo": {
            "label_horizon_days": embargo_count,
            "final_holdout_embargo_dates": final_embargo_dates,
        },
    }


def _normalized_dates(values: List[Any]) -> List[str]:
    parsed = pd.to_datetime(pd.Series(values), errors="coerce")
    dates = sorted({item.date().isoformat() for item in parsed.dropna()})
    return dates


def _stock_holdout_symbols(symbols: List[str], ratio: float) -> List[str]:
    bounded_ratio = min(0.8, max(0.0, float(ratio or 0.0)))
    count = max(1, int(round(len(symbols) * bounded_ratio)))
    count = min(count, len(symbols) - 1)
    ranked = sorted(symbols, key=lambda item: hashlib.sha256(item.encode("utf-8")).hexdigest())
    return sorted(ranked[:count])


def _walk_forward_windows(training_dates: List[str], split_count: int, embargo_count: int = 0) -> List[Dict[str, Any]]:
    if len(training_dates) < 3:
        raise ValueError("walk-forward planning requires at least 3 training dates")
    bounded_splits = max(1, min(split_count, len(training_dates) - 2))
    validation_count = max(1, len(training_dates) // (bounded_splits + 1))
    windows = []
    for index in range(bounded_splits):
        validation_start = len(training_dates) - validation_count * (bounded_splits - index)
        validation_end = validation_start + validation_count
        embargo_start = max(0, validation_start - max(0, int(embargo_count or 0)))
        embargo_dates = training_dates[embargo_start:validation_start]
        train_dates = training_dates[:embargo_start]
        validation_dates = training_dates[validation_start:validation_end]
        if not train_dates or not validation_dates:
            continue
        windows.append(
            {
                "window": len(windows) + 1,
                "train_start": train_dates[0],
                "train_end": train_dates[-1],
                "validation_start": validation_dates[0],
                "validation_end": validation_dates[-1],
                "train_date_count": len(train_dates),
                "validation_date_count": len(validation_dates),
                "train_dates": train_dates,
                "validation_dates": validation_dates,
                "embargo_dates": embargo_dates,
            }
        )
    if not windows:
        raise ValueError("unable to build walk-forward windows from training dates")
    return windows
