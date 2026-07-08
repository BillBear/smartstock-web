from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FullMarketFeatureSpec:
    name: str
    category: str
    source: str
    description: str
    adjusted: bool = False
    leakage_safe: bool = True
    missing: str = "numeric features are median-filled after missing flags are created"


FULL_MARKET_FEATURE_SPECS: List[Dict[str, Any]] = [
    {"name": "adj_return_3d", "category": "adjusted_momentum", "source": "daily+adj_factor", "description": "3-day adjusted return.", "adjusted": True},
    {"name": "adj_return_5d", "category": "adjusted_momentum", "source": "daily+adj_factor", "description": "5-day adjusted return.", "adjusted": True},
    {"name": "adj_return_10d", "category": "adjusted_momentum", "source": "daily+adj_factor", "description": "10-day adjusted return.", "adjusted": True},
    {"name": "adj_return_20d", "category": "adjusted_momentum", "source": "daily+adj_factor", "description": "20-day adjusted return.", "adjusted": True},
    {"name": "adj_return_60d", "category": "adjusted_momentum", "source": "daily+adj_factor", "description": "60-day adjusted return.", "adjusted": True},
    {"name": "adj_return_120d", "category": "adjusted_momentum", "source": "daily+adj_factor", "description": "120-day adjusted return.", "adjusted": True},
    {"name": "adj_return_20d_rank", "category": "adjusted_momentum", "source": "derived", "description": "Daily percentile rank of adjusted 20-day return.", "adjusted": True},
    {"name": "adj_return_60d_rank", "category": "adjusted_momentum", "source": "derived", "description": "Daily percentile rank of adjusted 60-day return.", "adjusted": True},
    {"name": "adj_momentum_accel_5_20", "category": "adjusted_momentum", "source": "derived", "description": "Short adjusted momentum acceleration.", "adjusted": True},
    {"name": "adj_momentum_accel_20_60", "category": "adjusted_momentum", "source": "derived", "description": "Medium adjusted momentum acceleration.", "adjusted": True},
    {"name": "ma20_gap_pct", "category": "trend_quality", "source": "daily", "description": "Close versus MA20."},
    {"name": "ma60_gap_pct", "category": "trend_quality", "source": "daily", "description": "Close versus MA60."},
    {"name": "ma_alignment", "category": "trend_quality", "source": "daily", "description": "Moving average alignment count."},
    {"name": "trend_slope_20d", "category": "trend_quality", "source": "daily", "description": "20-day log price slope."},
    {"name": "breakout_20d_count_5d", "category": "trend_quality", "source": "daily", "description": "Recent closes above previous 20-day high."},
    {"name": "distance_to_20d_high_pct", "category": "trend_quality", "source": "daily", "description": "Distance from 20-day high."},
    {"name": "recovery_from_20d_low_pct", "category": "trend_quality", "source": "daily", "description": "Distance above 20-day low."},
    {"name": "amount_log", "category": "liquidity", "source": "daily", "description": "Log traded amount."},
    {"name": "amount_rank", "category": "liquidity", "source": "derived", "description": "Daily amount percentile rank."},
    {"name": "amount_ratio_5_20", "category": "liquidity", "source": "daily", "description": "5-day versus 20-day amount average."},
    {"name": "turnover_rate", "category": "turnover", "source": "daily_basic", "description": "Daily turnover rate."},
    {"name": "turnover_rate_rank", "category": "turnover", "source": "derived", "description": "Daily turnover percentile rank."},
    {"name": "turnover_avg_5d", "category": "turnover", "source": "daily_basic", "description": "5-day average turnover."},
    {"name": "turnover_avg_20d", "category": "turnover", "source": "daily_basic", "description": "20-day average turnover."},
    {"name": "volume_ratio", "category": "liquidity", "source": "daily_basic", "description": "TuShare volume ratio."},
    {"name": "rsi_14", "category": "technical", "source": "daily", "description": "14-day RSI."},
    {"name": "macd_hist", "category": "technical", "source": "daily", "description": "MACD histogram."},
    {"name": "atr_14_pct", "category": "risk", "source": "daily", "description": "14-day ATR percentage."},
    {"name": "volatility_20d", "category": "risk", "source": "daily", "description": "20-day realized volatility."},
    {"name": "max_drawdown_20d", "category": "risk", "source": "daily", "description": "20-day historical drawdown."},
    {"name": "intraday_range_pct", "category": "risk", "source": "daily", "description": "Current day high-low range."},
    {"name": "large_down_day_count_20d", "category": "risk", "source": "daily", "description": "Count of large down days in 20 days."},
    {"name": "distance_to_up_limit_pct", "category": "limit_tradeability", "source": "stk_limit", "description": "Distance to涨停."},
    {"name": "distance_to_down_limit_pct", "category": "limit_tradeability", "source": "stk_limit", "description": "Distance to跌停."},
    {"name": "hit_limit_up_today", "category": "limit_tradeability", "source": "stk_limit", "description": "Whether signal date hit涨停."},
    {"name": "hit_limit_down_today", "category": "limit_tradeability", "source": "stk_limit", "description": "Whether signal date hit跌停."},
    {"name": "entry_tradeable", "category": "limit_tradeability", "source": "daily+stk_limit+suspend", "description": "Whether next-day entry is tradable."},
    {"name": "main_net_inflow_ratio", "category": "moneyflow", "source": "moneyflow", "description": "Main moneyflow relative to buy-side amount."},
    {"name": "main_net_inflow_rank", "category": "moneyflow", "source": "derived", "description": "Daily main moneyflow percentile rank."},
    {"name": "circ_mv_rank", "category": "valuation_size", "source": "daily_basic", "description": "Daily circulating market cap percentile rank."},
    {"name": "pe_ttm_rank", "category": "valuation_size", "source": "daily_basic", "description": "Daily PE percentile rank."},
    {"name": "pb_rank", "category": "valuation_size", "source": "daily_basic", "description": "Daily PB percentile rank."},
    {"name": "market_median_return_20d", "category": "market_context", "source": "derived", "description": "Daily median adjusted 20-day return."},
    {"name": "market_up_ratio", "category": "market_context", "source": "derived", "description": "Share of stocks up on signal date."},
    {"name": "limit_up_market_count", "category": "market_context", "source": "derived", "description": "Daily count of limit-up stocks."},
    {"name": "limit_down_market_count", "category": "market_context", "source": "derived", "description": "Daily count of limit-down stocks."},
    {"name": "industry_return_20d_rank", "category": "industry_context", "source": "derived", "description": "Daily industry 20-day return rank."},
    {"name": "excess_return_20d_vs_industry", "category": "industry_context", "source": "derived", "description": "Stock 20-day return less industry median."},
]

FEATURE_NAMES = [str(spec["name"]) for spec in FULL_MARKET_FEATURE_SPECS]


def build_full_market_features(panel: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if panel is None or panel.empty:
        return pd.DataFrame(), {"row_count": 0, "feature_missing_rates": {}}
    local = panel.copy().sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    for column in ["open", "high", "low", "close", "pre_close", "volume", "amount", "adj_close"]:
        if column not in local.columns:
            local[column] = 0.0
        local[column] = pd.to_numeric(local[column], errors="coerce")
    if "adj_close" not in local.columns or local["adj_close"].isna().all():
        local["adj_close"] = local["close"]

    parts = []
    for _, group in local.groupby("symbol", sort=False):
        parts.append(_symbol_features(group.copy()))
    featured = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if featured.empty:
        return featured, {"row_count": 0, "feature_missing_rates": {}}
    featured = featured.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    _cross_section_features(featured)
    missing_rates: Dict[str, float] = {}
    missing_flags: Dict[str, pd.Series] = {}
    for name in FEATURE_NAMES:
        if name not in featured.columns:
            featured[name] = np.nan
        missing_flags[f"{name}_missing"] = featured[name].isna().astype(int)
        missing_rates[name] = round(float(featured[name].isna().mean()), 6)
        featured[name] = pd.to_numeric(featured[name], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    featured = pd.concat([featured, pd.DataFrame(missing_flags, index=featured.index)], axis=1).copy()
    return featured, {
        "row_count": int(len(featured)),
        "feature_count": len(FEATURE_NAMES),
        "feature_missing_rates": missing_rates,
        "feature_names": FEATURE_NAMES,
    }


def write_feature_dictionary(path: str | Path) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Full Market ML Feature Dictionary",
        "",
        "All features are computed from the signal date or earlier. The `泄露未来` column must remain `否` for every feature.",
        "",
        "| Feature | Category | Source | Adjusted | 泄露未来 | Missing Handling | Description |",
        "|---|---|---|---|---|---|---|",
    ]
    for spec in FULL_MARKET_FEATURE_SPECS:
        lines.append(
            "| `{name}` | {category} | {source} | {adjusted} | 否 | {missing} | {description} |".format(
                name=spec["name"],
                category=spec["category"],
                source=spec["source"],
                adjusted="是" if spec.get("adjusted") else "否",
                missing=spec.get("missing", "missing flag + numeric fill"),
                description=spec["description"],
            )
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(output)


def _symbol_features(group: pd.DataFrame) -> pd.DataFrame:
    close = group["close"].astype(float)
    adj_close = group["adj_close"].astype(float)
    high = group["high"].astype(float)
    low = group["low"].astype(float)
    amount = pd.to_numeric(group.get("amount"), errors="coerce").fillna(0.0)
    turnover = pd.to_numeric(group.get("turnover_rate"), errors="coerce")
    returns = adj_close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    for horizon in [3, 5, 10, 20, 60, 120]:
        group[f"adj_return_{horizon}d"] = (adj_close / adj_close.shift(horizon) - 1.0) * 100.0
    group["adj_momentum_accel_5_20"] = group["adj_return_5d"] - group["adj_return_20d"] * 0.25
    group["adj_momentum_accel_20_60"] = group["adj_return_20d"] - group["adj_return_60d"] / 3.0
    ma5 = close.rolling(5, min_periods=2).mean()
    ma10 = close.rolling(10, min_periods=3).mean()
    ma20 = close.rolling(20, min_periods=5).mean()
    ma60 = close.rolling(60, min_periods=10).mean()
    group["ma20_gap_pct"] = (close / ma20 - 1.0) * 100.0
    group["ma60_gap_pct"] = (close / ma60 - 1.0) * 100.0
    group["ma_alignment"] = (close >= ma5).astype(int) + (ma5 >= ma10).astype(int) + (ma10 >= ma20).astype(int) + (ma20 >= ma60).astype(int)
    group["trend_slope_20d"] = adj_close.rolling(20, min_periods=10).apply(_rolling_log_slope, raw=True)
    prior_high = high.shift(1).rolling(20, min_periods=5).max()
    rolling_high = high.rolling(20, min_periods=5).max()
    rolling_low = low.rolling(20, min_periods=5).min()
    group["breakout_20d_count_5d"] = (close > prior_high).rolling(5, min_periods=1).sum()
    group["distance_to_20d_high_pct"] = (close / rolling_high - 1.0) * 100.0
    group["recovery_from_20d_low_pct"] = (close / rolling_low - 1.0) * 100.0
    group["amount_log"] = np.log1p(amount.clip(lower=0.0))
    group["amount_ratio_5_20"] = amount.rolling(5, min_periods=1).mean() / amount.rolling(20, min_periods=5).mean().replace(0, np.nan)
    group["turnover_avg_5d"] = turnover.rolling(5, min_periods=1).mean()
    group["turnover_avg_20d"] = turnover.rolling(20, min_periods=5).mean()
    group["rsi_14"] = _rsi(returns, 14)
    ema12 = adj_close.ewm(span=12, adjust=False).mean()
    ema26 = adj_close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    group["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    true_range = pd.concat([(high - low).abs(), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    group["atr_14_pct"] = true_range.rolling(14, min_periods=3).mean() / close.replace(0, np.nan) * 100.0
    group["volatility_20d"] = returns.rolling(20, min_periods=5).std() * np.sqrt(252) * 100.0
    group["max_drawdown_20d"] = (close / rolling_high - 1.0) * 100.0
    group["intraday_range_pct"] = (high - low) / close.replace(0, np.nan) * 100.0
    group["large_down_day_count_20d"] = (returns <= -0.05).rolling(20, min_periods=1).sum()
    group["distance_to_up_limit_pct"] = (pd.to_numeric(group.get("up_limit"), errors="coerce") - close) / close.replace(0, np.nan) * 100.0
    group["distance_to_down_limit_pct"] = (close - pd.to_numeric(group.get("down_limit"), errors="coerce")) / close.replace(0, np.nan) * 100.0
    positive_flow = pd.to_numeric(group.get("buy_lg_amount"), errors="coerce").fillna(0.0) + pd.to_numeric(group.get("buy_elg_amount"), errors="coerce").fillna(0.0)
    group["main_net_inflow_ratio"] = pd.to_numeric(group.get("net_mf_amount"), errors="coerce") / positive_flow.replace(0, np.nan)
    return group


def _cross_section_features(df: pd.DataFrame) -> None:
    df["adj_return_20d_rank"] = df.groupby("trade_date")["adj_return_20d"].rank(pct=True)
    df["adj_return_60d_rank"] = df.groupby("trade_date")["adj_return_60d"].rank(pct=True)
    df["amount_rank"] = df.groupby("trade_date")["amount"].rank(pct=True)
    df["turnover_rate_rank"] = df.groupby("trade_date")["turnover_rate"].rank(pct=True)
    df["main_net_inflow_rank"] = df.groupby("trade_date")["main_net_inflow_ratio"].rank(pct=True)
    df["circ_mv_rank"] = df.groupby("trade_date")["circ_mv"].rank(pct=True)
    df["pe_ttm_rank"] = df.groupby("trade_date")["pe_ttm"].rank(pct=True)
    df["pb_rank"] = df.groupby("trade_date")["pb"].rank(pct=True)
    df["market_median_return_20d"] = df.groupby("trade_date")["adj_return_20d"].transform("median")
    df["market_up_ratio"] = df.groupby("trade_date")["pct_chg"].transform(lambda values: float((values > 0).mean()))
    df["limit_up_market_count"] = df.groupby("trade_date")["hit_limit_up_today"].transform("sum")
    df["limit_down_market_count"] = df.groupby("trade_date")["hit_limit_down_today"].transform("sum")
    if "industry" in df.columns:
        industry_return = df.groupby(["trade_date", "industry"])["adj_return_20d"].transform("median")
        industry_rank_source = df[["trade_date", "industry"]].copy()
        industry_rank_source["industry_return"] = industry_return
        industry_rank = industry_rank_source.drop_duplicates(["trade_date", "industry"]).copy()
        industry_rank["industry_return_20d_rank"] = industry_rank.groupby("trade_date")["industry_return"].rank(pct=True)
        df["_industry_return_20d"] = industry_return
        df["excess_return_20d_vs_industry"] = df["adj_return_20d"] - industry_return
        df.drop(columns=[col for col in ["industry_return_20d_rank"] if col in df.columns], inplace=True)
        df[["trade_date", "industry"]] = df[["trade_date", "industry"]].astype(str)
        industry_rank[["trade_date", "industry"]] = industry_rank[["trade_date", "industry"]].astype(str)
        merged = df[["trade_date", "industry"]].merge(industry_rank[["trade_date", "industry", "industry_return_20d_rank"]], on=["trade_date", "industry"], how="left")
        df["industry_return_20d_rank"] = merged["industry_return_20d_rank"].to_numpy()
    else:
        df["industry_return_20d_rank"] = 0.5
        df["excess_return_20d_vs_industry"] = 0.0
    for column in ["hit_limit_up_today", "hit_limit_down_today", "entry_tradeable"]:
        df[column] = df[column].astype(int)


def _rsi(returns: pd.Series, window: int) -> pd.Series:
    gain = returns.clip(lower=0).rolling(window, min_periods=3).mean()
    loss = (-returns.clip(upper=0)).rolling(window, min_periods=3).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _rolling_log_slope(values: np.ndarray) -> float:
    y = np.log(np.asarray(values, dtype=float).clip(min=0.001))
    x = np.arange(len(y), dtype=float)
    if len(y) < 2 or not np.isfinite(y).all():
        return 0.0
    return float(np.polyfit(x, y, 1)[0])
