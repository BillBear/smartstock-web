"""Rebuild immutable daily OOF cohort paths without production dependencies."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


HORIZON_SESSIONS = 10
DEFAULT_COMMISSION_PER_SIDE = 0.0003
DEFAULT_SLIPPAGE_PER_SIDE = 0.001
TERMINAL_FACTOR_TOLERANCE = 1e-8

_OOF_COLUMNS = frozenset(
    {
        "fold",
        "quadrant",
        "trade_date",
        "symbol",
        "entry_tradeable",
        "horizon_available_10d",
        "path_ambiguous_10d",
        "net_return_after_cost_10d",
    }
)
_PANEL_COLUMNS = frozenset(
    {
        "trade_date",
        "symbol",
        "next_open_date",
        "adjusted_open",
        "adjusted_close",
        "valid_ohlc",
        "is_suspended",
        "at_up_limit_open",
    }
)
_PATH_COLUMNS = (
    "fold",
    "quadrant",
    "signal_trade_date",
    "entry_trade_date",
    "exit_trade_date",
    "symbol",
    "rank_no",
    "score",
    "portfolio_mark_date",
    "cohort_net_factor",
    "daily_mark_to_market_return",
)


class MLOofDailyPathError(ValueError):
    """Raised when OOF or immutable panel schema cannot support reconstruction."""


def reconstruct_selected_daily_paths(
    *,
    oof_rows: pd.DataFrame,
    panel_rows: pd.DataFrame,
    score_column: str,
    top_k: int = 10,
    commission_per_side: float = DEFAULT_COMMISSION_PER_SIDE,
    slippage_per_side: float = DEFAULT_SLIPPAGE_PER_SIDE,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Reconstruct Top-K daily marks and fail closed on any selected-row defect."""
    if int(top_k) != top_k or top_k <= 0:
        raise MLOofDailyPathError("top_k must be a positive integer")
    if commission_per_side < 0 or slippage_per_side < 0:
        raise MLOofDailyPathError("commission and slippage must be non-negative")
    selected = _select_top_k(oof_rows, score_column=score_column, top_k=int(top_k))
    panel = _normalize_panel(panel_rows)
    panel_index = panel.set_index(["symbol", "trade_date"])
    reconstructed: list[dict[str, object]] = []
    rejection_codes: list[str] = []
    terminal_mismatch_count = 0

    for selected_row in selected.itertuples(index=False):
        path, rejection = _reconstruct_row(
            selected_row=selected_row,
            panel_index=panel_index,
            commission_per_side=float(commission_per_side),
            slippage_per_side=float(slippage_per_side),
        )
        if rejection is not None:
            rejection_codes.append(rejection)
            terminal_mismatch_count += int(rejection == "terminal_factor_mismatch")
            continue
        reconstructed.extend(path)

    rejected_count = len(rejection_codes)
    report: dict[str, object] = {
        "status": "complete" if rejected_count == 0 else "blocked",
        "top_k": int(top_k),
        "horizon_sessions": HORIZON_SESSIONS,
        "commission_per_side": float(commission_per_side),
        "slippage_per_side": float(slippage_per_side),
        "selected_row_count": int(len(selected)),
        "reconstructed_row_count": int(len(selected) - rejected_count),
        "rejected_row_count": int(rejected_count),
        "terminal_mismatch_count": int(terminal_mismatch_count),
        "rejection_codes": sorted(set(rejection_codes)),
        "all_selected_rows_reconstructed": bool(rejected_count == 0),
    }
    if rejected_count:
        return _empty_paths(), report
    paths = pd.DataFrame(reconstructed, columns=_PATH_COLUMNS)
    return paths.sort_values(
        ["fold", "quadrant", "signal_trade_date", "rank_no", "portfolio_mark_date", "symbol"],
        kind="stable",
    ).reset_index(drop=True), report


def _select_top_k(oof_rows: pd.DataFrame, *, score_column: str, top_k: int) -> pd.DataFrame:
    if not isinstance(oof_rows, pd.DataFrame):
        raise TypeError("oof_rows must be a pandas DataFrame")
    missing = sorted((_OOF_COLUMNS | {str(score_column)}) - set(oof_rows.columns))
    if missing:
        raise MLOofDailyPathError("OOF rows miss required columns: " + ", ".join(missing))
    rows = oof_rows.copy()
    rows["trade_date"] = _normalize_dates(rows["trade_date"], "OOF trade_date")
    rows["symbol"] = _normalize_symbols(rows["symbol"], "OOF symbol")
    rows["selected_score"] = pd.to_numeric(rows[score_column], errors="coerce")
    eligible = (
        rows["entry_tradeable"].eq(True).fillna(False)
        & rows["horizon_available_10d"].eq(True).fillna(False)
        & rows["path_ambiguous_10d"].eq(False).fillna(False)
        & np.isfinite(rows["selected_score"])
        & pd.to_numeric(rows["net_return_after_cost_10d"], errors="coerce").notna()
    )
    rows = rows.loc[eligible].copy()
    if rows.empty:
        raise MLOofDailyPathError("OOF rows have no execution-eligible scored candidates")
    if rows.duplicated(["fold", "quadrant", "trade_date", "symbol"]).any():
        raise MLOofDailyPathError("OOF rows have duplicate fold/quadrant/trade_date/symbol keys")
    rows = rows.sort_values(
        ["fold", "quadrant", "trade_date", "selected_score", "symbol"],
        ascending=[True, True, True, False, True],
        kind="stable",
    )
    selected = rows.groupby(["fold", "quadrant", "trade_date"], sort=False, group_keys=False).head(top_k).copy()
    selected["rank_no"] = selected.groupby(["fold", "quadrant", "trade_date"], sort=False).cumcount() + 1
    selected["selected_score"] = pd.to_numeric(selected["selected_score"], errors="raise")
    return selected.reset_index(drop=True)


def _normalize_panel(panel_rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel_rows, pd.DataFrame):
        raise TypeError("panel_rows must be a pandas DataFrame")
    missing = sorted(_PANEL_COLUMNS - set(panel_rows.columns))
    if missing:
        raise MLOofDailyPathError("panel rows miss required columns: " + ", ".join(missing))
    panel = panel_rows.loc[:, list(_PANEL_COLUMNS)].copy()
    panel["trade_date"] = _normalize_dates(panel["trade_date"], "panel trade_date")
    panel["next_open_date"] = _normalize_optional_dates(panel["next_open_date"], "panel next_open_date")
    panel["symbol"] = _normalize_symbols(panel["symbol"], "panel symbol")
    if panel.duplicated(["symbol", "trade_date"]).any():
        raise MLOofDailyPathError("panel rows have duplicate symbol/trade_date keys")
    for column in ("adjusted_open", "adjusted_close"):
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    return panel


def _reconstruct_row(
    *,
    selected_row: Any,
    panel_index: pd.DataFrame,
    commission_per_side: float,
    slippage_per_side: float,
) -> tuple[list[dict[str, object]], str | None]:
    symbol = str(selected_row.symbol)
    signal_date = str(selected_row.trade_date)
    signal = _panel_record(panel_index, symbol, signal_date)
    expected_date = _date_value(None if signal is None else signal.next_open_date)
    if signal is None or expected_date is None:
        return [], "missing_entry_session"

    entry_date = expected_date
    previous_close: float | None = None
    factor = 1.0
    path: list[dict[str, object]] = []
    for session_offset in range(HORIZON_SESSIONS):
        current = _panel_record(panel_index, symbol, expected_date)
        if current is None:
            return [], "missing_future_session"
        opening = _positive_float(current.adjusted_open)
        closing = _positive_float(current.adjusted_close)
        if opening is None or closing is None:
            return [], "invalid_adjusted_price"
        if session_offset == 0 and (
            not bool(current.valid_ohlc) or bool(current.is_suspended) or bool(current.at_up_limit_open)
        ):
            return [], "entry_tradeability_contradiction"
        previous_factor = factor
        if session_offset == 0:
            factor = closing / (opening * (1.0 + slippage_per_side)) * (1.0 - commission_per_side)
        else:
            if previous_close is None or previous_close <= 0:
                return [], "invalid_adjusted_price"
            factor *= closing / previous_close
        if session_offset == HORIZON_SESSIONS - 1:
            factor *= (1.0 - slippage_per_side) * (1.0 - commission_per_side)
        path.append(
            {
                "fold": int(selected_row.fold),
                "quadrant": str(selected_row.quadrant),
                "signal_trade_date": signal_date,
                "entry_trade_date": entry_date,
                "exit_trade_date": None,
                "symbol": symbol,
                "rank_no": int(selected_row.rank_no),
                "score": float(selected_row.selected_score),
                "portfolio_mark_date": expected_date,
                "cohort_net_factor": float(factor),
                "daily_mark_to_market_return": float(factor / previous_factor - 1.0),
            }
        )
        previous_close = closing
        if session_offset < HORIZON_SESSIONS - 1:
            expected_date = _date_value(current.next_open_date)
            if expected_date is None:
                return [], "nonconsecutive_future_session"

    expected_factor = float(pd.to_numeric(pd.Series([selected_row.net_return_after_cost_10d]), errors="coerce").iloc[0]) + 1.0
    if not np.isfinite(expected_factor) or not np.isclose(factor, expected_factor, rtol=0.0, atol=TERMINAL_FACTOR_TOLERANCE):
        return [], "terminal_factor_mismatch"
    for point in path:
        point["exit_trade_date"] = str(path[-1]["portfolio_mark_date"])
    return path, None


def _panel_record(panel_index: pd.DataFrame, symbol: str, trade_date: str) -> Any | None:
    try:
        return panel_index.loc[(symbol, trade_date)]
    except KeyError:
        return None


def _normalize_dates(values: pd.Series, source: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce")
    if dates.isna().any():
        raise MLOofDailyPathError(f"{source} contains an invalid date")
    return dates.dt.strftime("%Y-%m-%d")


def _normalize_optional_dates(values: pd.Series, source: str) -> pd.Series:
    raw = values.astype("string")
    present = raw.notna() & raw.str.strip().ne("")
    normalized = pd.Series(pd.NA, index=values.index, dtype="string")
    if present.any():
        normalized.loc[present] = _normalize_dates(raw.loc[present], source).astype("string")
    return normalized


def _normalize_symbols(values: pd.Series, source: str) -> pd.Series:
    raw = values.astype("string").str.strip().str.split(".", regex=False).str[0]
    if raw.isna().any() or raw.str.fullmatch(r"\d{1,6}").eq(False).any():
        raise MLOofDailyPathError(f"{source} contains an invalid symbol")
    return raw.str.zfill(6)


def _positive_float(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) and np.isfinite(parsed) and float(parsed) > 0 else None


def _date_value(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def _empty_paths() -> pd.DataFrame:
    return pd.DataFrame(columns=_PATH_COLUMNS)
