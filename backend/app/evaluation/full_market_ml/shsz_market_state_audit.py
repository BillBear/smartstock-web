"""Point-in-time SH/SZ market-state construction for development-only research."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from .market_regime import build_market_regime_table


MIN_VALID_STOCK_COUNT = 4_500
STATE_PANEL_COLUMNS = (
    "trade_date",
    "symbol",
    "market_index_close",
    "at_up_limit",
    "at_down_limit",
)
STATE_R2_COLUMNS = (
    "trade_date",
    "symbol",
    "valid_ohlc_flag",
    "adjusted_return_1d",
    "price_to_sma_20d",
)
STATE_OUTPUT_COLUMNS = (
    "trade_date",
    "market_index_close",
    "market_return_1d",
    "market_return_5d",
    "market_return_20d",
    "market_volatility_20d",
    "valid_stock_count",
    "market_positive_breadth_1d",
    "market_above_sma20_rate",
    "market_limit_up_rate",
    "market_limit_down_rate",
    "regime_history_complete",
    "market_regime",
)


class SHSZMarketStateAuditError(ValueError):
    """Raised when a state input cannot support point-in-time SH/SZ research."""


def validate_shsz_state_inputs(
    panel_manifest: Mapping[str, Any],
    r2_manifest: Mapping[str, Any],
    expected_panel_sha256: str,
) -> None:
    """Validate the immutable panel/R2 universe binding before data is read."""
    if not isinstance(panel_manifest, Mapping) or not isinstance(r2_manifest, Mapping):
        raise TypeError("state audit manifests must be mappings")
    panel_sha = str(r2_manifest.get("panel_manifest_sha256", ""))
    if panel_sha != str(expected_panel_sha256):
        raise SHSZMarketStateAuditError("R2 panel manifest SHA256 does not match the frozen state source")
    if str(panel_manifest.get("universe_id", "")) != "shsz_a_share_v1":
        raise SHSZMarketStateAuditError("state panel does not define shsz_a_share_v1")
    exchanges = tuple(str(value).upper() for value in panel_manifest.get("allowed_exchanges", ()))
    if exchanges != ("SH", "SZ"):
        raise SHSZMarketStateAuditError("state panel does not restrict the universe to SH/SZ")
    if str(r2_manifest.get("universe_id", "")) != "shsz_a_share_v1":
        raise SHSZMarketStateAuditError("R2 feature asset does not define shsz_a_share_v1")
    if tuple(str(value).upper() for value in r2_manifest.get("allowed_exchanges", ())) != ("SH", "SZ"):
        raise SHSZMarketStateAuditError("R2 feature asset does not restrict the universe to SH/SZ")


def build_shsz_market_state_table(panel_rows: pd.DataFrame, r2_rows: pd.DataFrame) -> pd.DataFrame:
    """Build one same-date-only state row for each SH/SZ market session.

    This function does not accept labels or forward outcomes. The state is
    determined solely from historical index closes and same-date full-market
    breadth, then delegated to the frozen ``market_regime`` classifier.
    """
    panel = _normalize_rows(panel_rows, STATE_PANEL_COLUMNS, "certified panel")
    r2 = _normalize_rows(r2_rows, STATE_R2_COLUMNS, "R2 matrix")
    index_rows = _one_index_close_per_date(panel)
    limit_rows = _panel_limit_rows(panel)
    market_rows = _full_market_state_rows(r2)
    source = market_rows.merge(limit_rows, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    if source[["at_up_limit", "at_down_limit"]].isna().any(axis=None):
        raise SHSZMarketStateAuditError("certified panel does not cover every R2 state key with limit flags")
    source = source.merge(index_rows, on="trade_date", how="inner", validate="many_to_one")
    if source.empty:
        raise SHSZMarketStateAuditError("state inputs have no overlapping trade dates")
    result = build_market_regime_table(source.rename(columns={"valid_ohlc_flag": "valid_ohlc"}))
    _validate_state_table(result)
    return result.loc[:, STATE_OUTPUT_COLUMNS].sort_values("trade_date", kind="stable").reset_index(drop=True)


def _normalize_rows(rows: pd.DataFrame, required: tuple[str, ...], source_name: str) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError(f"{source_name} rows must be a pandas DataFrame")
    missing = sorted(set(required) - set(rows.columns))
    if missing:
        raise SHSZMarketStateAuditError(f"{source_name} misses columns: {', '.join(missing)}")
    _reject_outcome_columns(rows, source_name)
    result = rows.loc[:, required].copy()
    _reject_bj_symbols(result["symbol"], source_name)
    result["trade_date"] = _normalize_trade_dates(result["trade_date"], source_name)
    result["symbol"] = _normalize_symbols(result["symbol"], source_name)
    if source_name == "R2 matrix" and result.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("R2 matrix has duplicate trade_date and symbol keys")
    return result


def _reject_outcome_columns(rows: pd.DataFrame, source_name: str) -> None:
    forbidden_prefixes = ("future_", "label_", "alpha_", "relevance_", "net_return", "entry_price", "exit_price")
    present = sorted(column for column in rows.columns if str(column).startswith(forbidden_prefixes))
    if present:
        raise SHSZMarketStateAuditError(f"{source_name} includes forbidden outcome columns: {', '.join(present)}")


def _reject_bj_symbols(symbols: pd.Series, source_name: str) -> None:
    raw = symbols.astype("string").fillna("").str.strip().str.upper()
    if raw.str.endswith(".BJ").any():
        raise SHSZMarketStateAuditError(f"{source_name} includes BJ symbols before normalization")


def _normalize_trade_dates(values: pd.Series, source_name: str) -> pd.Series:
    normalized = pd.to_datetime(values.astype("string"), errors="coerce").dt.strftime("%Y-%m-%d")
    if normalized.isna().any():
        raise SHSZMarketStateAuditError(f"{source_name} contains invalid trade dates")
    return normalized


def _normalize_symbols(values: pd.Series, source_name: str) -> pd.Series:
    raw = values.astype("string").fillna("").str.strip().str.upper()
    stripped = raw.str.split(".", regex=False).str[0]
    valid = stripped.str.fullmatch(r"\d{6}")
    if (~valid).any():
        raise SHSZMarketStateAuditError(f"{source_name} contains malformed symbols")
    return stripped


def _one_index_close_per_date(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.loc[:, ["trade_date", "market_index_close"]].copy()
    result["market_index_close"] = pd.to_numeric(result["market_index_close"], errors="coerce")
    if (~np.isfinite(result["market_index_close"]) | result["market_index_close"].le(0)).any():
        raise SHSZMarketStateAuditError("certified panel contains invalid market index closes")
    counts = result.groupby("trade_date", sort=True)["market_index_close"].nunique(dropna=True)
    if counts.ne(1).any():
        invalid = str(counts.loc[counts.ne(1)].index[0])
        raise SHSZMarketStateAuditError(f"certified panel has conflicting market index close on {invalid}")
    return result.groupby("trade_date", as_index=False, sort=True)["market_index_close"].first()


def _panel_limit_rows(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.loc[:, ["trade_date", "symbol", "at_up_limit", "at_down_limit"]].copy()
    if result.duplicated(["trade_date", "symbol"]).any():
        raise SHSZMarketStateAuditError("certified panel has duplicate trade_date and symbol keys")
    result["at_up_limit"] = result["at_up_limit"].eq(True)
    result["at_down_limit"] = result["at_down_limit"].eq(True)
    return result


def _full_market_state_rows(r2: pd.DataFrame) -> pd.DataFrame:
    result = r2.copy()
    result["valid_ohlc_flag"] = result["valid_ohlc_flag"].eq(True)
    valid_counts = result.loc[result["valid_ohlc_flag"]].groupby("trade_date", sort=True).size()
    if valid_counts.empty:
        raise SHSZMarketStateAuditError("R2 matrix has no valid OHLC rows")
    low_coverage = valid_counts.loc[valid_counts.lt(MIN_VALID_STOCK_COUNT)]
    if not low_coverage.empty:
        date, count = str(low_coverage.index[0]), int(low_coverage.iloc[0])
        raise SHSZMarketStateAuditError(f"R2 matrix has fewer than 4500 valid SH/SZ rows on {date}: {count}")
    result["adjusted_return_1d"] = pd.to_numeric(result["adjusted_return_1d"], errors="coerce")
    result["price_to_sma_20d"] = pd.to_numeric(result["price_to_sma_20d"], errors="coerce")
    return result.loc[:, [
        "trade_date",
        "symbol",
        "adjusted_return_1d",
        "price_to_sma_20d",
        "valid_ohlc_flag",
    ]]


def _validate_state_table(states: pd.DataFrame) -> None:
    if states.duplicated("trade_date").any():
        raise SHSZMarketStateAuditError("market state table has duplicate trade dates")
    if states["valid_stock_count"].lt(MIN_VALID_STOCK_COUNT).any():
        raise SHSZMarketStateAuditError("market state table contains a date below the minimum SH/SZ coverage")
    if states["market_regime"].isna().any() or states["regime_history_complete"].isna().any():
        raise SHSZMarketStateAuditError("market state table has incomplete regime values")
