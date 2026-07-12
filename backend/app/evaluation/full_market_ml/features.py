"""Leak-free, two-pass feature construction for offline full-market ML research."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .config import FullMarketMLConfig


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    formula: str
    source_endpoint: str
    adjusted_status: str
    earliest_lookback: int
    missing_policy: str
    feature_group: str
    stage: str


class FeatureLeakageError(ValueError):
    """Raised when a requested model column could expose post-signal data."""


def _spec(name, formula, source, adjusted, lookback, missing, group, stage="time_series"):
    return FeatureSpec(name, formula, source, adjusted, lookback, missing, group, stage)


# Each core entry is intentionally explicit: this dictionary is the model contract.
CORE_FEATURE_SPECS = (
    _spec("adjusted_return_1d", "adjusted_close / lag(adjusted_close, 1) - 1", "daily+adj_factor", "adjusted", 1, "null", "price_return"),
    _spec("adjusted_return_2d", "adjusted_close / lag(adjusted_close, 2) - 1", "daily+adj_factor", "adjusted", 2, "null", "price_return"),
    _spec("adjusted_return_3d", "adjusted_close / lag(adjusted_close, 3) - 1", "daily+adj_factor", "adjusted", 3, "null", "price_return"),
    _spec("adjusted_return_5d", "adjusted_close / lag(adjusted_close, 5) - 1", "daily+adj_factor", "adjusted", 5, "null", "price_return"),
    _spec("adjusted_return_10d", "adjusted_close / lag(adjusted_close, 10) - 1", "daily+adj_factor", "adjusted", 10, "null", "price_return"),
    _spec("adjusted_return_20d", "adjusted_close / lag(adjusted_close, 20) - 1", "daily+adj_factor", "adjusted", 20, "null", "price_return"),
    _spec("adjusted_return_60d", "adjusted_close / lag(adjusted_close, 60) - 1", "daily+adj_factor", "adjusted", 60, "null", "price_return"),
    _spec("adjusted_open_gap_return", "adjusted_open / lag(adjusted_close, 1) - 1", "daily+adj_factor", "adjusted", 1, "null", "price_return"),
    _spec("adjusted_intraday_return", "adjusted_close / adjusted_open - 1", "daily+adj_factor", "adjusted", 0, "null", "price_return"),
    _spec("adjusted_high_low_range", "adjusted_high / adjusted_low - 1", "daily+adj_factor", "adjusted", 0, "null", "price_return"),
    _spec("adjusted_close_to_high", "adjusted_close / adjusted_high - 1", "daily+adj_factor", "adjusted", 0, "null", "price_return"),
    _spec("adjusted_close_to_low", "adjusted_close / adjusted_low - 1", "daily+adj_factor", "adjusted", 0, "null", "price_return"),
    _spec("price_to_sma_5d", "adjusted_close / mean(adjusted_close, 5) - 1", "daily+adj_factor", "adjusted", 5, "null", "trend"),
    _spec("price_to_sma_10d", "adjusted_close / mean(adjusted_close, 10) - 1", "daily+adj_factor", "adjusted", 10, "null", "trend"),
    _spec("price_to_sma_20d", "adjusted_close / mean(adjusted_close, 20) - 1", "daily+adj_factor", "adjusted", 20, "null", "trend"),
    _spec("price_to_sma_60d", "adjusted_close / mean(adjusted_close, 60) - 1", "daily+adj_factor", "adjusted", 60, "null", "trend"),
    _spec("sma_5d_to_sma_20d", "mean(adjusted_close, 5) / mean(adjusted_close, 20) - 1", "daily+adj_factor", "adjusted", 20, "null", "trend"),
    _spec("sma_20d_to_sma_60d", "mean(adjusted_close, 20) / mean(adjusted_close, 60) - 1", "daily+adj_factor", "adjusted", 60, "null", "trend"),
    _spec("price_to_ema_12d", "adjusted_close / ewm(adjusted_close, 12) - 1", "daily+adj_factor", "adjusted", 12, "null", "trend"),
    _spec("price_to_ema_26d", "adjusted_close / ewm(adjusted_close, 26) - 1", "daily+adj_factor", "adjusted", 26, "null", "trend"),
    _spec("macd_line", "ewm(adjusted_close, 12) - ewm(adjusted_close, 26)", "daily+adj_factor", "adjusted", 26, "null", "trend"),
    _spec("macd_signal_gap", "macd_line - ewm(macd_line, 9)", "daily+adj_factor", "adjusted", 34, "null", "trend"),
    _spec("realized_volatility_5d", "std(return_1d, 5)", "daily+adj_factor", "adjusted", 6, "null", "volatility"),
    _spec("realized_volatility_10d", "std(return_1d, 10)", "daily+adj_factor", "adjusted", 11, "null", "volatility"),
    _spec("realized_volatility_20d", "std(return_1d, 20)", "daily+adj_factor", "adjusted", 21, "null", "volatility"),
    _spec("downside_volatility_20d", "std(min(return_1d, 0), 20)", "daily+adj_factor", "adjusted", 21, "null", "volatility"),
    _spec("atr_pct_5d", "mean(true_range, 5) / adjusted_close", "daily+adj_factor", "adjusted", 5, "null", "volatility"),
    _spec("atr_pct_14d", "mean(true_range, 14) / adjusted_close", "daily+adj_factor", "adjusted", 14, "null", "volatility"),
    _spec("range_mean_5d", "mean(high_low_range, 5)", "daily+adj_factor", "adjusted", 5, "null", "volatility"),
    _spec("range_mean_20d", "mean(high_low_range, 20)", "daily+adj_factor", "adjusted", 20, "null", "volatility"),
    _spec("range_std_20d", "std(high_low_range, 20)", "daily+adj_factor", "adjusted", 20, "null", "volatility"),
    _spec("volume_log", "log1p(volume_shares)", "daily", "raw", 0, "null", "volume_liquidity"),
    _spec("amount_log", "log1p(amount_cny)", "daily", "raw", 0, "null", "volume_liquidity"),
    _spec("volume_ratio_5d", "volume_shares / mean(volume_shares, 5)", "daily", "raw", 5, "null", "volume_liquidity"),
    _spec("volume_ratio_20d", "volume_shares / mean(volume_shares, 20)", "daily", "raw", 20, "null", "volume_liquidity"),
    _spec("amount_ratio_5d", "amount_cny / mean(amount_cny, 5)", "daily", "raw", 5, "null", "volume_liquidity"),
    _spec("amount_ratio_20d", "amount_cny / mean(amount_cny, 20)", "daily", "raw", 20, "null", "volume_liquidity"),
    _spec("volume_change_1d", "volume_shares / lag(volume_shares, 1) - 1", "daily", "raw", 1, "null", "volume_liquidity"),
    _spec("amount_change_1d", "amount_cny / lag(amount_cny, 1) - 1", "daily", "raw", 1, "null", "volume_liquidity"),
    _spec("volume_cv_20d", "std(volume_shares, 20) / mean(volume_shares, 20)", "daily", "raw", 20, "null", "volume_liquidity"),
    _spec("turnover_rate", "turnover_rate", "daily_basic", "raw", 0, "null+flag", "valuation_liquidity"),
    _spec("turnover_rate_missing", "isnull(turnover_rate)", "daily_basic", "raw", 0, "1 if absent", "valuation_liquidity"),
    _spec("turnover_ratio_20d", "turnover_rate / mean(turnover_rate, 20)", "daily_basic", "raw", 20, "null+flag", "valuation_liquidity"),
    _spec("total_mv_log", "log1p(total_mv)", "daily_basic", "raw", 0, "null+flag", "valuation_liquidity"),
    _spec("total_mv_missing", "isnull(total_mv)", "daily_basic", "raw", 0, "1 if absent", "valuation_liquidity"),
    _spec("circ_mv_log", "log1p(circ_mv)", "daily_basic", "raw", 0, "null+flag", "valuation_liquidity"),
    _spec("circ_mv_missing", "isnull(circ_mv)", "daily_basic", "raw", 0, "1 if absent", "valuation_liquidity"),
    _spec("float_market_value_ratio", "circ_mv / total_mv", "daily_basic", "raw", 0, "null+flags", "valuation_liquidity"),
    _spec("pe", "pe", "daily_basic", "raw", 0, "null+flag", "valuation_liquidity"),
    _spec("pe_missing", "isnull(pe)", "daily_basic", "raw", 0, "1 if absent", "valuation_liquidity"),
    _spec("pb", "pb", "daily_basic", "raw", 0, "null+flag", "valuation_liquidity"),
    _spec("pb_missing", "isnull(pb)", "daily_basic", "raw", 0, "1 if absent", "valuation_liquidity"),
    _spec("ps", "ps", "daily_basic", "raw", 0, "null+flag", "valuation_liquidity"),
    _spec("ps_missing", "isnull(ps)", "daily_basic", "raw", 0, "1 if absent", "valuation_liquidity"),
    _spec("main_net_inflow_ratio", "net_mf_amount / amount_cny", "moneyflow+daily", "raw", 0, "null+flag", "moneyflow"),
    _spec("main_net_inflow_ratio_missing", "isnull(net_mf_amount) or amount_cny <= 0", "moneyflow+daily", "raw", 0, "1 if absent", "moneyflow"),
    _spec("net_mf_amount_log", "signed_log1p(net_mf_amount)", "moneyflow", "raw", 0, "null+flag", "moneyflow"),
    _spec("net_mf_amount_missing", "isnull(net_mf_amount)", "moneyflow", "raw", 0, "1 if absent", "moneyflow"),
    _spec("net_mf_amount_ratio_20d", "net_mf_amount / mean(abs(net_mf_amount), 20)", "moneyflow", "raw", 20, "null+flag", "moneyflow"),
    _spec("moneyflow_5d_mean", "mean(main_net_inflow_ratio, 5)", "moneyflow", "raw", 5, "null+flag", "moneyflow"),
    _spec("moneyflow_20d_mean", "mean(main_net_inflow_ratio, 20)", "moneyflow", "raw", 20, "null+flag", "moneyflow"),
    _spec("listing_age_log", "log1p(listing_age_trade_days)", "stock_basic+trade_cal", "raw", 0, "null", "listing_quality"),
    _spec("listing_age_missing", "isnull(listing_age_trade_days)", "stock_basic+trade_cal", "raw", 0, "1 if absent", "listing_quality"),
    _spec("valid_ohlc_flag", "valid_ohlc", "daily+adj_factor", "adjusted", 0, "0 if false or absent", "listing_quality"),
    _spec("industry_available_flag", "notnull(industry_l1)", "index_member_all", "raw", 0, "0 if absent", "listing_quality"),
    _spec("adjusted_return_5d_rank", "percent_rank(adjusted_return_5d) by trade_date", "derived", "adjusted", 5, "null", "cross_section_return", "cross_section"),
    _spec("adjusted_return_5d_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "adjusted", 5, "null", "cross_section_return", "cross_section"),
    _spec("adjusted_return_10d_rank", "percent_rank(adjusted_return_10d) by trade_date", "derived", "adjusted", 10, "null", "cross_section_return", "cross_section"),
    _spec("adjusted_return_10d_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "adjusted", 10, "null", "cross_section_return", "cross_section"),
    _spec("adjusted_return_20d_rank", "percent_rank(adjusted_return_20d) by trade_date", "derived", "adjusted", 20, "null", "cross_section_return", "cross_section"),
    _spec("adjusted_return_20d_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "adjusted", 20, "null", "cross_section_return", "cross_section"),
    _spec("volume_log_rank", "percent_rank(volume_log) by trade_date", "derived", "raw", 0, "null", "cross_section_liquidity", "cross_section"),
    _spec("volume_log_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "raw", 0, "null", "cross_section_liquidity", "cross_section"),
    _spec("amount_log_rank", "percent_rank(amount_log) by trade_date", "derived", "raw", 0, "null", "cross_section_liquidity", "cross_section"),
    _spec("amount_log_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "raw", 0, "null", "cross_section_liquidity", "cross_section"),
    _spec("turnover_rate_rank", "percent_rank(turnover_rate) by trade_date", "derived", "raw", 0, "null", "cross_section_liquidity", "cross_section"),
    _spec("turnover_rate_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "raw", 0, "null", "cross_section_liquidity", "cross_section"),
    _spec("total_mv_log_rank", "percent_rank(total_mv_log) by trade_date", "derived", "raw", 0, "null", "cross_section_valuation", "cross_section"),
    _spec("total_mv_log_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "raw", 0, "null", "cross_section_valuation", "cross_section"),
    _spec("pe_rank", "percent_rank(pe) by trade_date", "derived", "raw", 0, "null", "cross_section_valuation", "cross_section"),
    _spec("pb_rank", "percent_rank(pb) by trade_date", "derived", "raw", 0, "null", "cross_section_valuation", "cross_section"),
    _spec("ps_rank", "percent_rank(ps) by trade_date", "derived", "raw", 0, "null", "cross_section_valuation", "cross_section"),
    _spec("float_market_value_ratio_rank", "percent_rank(float_market_value_ratio) by trade_date", "derived", "raw", 0, "null", "cross_section_valuation", "cross_section"),
    _spec("main_net_inflow_ratio_rank", "percent_rank(main_net_inflow_ratio) by trade_date", "derived", "raw", 0, "null", "cross_section_moneyflow", "cross_section"),
    _spec("main_net_inflow_ratio_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "raw", 0, "null", "cross_section_moneyflow", "cross_section"),
    _spec("net_mf_amount_log_rank", "percent_rank(net_mf_amount_log) by trade_date", "derived", "raw", 0, "null", "cross_section_moneyflow", "cross_section"),
    _spec("net_mf_amount_log_robust_z", "clip((x-median)/MAD, -5, 5) by trade_date", "derived", "raw", 0, "null", "cross_section_moneyflow", "cross_section"),
    _spec("industry_return_5d_rank", "percent_rank(adjusted_return_5d) by trade_date, industry_l1", "derived", "adjusted", 5, "null", "industry_relative", "cross_section"),
    _spec("industry_return_5d_excess", "adjusted_return_5d - median(adjusted_return_5d) by trade_date, industry_l1", "derived", "adjusted", 5, "null", "industry_relative", "cross_section"),
    _spec("industry_return_20d_rank", "percent_rank(adjusted_return_20d) by trade_date, industry_l1", "derived", "adjusted", 20, "null", "industry_relative", "cross_section"),
    _spec("industry_return_20d_excess", "adjusted_return_20d - median(adjusted_return_20d) by trade_date, industry_l1", "derived", "adjusted", 20, "null", "industry_relative", "cross_section"),
)

OPTIONAL_FEATURE_SPECS = (
    _spec("market_index_return_5d", "index close / lag(index close, 5) - 1", "index_daily", "raw", 5, "omit when unavailable", "market_context"),
    _spec("market_index_volatility_20d", "std(index return, 20)", "index_daily", "raw", 21, "omit when unavailable", "market_context"),
    _spec("index_turnover_ratio_20d", "index turnover / mean(index turnover, 20)", "index_dailybasic", "raw", 20, "omit when unavailable", "market_context"),
    _spec("northbound_net_flow", "northbound_net_flow", "moneyflow_hsgt", "raw", 0, "omit when unavailable", "market_context"),
)

FEATURE_NAMES = [spec.name for spec in CORE_FEATURE_SPECS]
OPTIONAL_FEATURE_NAMES = [spec.name for spec in OPTIONAL_FEATURE_SPECS]
ALL_FEATURE_NAMES = [*FEATURE_NAMES, *OPTIONAL_FEATURE_NAMES]
_DENIED_EXACT = {"entry_tradeable", "eligible_for_training", "eligible_signal_day"}
_DENIED_PREFIXES = (
    "next_", "future_", "label_", "relevance_", "tp_", "sl_", "path_ambiguous",
    "horizon_available_", "eligible_for_training_", "mfe_", "mae_", "market_median_",
    "industry_median_", "market_state_",
)


def assert_leak_free_schema(columns: Iterable[str]) -> None:
    """Reject all known label and execution fields from a supplied model schema."""
    denied = []
    for value in columns:
        name = str(value).lower()
        has_t_plus_one_token = re.search(r"(?:^|_)t(?:\+|_plus)?_?1(?:$|_)", name) is not None
        if name in _DENIED_EXACT or name.startswith(_DENIED_PREFIXES) or has_t_plus_one_token:
            denied.append(str(value))
    if denied:
        raise FeatureLeakageError("post-signal columns are forbidden: " + ", ".join(sorted(denied)))


def _model_schema(feature_schema: Iterable[str] | None) -> list[str]:
    schema = list(ALL_FEATURE_NAMES if feature_schema is None else feature_schema)
    assert_leak_free_schema(schema)
    unknown = sorted(set(schema) - set(ALL_FEATURE_NAMES))
    if unknown:
        raise ValueError("feature schema contains unknown features: " + ", ".join(unknown))
    return schema


def build_time_series_features(config: FullMarketMLConfig, panel_shard: pd.DataFrame) -> pd.DataFrame:
    """Compute symbol-local historical features only; no same-date peer information is used."""
    del config
    panel = _normalize_panel(panel_shard)
    if panel.empty:
        return panel
    assert_leak_free_schema(ALL_FEATURE_NAMES)
    result = panel.copy()
    grouped = result.groupby("symbol", sort=False, group_keys=False)
    close, opening, high, low = (result[name] for name in ("adjusted_close", "adjusted_open", "adjusted_high", "adjusted_low"))
    prior_close = grouped["adjusted_close"].shift(1)
    returns = close / prior_close - 1.0
    for window in (1, 2, 3, 5, 10, 20, 60):
        result[f"adjusted_return_{window}d"] = close / grouped["adjusted_close"].shift(window) - 1.0
    result["adjusted_open_gap_return"] = opening / prior_close - 1.0
    result["adjusted_intraday_return"] = close / opening - 1.0
    result["adjusted_high_low_range"] = high / low - 1.0
    result["adjusted_close_to_high"] = close / high - 1.0
    result["adjusted_close_to_low"] = close / low - 1.0
    for window in (5, 10, 20, 60):
        result[f"price_to_sma_{window}d"] = close / grouped["adjusted_close"].transform(lambda s: s.rolling(window, min_periods=window).mean()) - 1.0
    sma5 = grouped["adjusted_close"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    sma20 = grouped["adjusted_close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    sma60 = grouped["adjusted_close"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    result["sma_5d_to_sma_20d"] = sma5 / sma20 - 1.0
    result["sma_20d_to_sma_60d"] = sma20 / sma60 - 1.0
    ema12 = grouped["adjusted_close"].transform(lambda s: s.ewm(span=12, adjust=False, min_periods=12).mean())
    ema26 = grouped["adjusted_close"].transform(lambda s: s.ewm(span=26, adjust=False, min_periods=26).mean())
    macd = ema12 - ema26
    result["price_to_ema_12d"] = close / ema12 - 1.0
    result["price_to_ema_26d"] = close / ema26 - 1.0
    result["macd_line"] = macd
    result["macd_signal_gap"] = macd - result.groupby("symbol", sort=False)["macd_line"].transform(lambda s: s.ewm(span=9, adjust=False, min_periods=9).mean())
    for window in (5, 10, 20):
        result[f"realized_volatility_{window}d"] = returns.groupby(result["symbol"], sort=False).transform(lambda s: s.rolling(window, min_periods=window).std())
    result["downside_volatility_20d"] = returns.clip(upper=0).groupby(result["symbol"], sort=False).transform(lambda s: s.rolling(20, min_periods=20).std())
    true_range = pd.concat([(high - low), (high - prior_close).abs(), (low - prior_close).abs()], axis=1).max(axis=1)
    for window in (5, 14):
        result[f"atr_pct_{window}d"] = true_range.groupby(result["symbol"], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean()) / close
    for window in (5, 20):
        result[f"range_mean_{window}d"] = result["adjusted_high_low_range"].groupby(result["symbol"], sort=False).transform(lambda s: s.rolling(window, min_periods=window).mean())
    result["range_std_20d"] = result["adjusted_high_low_range"].groupby(result["symbol"], sort=False).transform(lambda s: s.rolling(20, min_periods=20).std())
    result["volume_log"] = np.log1p(result["volume_shares"])
    result["amount_log"] = np.log1p(result["amount_cny"])
    for source, output in (("volume_shares", "volume"), ("amount_cny", "amount")):
        for window in (5, 20):
            mean = grouped[source].transform(lambda s: s.rolling(window, min_periods=window).mean())
            result[f"{output}_ratio_{window}d"] = result[source] / mean
        result[f"{output}_change_1d"] = result[source] / grouped[source].shift(1) - 1.0
    result["volume_cv_20d"] = grouped["volume_shares"].transform(lambda s: s.rolling(20, min_periods=20).std() / s.rolling(20, min_periods=20).mean())
    _add_optional_time_series(result, grouped)
    return result


def build_cross_section_features(
    config: FullMarketMLConfig, time_series_shards: Mapping[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """Aggregate each date across all supplied symbol shards before assigning peer features."""
    del config
    if not isinstance(time_series_shards, Mapping):
        raise TypeError("time_series_shards must be a mapping of shard keys to pandas DataFrames")
    result = {str(key): value.copy() for key, value in time_series_shards.items()}
    dates = sorted({str(date) for shard in result.values() if not shard.empty for date in shard.get("trade_date", pd.Series(dtype=str)).dropna().unique()})
    for trade_date in dates:
        daily_rows = []
        for shard_key, shard in result.items():
            rows = shard.loc[shard["trade_date"].eq(trade_date)].copy()
            if not rows.empty:
                rows["_shard_key"] = shard_key
                rows["_source_index"] = rows.index
                daily_rows.append(rows)
        if not daily_rows:
            continue
        market = _cross_section_for_date(pd.concat(daily_rows, ignore_index=True))
        output_columns = [name for name in ALL_FEATURE_NAMES if name in market]
        for shard_key, shard in result.items():
            rows = market.loc[market["_shard_key"].eq(shard_key)]
            if not rows.empty:
                shard.loc[rows["_source_index"].tolist(), output_columns] = rows[output_columns].to_numpy()
    return result


def build_features_for_date(
    config: FullMarketMLConfig, panel_shard: pd.DataFrame, trade_date: str, *, feature_schema: Iterable[str] | None = None
) -> pd.DataFrame:
    """Convenience test and batch helper returning the leak-free model matrix for one date."""
    requested_schema = _model_schema(feature_schema)
    time_series = build_time_series_features(config, panel_shard)
    result = build_cross_section_features(config, {"full_market": time_series})["full_market"]
    result = result.loc[result["trade_date"].eq(_date_text(trade_date))].copy()
    for name in requested_schema:
        if name not in result:
            result[name] = np.nan
    return result[["trade_date", "symbol", *requested_schema]].reset_index(drop=True)


def write_feature_dictionary(path: str | Path) -> Path:
    """Write the human-readable, source-specific feature contract."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Full-Market ML Feature Dictionary", "", "This read-only research contract contains only signal-day and historical inputs.", "", "| Name | Group | Formula | Source | Adjusted/raw | Lookback | Missing policy | Stage |", "| --- | --- | --- | --- | --- | ---: | --- | --- |"]
    for spec in (*CORE_FEATURE_SPECS, *OPTIONAL_FEATURE_SPECS):
        lines.append(f"| `{spec.name}` | {spec.feature_group} | {spec.formula} | {spec.source_endpoint} | {spec.adjusted_status} | {spec.earliest_lookback} | {spec.missing_policy} | {spec.stage} |")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def _add_optional_time_series(result: pd.DataFrame, grouped) -> None:
    index_close = pd.to_numeric(result.get("market_index_close", pd.Series(np.nan, index=result.index)), errors="coerce")
    index_amount = pd.to_numeric(result.get("market_index_amount", pd.Series(np.nan, index=result.index)), errors="coerce")
    index_grouped = index_close.groupby(result["symbol"], sort=False)
    index_returns = index_close / index_grouped.shift(1) - 1.0
    result["market_index_return_5d"] = index_close / index_grouped.shift(5) - 1.0
    result["market_index_volatility_20d"] = index_returns.groupby(result["symbol"], sort=False).transform(
        lambda s: s.rolling(20, min_periods=20).std()
    )
    result["index_turnover_ratio_20d"] = index_amount / index_amount.groupby(result["symbol"], sort=False).transform(
        lambda s: s.rolling(20, min_periods=20).mean()
    )
    for source in ("turnover_rate", "total_mv", "circ_mv", "pe", "pb", "ps", "net_mf_amount", "listing_age_trade_days"):
        values = pd.to_numeric(result[source], errors="coerce") if source in result else pd.Series(np.nan, index=result.index)
        result[source] = values
    result["main_net_inflow_ratio"] = result["net_mf_amount"] / result["amount_cny"].where(result["amount_cny"].gt(0))
    missing_flags = (
        ("turnover_rate", "turnover_rate_missing"),
        ("total_mv", "total_mv_missing"),
        ("circ_mv", "circ_mv_missing"),
        ("pe", "pe_missing"),
        ("pb", "pb_missing"),
        ("ps", "ps_missing"),
        ("main_net_inflow_ratio", "main_net_inflow_ratio_missing"),
        ("net_mf_amount", "net_mf_amount_missing"),
        ("listing_age_trade_days", "listing_age_missing"),
    )
    for source, flag in missing_flags:
        if flag in FEATURE_NAMES:
            result[flag] = result[source].isna().astype("int8")
    result["turnover_ratio_20d"] = result["turnover_rate"] / grouped["turnover_rate"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    result["total_mv_log"] = np.log1p(result["total_mv"].where(result["total_mv"] >= 0))
    result["circ_mv_log"] = np.log1p(result["circ_mv"].where(result["circ_mv"] >= 0))
    result["float_market_value_ratio"] = result["circ_mv"] / result["total_mv"]
    result["net_mf_amount_log"] = np.sign(result["net_mf_amount"]) * np.log1p(result["net_mf_amount"].abs())
    result["net_mf_amount_ratio_20d"] = result["net_mf_amount"] / result.groupby("symbol", sort=False)["net_mf_amount"].transform(lambda s: s.abs().rolling(20, min_periods=20).mean())
    for window in (5, 20):
        result[f"moneyflow_{window}d_mean"] = result.groupby("symbol", sort=False)["main_net_inflow_ratio"].transform(lambda s: s.rolling(window, min_periods=window).mean())
    result["listing_age_log"] = np.log1p(result["listing_age_trade_days"].where(result["listing_age_trade_days"] >= 0))
    result["valid_ohlc_flag"] = result.get("valid_ohlc", pd.Series(False, index=result.index)).eq(True).astype("int8")
    result["industry_available_flag"] = result.get("industry_l1", pd.Series(pd.NA, index=result.index)).notna().astype("int8")


def _cross_section_for_date(market: pd.DataFrame) -> pd.DataFrame:
    result = market.copy()
    ranked_sources = (
        "adjusted_return_5d", "adjusted_return_10d", "adjusted_return_20d", "volume_log",
        "amount_log", "turnover_rate", "total_mv_log", "main_net_inflow_ratio", "net_mf_amount_log",
    )
    for source in ranked_sources:
        values = result[source] if source in result else pd.Series(np.nan, index=result.index)
        result[f"{source}_rank"] = values.rank(pct=True)
        result[f"{source}_robust_z"] = _robust_z(values)
    for source in ("pe", "pb", "ps", "float_market_value_ratio"):
        values = result[source] if source in result else pd.Series(np.nan, index=result.index)
        result[f"{source}_rank"] = values.rank(pct=True)
    if "industry_l1" not in result:
        result["industry_l1"] = pd.NA
    for window in (5, 20):
        source = f"adjusted_return_{window}d"
        rank_name = f"industry_return_{window}d_rank"
        excess_name = f"industry_return_{window}d_excess"
        result[rank_name] = np.nan
        result[excess_name] = np.nan
        valid = result["industry_l1"].notna()
        if valid.any():
            industry_rows = result.loc[valid]
            result.loc[valid, rank_name] = industry_rows.groupby("industry_l1", sort=False)[source].rank(pct=True)
            median = industry_rows.groupby("industry_l1", sort=False)[source].transform("median")
            result.loc[valid, excess_name] = industry_rows[source] - median
    return result


def _normalize_panel(panel_shard: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel_shard, pd.DataFrame):
        raise TypeError("panel_shard must be a pandas DataFrame")
    required = {"trade_date", "symbol", "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume_shares", "amount_cny"}
    missing = sorted(required - set(panel_shard.columns))
    if missing:
        raise ValueError("panel_shard missing columns: " + ", ".join(missing))
    panel = panel_shard.copy()
    panel["trade_date"] = panel["trade_date"].map(_date_text)
    panel["symbol"] = panel["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    for name in ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume_shares", "amount_cny"):
        panel[name] = pd.to_numeric(panel[name], errors="coerce")
    return panel.dropna(subset=["trade_date"]).sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _robust_z(values: pd.Series) -> pd.Series:
    if values.notna().sum() < 2:
        return pd.Series(np.nan, index=values.index)
    median = values.median(skipna=True)
    mad = (values - median).abs().median(skipna=True)
    if pd.isna(mad) or mad == 0:
        return pd.Series(np.nan, index=values.index)
    return ((values - median) / (1.4826 * mad)).clip(-5.0, 5.0)


def _date_text(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%Y-%m-%d") if not pd.isna(parsed) else ""
