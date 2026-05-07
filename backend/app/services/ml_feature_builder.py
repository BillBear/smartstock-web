"""
Explainable ML feature builder for the investment coach.

The builder only uses information available at the signal date. Future columns
are created in a separate label step so leakage is easy to audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.services.technical_analyzer import TechnicalAnalyzer


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    category: str
    direction: str
    description: str


class MLFeatureBuilder:
    """Builds auditable model features and labels from daily OHLCV data."""

    FEATURE_SPECS: List[FeatureSpec] = [
        FeatureSpec("return_5d_pct", "5日涨跌幅", "trend_momentum", "higher_better", "短期动量强度。"),
        FeatureSpec("return_20d_pct", "20日涨跌幅", "trend_momentum", "moderate_better", "中期动量，过热会增加追高风险。"),
        FeatureSpec("ma20_gap_pct", "相对MA20乖离", "trend_momentum", "moderate_better", "价格相对20日均线的位置。"),
        FeatureSpec("ma60_gap_pct", "相对MA60乖离", "trend_momentum", "higher_better", "价格相对60日均线的位置。"),
        FeatureSpec("ma_alignment", "均线多头数量", "trend_momentum", "higher_better", "收盘价和均线排列的趋势确认数。"),
        FeatureSpec("macd_hist", "MACD柱", "trend_momentum", "higher_better", "趋势加速度代理。"),
        FeatureSpec("rsi", "RSI", "trend_momentum", "moderate_better", "超买超卖状态。"),
        FeatureSpec("boll_position", "布林带位置", "trend_momentum", "moderate_better", "价格在布林带内的位置。"),
        FeatureSpec("volume_ratio_5", "5日量比", "volume_money", "moderate_better", "当前成交量相对5日均量。"),
        FeatureSpec("volume_ratio_20", "20日量比", "volume_money", "moderate_better", "当前成交量相对20日均量。"),
        FeatureSpec("amount_yi", "成交额(亿)", "volume_money", "higher_better", "流动性强度。"),
        FeatureSpec("turnover_rate", "换手率", "volume_money", "moderate_better", "交易活跃度，过高代表博弈风险。"),
        FeatureSpec("money_flow_proxy_yi", "资金强弱代理(亿)", "volume_money", "higher_better", "无逐日资金流时由成交额和涨跌幅构造。"),
        FeatureSpec("volatility_20d", "20日波动率", "volatility_risk", "lower_better", "历史收益波动。"),
        FeatureSpec("max_drawdown_20d", "20日区间回撤", "volatility_risk", "lower_better", "近期价格回撤压力。"),
        FeatureSpec("intraday_range_pct", "日内振幅", "volatility_risk", "lower_better", "单日波动风险。"),
        FeatureSpec("from_20d_high_pct", "距20日高点", "volatility_risk", "higher_better", "越接近高点，趋势越强但也需防追高。"),
        FeatureSpec("market_state_score", "市场状态分", "market_context", "higher_better", "市场环境综合分。"),
        FeatureSpec("market_offensive", "进攻市场", "market_context", "higher_better", "市场是否处于进攻状态。"),
        FeatureSpec("market_defensive", "防守市场", "market_context", "lower_better", "市场是否处于防守状态。"),
        FeatureSpec("news_total_score", "资讯总分", "fundamental_news", "higher_better", "政策、公告和行业资讯聚合分。"),
        FeatureSpec("news_net_score", "资讯净贡献", "fundamental_news", "higher_better", "正负面资讯净影响。"),
    ]
    FEATURE_NAMES = [spec.name for spec in FEATURE_SPECS]
    FEATURE_MAP = {spec.name: spec for spec in FEATURE_SPECS}

    @staticmethod
    def _safe_div(num: pd.Series, den: pd.Series, default: float = 0.0) -> pd.Series:
        den = den.replace(0, np.nan)
        return (num / den).replace([np.inf, -np.inf], np.nan).fillna(default)

    @staticmethod
    def _ensure_indicators(df: pd.DataFrame) -> pd.DataFrame:
        local = df.copy()
        if local.empty:
            return local
        local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        local = local[local["date"].notna()].sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        required = {"ma5", "ma10", "ma20", "ma60", "macd", "macd_signal", "macd_hist", "rsi", "boll_upper", "boll_middle", "boll_lower"}
        if not required.issubset(set(local.columns)):
            local = TechnicalAnalyzer.analyze_all_indicators(local)
        if "amount" not in local.columns:
            local["amount"] = local["close"] * local["volume"]
        return local

    @classmethod
    def build_feature_frame(
        cls,
        df: pd.DataFrame,
        market_state: Optional[Dict[str, Any]] = None,
        news_factor: Optional[Dict[str, Any]] = None,
        money_flow_proxy_yi: Optional[float] = None,
        turnover_rate: Optional[float] = None,
    ) -> pd.DataFrame:
        local = cls._ensure_indicators(df)
        if local.empty:
            return local

        close = local["close"].astype(float)
        high = local["high"].astype(float)
        low = local["low"].astype(float)
        volume = local["volume"].astype(float)
        amount = local["amount"].astype(float)
        pct_change = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0) * 100

        local["return_5d_pct"] = (close / close.shift(5) - 1).replace([np.inf, -np.inf], np.nan).fillna(0) * 100
        local["return_20d_pct"] = (close / close.shift(20) - 1).replace([np.inf, -np.inf], np.nan).fillna(0) * 100
        local["ma20_gap_pct"] = cls._safe_div(close, local["ma20"].astype(float), 1.0).sub(1).mul(100)
        local["ma60_gap_pct"] = cls._safe_div(close, local["ma60"].astype(float), 1.0).sub(1).mul(100)
        local["ma_alignment"] = (
            (close >= local["ma5"].astype(float)).astype(int)
            + (local["ma5"].astype(float) >= local["ma10"].astype(float)).astype(int)
            + (local["ma10"].astype(float) >= local["ma20"].astype(float)).astype(int)
            + (local["ma20"].astype(float) >= local["ma60"].astype(float)).astype(int)
        )
        boll_width = (local["boll_upper"].astype(float) - local["boll_lower"].astype(float)).replace(0, np.nan)
        local["boll_position"] = ((close - local["boll_lower"].astype(float)) / boll_width).replace([np.inf, -np.inf], np.nan).fillna(0.5)
        local["volume_ratio_5"] = cls._safe_div(volume, volume.rolling(5).mean(), 1.0).clip(0, 8)
        local["volume_ratio_20"] = cls._safe_div(volume, volume.rolling(20).mean(), 1.0).clip(0, 8)
        local["amount_yi"] = amount / 100000000
        inferred_turnover = cls._safe_div(local["amount_yi"], local["amount_yi"].rolling(20).mean(), 1.0).clip(0.1, 10) * 3
        local["turnover_rate"] = float(turnover_rate) if turnover_rate is not None else inferred_turnover
        local["money_flow_proxy_yi"] = (
            float(money_flow_proxy_yi)
            if money_flow_proxy_yi is not None
            else (local["amount_yi"] * pct_change / 12.0).clip(-5, 5)
        )
        returns = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0)
        local["volatility_20d"] = returns.rolling(20).std().replace([np.inf, -np.inf], np.nan).fillna(0) * np.sqrt(252) * 100
        rolling_high = high.rolling(20).max().replace(0, np.nan)
        local["max_drawdown_20d"] = ((close / rolling_high) - 1).replace([np.inf, -np.inf], np.nan).fillna(0) * 100
        local["intraday_range_pct"] = cls._safe_div(high - low, close, 0.0) * 100
        local["from_20d_high_pct"] = ((close / rolling_high) - 1).replace([np.inf, -np.inf], np.nan).fillna(0) * 100

        state_tag = str((market_state or {}).get("state_tag") or "neutral")
        local["market_state_score"] = float((market_state or {}).get("state_score") or 50.0)
        local["market_offensive"] = 1.0 if state_tag == "offensive" else 0.0
        local["market_defensive"] = 1.0 if state_tag == "defensive" else 0.0
        local["news_total_score"] = float((news_factor or {}).get("total_score") or 50.0)
        local["news_net_score"] = float((news_factor or {}).get("net_score") or 0.0)

        for name in cls.FEATURE_NAMES:
            local[f"{name}_missing"] = local[name].isna().astype(int)
            local[name] = local[name].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return local

    @classmethod
    def add_forward_labels(
        cls,
        feature_df: pd.DataFrame,
        horizon_days: int = 15,
        target_return_pct: float = 8.0,
        drawdown_pct: float = 6.0,
    ) -> pd.DataFrame:
        local = feature_df.copy()
        if local.empty:
            return local
        close = local["close"].astype(float)
        future_close = close.shift(-horizon_days)
        future_high = local["high"].astype(float).shift(-1).rolling(horizon_days).max().shift(-(horizon_days - 1))
        future_low = local["low"].astype(float).shift(-1).rolling(horizon_days).min().shift(-(horizon_days - 1))
        local["future_return_pct"] = (future_close / close - 1).replace([np.inf, -np.inf], np.nan) * 100
        local["future_max_return_pct"] = (future_high / close - 1).replace([np.inf, -np.inf], np.nan) * 100
        local["future_max_drawdown_pct"] = (future_low / close - 1).replace([np.inf, -np.inf], np.nan) * 100
        local["label_up"] = (local["future_return_pct"] >= float(target_return_pct)).astype(int)
        local["label_dd"] = (local["future_max_drawdown_pct"] <= -float(drawdown_pct)).astype(int)
        local["label_risk_adjusted_return"] = local["future_return_pct"].fillna(0) + local["future_max_drawdown_pct"].fillna(0) * 0.45
        return local

    @classmethod
    def build_live_features(
        cls,
        history_df: pd.DataFrame,
        market_state: Dict[str, Any],
        news_factor: Optional[Dict[str, Any]],
        money_flow_proxy_yi: float,
        turnover_rate: float,
    ) -> Dict[str, Any]:
        frame = cls.build_feature_frame(
            history_df,
            market_state=market_state,
            news_factor=news_factor,
            money_flow_proxy_yi=money_flow_proxy_yi,
            turnover_rate=turnover_rate,
        )
        if frame.empty:
            return {"features": {}, "missing_flags": {}, "as_of_date": None}
        row = frame.iloc[-1]
        features = {name: float(row.get(name) or 0.0) for name in cls.FEATURE_NAMES}
        missing_flags = {name: int(row.get(f"{name}_missing") or 0) for name in cls.FEATURE_NAMES}
        return {
            "features": features,
            "missing_flags": missing_flags,
            "as_of_date": row.get("date"),
            "feature_schema": cls.describe_features(),
        }

    @classmethod
    def describe_features(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "label": spec.label,
                "category": spec.category,
                "direction": spec.direction,
                "description": spec.description,
            }
            for spec in cls.FEATURE_SPECS
        ]
