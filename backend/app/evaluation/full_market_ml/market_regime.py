"""Point-in-time market regime diagnostics for offline ML research only."""
from __future__ import annotations

import numpy as np
import pandas as pd


_REQUIRED_COLUMNS = (
    "trade_date",
    "market_index_close",
    "adjusted_return_1d",
    "price_to_sma_20d",
    "at_up_limit",
    "at_down_limit",
    "valid_ohlc",
)


class MarketRegimeError(ValueError):
    """Raised when market-state inputs cannot preserve point-in-time semantics."""


def build_market_regime_table(rows: pd.DataFrame) -> pd.DataFrame:
    """Construct one historical-only market-state row per signal date.

    The returned state is deliberately independent of labels and later dates.
    `trend_up` and `trend_down` are frozen research definitions; all other
    complete-history dates are `mixed` rather than being optimized from labels.
    """
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("market regime rows must be a pandas DataFrame")
    missing = sorted(set(_REQUIRED_COLUMNS) - set(rows.columns))
    if missing:
        raise MarketRegimeError("market regime rows missing columns: " + ", ".join(missing))
    if rows.empty:
        raise MarketRegimeError("market regime rows are empty")

    data = rows.loc[:, _REQUIRED_COLUMNS].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if data["trade_date"].isna().any():
        raise MarketRegimeError("market regime rows contain invalid trade dates")
    data["market_index_close"] = pd.to_numeric(data["market_index_close"], errors="coerce")
    if (~np.isfinite(data["market_index_close"]) | data["market_index_close"].le(0)).any():
        raise MarketRegimeError("market regime rows contain invalid market index closes")

    index_close = data.groupby("trade_date", sort=True)["market_index_close"].agg(["min", "max"])
    if not np.isclose(index_close["min"], index_close["max"], rtol=0.0, atol=1e-12).all():
        raise MarketRegimeError("market index close conflicts within a trade date")

    valid = data.loc[data["valid_ohlc"].eq(True)].copy()
    if valid.empty:
        raise MarketRegimeError("market regime rows have no valid OHLC observations")
    valid["adjusted_return_1d"] = pd.to_numeric(valid["adjusted_return_1d"], errors="coerce")
    valid["price_to_sma_20d"] = pd.to_numeric(valid["price_to_sma_20d"], errors="coerce")
    daily = valid.groupby("trade_date", sort=True).agg(
        valid_stock_count=("valid_ohlc", "size"),
        market_positive_breadth_1d=("adjusted_return_1d", lambda values: values.gt(0).mean()),
        market_above_sma20_rate=("price_to_sma_20d", lambda values: values.gt(0).mean()),
        market_limit_up_rate=("at_up_limit", lambda values: values.eq(True).mean()),
        market_limit_down_rate=("at_down_limit", lambda values: values.eq(True).mean()),
    )
    output = index_close[["min"]].rename(columns={"min": "market_index_close"}).join(daily, how="left")
    output.index.name = "trade_date"
    if output["valid_stock_count"].isna().any():
        raise MarketRegimeError("market regime has trade dates without valid OHLC observations")
    output["market_return_1d"] = output["market_index_close"].pct_change()
    output["market_return_5d"] = output["market_index_close"].pct_change(5)
    output["market_return_20d"] = output["market_index_close"].pct_change(20)
    output["market_volatility_20d"] = output["market_return_1d"].rolling(20, min_periods=20).std(ddof=0)
    output["regime_history_complete"] = output["market_return_20d"].notna()
    output["market_regime"] = "insufficient_history"
    complete = output["regime_history_complete"]
    output.loc[complete, "market_regime"] = "mixed"
    output.loc[
        complete & output["market_return_20d"].gt(0) & output["market_positive_breadth_1d"].ge(0.5),
        "market_regime",
    ] = "trend_up"
    output.loc[
        complete & output["market_return_20d"].lt(0) & output["market_positive_breadth_1d"].le(0.5),
        "market_regime",
    ] = "trend_down"
    return output.reset_index()
