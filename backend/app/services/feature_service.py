"""Feature construction for recommendation scoring."""
from __future__ import annotations

import copy
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

from app.services.technical_analyzer import TechnicalAnalyzer


class FeatureService:
    """Build data features without making ranking decisions."""

    def __init__(self, data_source_manager=None, news_service=None):
        self.data_source_manager = data_source_manager
        self.news_service = news_service

    def build_features(self, symbols: Iterable[str], snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        item_map = {str(item.get("symbol")): item for item in (snapshot or {}).get("items", [])}
        features = []
        for symbol in symbols:
            item = item_map.get(str(symbol), {})
            features.append(
                {
                    "symbol": str(symbol),
                    "pct_change": self._safe_float(item.get("pct_change"), 0),
                    "amount": self._safe_float(item.get("amount"), 0),
                    "turnover_rate": self._safe_float(item.get("turnover_rate"), 0),
                    "data_quality": {"snapshot": "real" if item else "missing"},
                }
            )
        return features

    def build_pick_features(
        self,
        symbol: str,
        quote_override: Optional[Dict[str, Any]] = None,
        strategy_code: str = "trend_breakout",
    ) -> Optional[Dict[str, Any]]:
        if not self.data_source_manager:
            return None

        quote = copy.deepcopy(quote_override) if quote_override else self.data_source_manager.get_realtime_quote(symbol)
        if not quote:
            return None
        quote.setdefault("code", symbol)
        quote.setdefault("name", symbol)
        if self._safe_float(quote.get("price"), 0) <= 0:
            refreshed_quote = self.data_source_manager.get_realtime_quote(symbol)
            if refreshed_quote:
                quote.update(refreshed_quote)

        history_df = self.data_source_manager.get_history_data(symbol, days=120)
        if history_df is None or history_df.empty:
            return None

        analyzed_df = TechnicalAnalyzer.analyze_all_indicators(history_df)
        indicators = TechnicalAnalyzer.get_latest_indicators(analyzed_df)
        signal = TechnicalAnalyzer.generate_signals(indicators)
        strategy = self._normalize_strategy_code(strategy_code)

        current_price = self._safe_float(quote.get("price") or indicators.get("close"), 0)
        if current_price <= 0:
            return None

        money_flow = self._build_money_flow_features(symbol, quote, quote_override)
        industry_name = (
            str((quote_override or {}).get("industry") or quote.get("industry") or "").strip()
            or self._infer_board_industry(symbol)
        )
        news_factor = self._build_news_factor(symbol, industry_name)
        technical = self._build_technical_structure(analyzed_df, indicators, current_price)
        turnover_rate = self._build_turnover_rate(quote)

        return {
            "symbol": symbol,
            "quote": quote,
            "history_df": history_df,
            "analyzed_df": analyzed_df,
            "indicators": indicators,
            "signal": signal,
            "strategy": strategy,
            "current_price": current_price,
            "industry_name": industry_name,
            "news_factor": news_factor,
            "turnover_rate": turnover_rate,
            **money_flow,
            **technical,
        }

    def _build_money_flow_features(
        self,
        symbol: str,
        quote: Dict[str, Any],
        quote_override: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        money_flow_source = "proxy"
        money_flow_quality = "proxy"
        money_flow_confidence = 0.45
        if quote_override:
            amount_yi_proxy = self._safe_float(quote.get("amount"), 0) / 100000000
            pct_proxy = self._safe_float(quote.get("pct_change"), 0)
            main_net_inflow_yi = self._clamp(amount_yi_proxy * pct_proxy / 12.0, -5.0, 5.0)
        else:
            money_flow_raw = self.data_source_manager.get_money_flow(symbol, days=3)
            if money_flow_raw:
                main_net_inflow_yi = self._safe_float(money_flow_raw.get("main_net_inflow"), 0) / 100000000
                money_flow_source = str(money_flow_raw.get("source") or "remote")
                money_flow_quality = "proxy" if money_flow_raw.get("quality") == "proxy" else "real"
                money_flow_confidence = 0.45 if money_flow_quality == "proxy" else 1.0
            else:
                main_net_inflow_yi = 0.0
                money_flow_source = "unavailable"
                money_flow_quality = "unavailable"
                money_flow_confidence = 0.0
        return {
            "main_net_inflow_yi": main_net_inflow_yi,
            "money_flow_source": money_flow_source,
            "money_flow_quality": money_flow_quality,
            "money_flow_confidence": money_flow_confidence,
        }

    def _build_news_factor(self, symbol: str, industry: str) -> Dict[str, Any]:
        default = {
            "macro_score": 50.0,
            "industry_score": 50.0,
            "stock_score": 50.0,
            "total_score": 50.0,
            "net_score": 0.0,
            "sentiment": "neutral",
            "latest_events": [],
            "updated_at": None,
        }
        if not self.news_service:
            return default
        try:
            return self.news_service.get_symbol_news_summary(symbol=symbol, industry=industry, allow_remote=False)
        except Exception:
            return default

    def _build_turnover_rate(self, quote: Dict[str, Any]) -> float:
        turnover_rate = self._safe_float(quote.get("turnover_rate"), 0)
        if turnover_rate <= 0:
            amount_yi = self._safe_float(quote.get("amount"), 0) / 100000000
            if amount_yi > 0:
                turnover_rate = self._clamp(amount_yi * 0.35, 0.2, 25)
        return turnover_rate

    def _build_technical_structure(self, analyzed_df, indicators: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        rsi = self._safe_float(indicators.get("rsi"), 50)
        macd_hist = self._safe_float(indicators.get("macd_hist"), 0)
        close_price = self._safe_float(indicators.get("close"), current_price)
        boll_lower = self._safe_float(indicators.get("boll_lower"), 0)
        boll_middle = self._safe_float(indicators.get("boll_middle"), 0)
        ma5 = self._safe_float(indicators.get("ma5"), close_price)
        ma10 = self._safe_float(indicators.get("ma10"), close_price)
        ma20 = self._safe_float(indicators.get("ma20"), close_price)
        ma60 = self._safe_float(indicators.get("ma60"), close_price)
        curr_volume = self._safe_float(analyzed_df.iloc[-1]["volume"], 0) if len(analyzed_df) >= 1 else 0
        avg_volume_5 = float(analyzed_df["volume"].tail(5).mean()) if "volume" in analyzed_df.columns and len(analyzed_df) >= 1 else 0
        volume_ratio = self._clamp(curr_volume / avg_volume_5, 0, 5) if avg_volume_5 > 0 else 1.0
        near_lower_band = bool(boll_lower > 0 and close_price <= boll_lower * 1.04)
        reclaim_middle_band = bool(boll_middle > 0 and close_price >= boll_middle * 0.99)
        prev_close = self._safe_float(analyzed_df.iloc[-2]["close"], close_price) if len(analyzed_df) >= 2 else close_price
        prev_base = self._safe_float(analyzed_df.iloc[-3]["close"], prev_close) if len(analyzed_df) >= 3 else prev_close
        prev_pct_change = ((prev_close - prev_base) / prev_base * 100) if prev_base > 0 else 0
        curr_pct_change = ((close_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
        close_5d = self._safe_float(analyzed_df.iloc[-6]["close"], close_price) if len(analyzed_df) >= 6 else close_price
        close_20d = self._safe_float(analyzed_df.iloc[-21]["close"], close_price) if len(analyzed_df) >= 21 else close_price
        return_5d_pct = ((close_price - close_5d) / close_5d * 100) if close_5d > 0 else 0
        return_20d_pct = ((close_price - close_20d) / close_20d * 100) if close_20d > 0 else 0
        recent_high_20 = float(analyzed_df["high"].tail(20).max()) if "high" in analyzed_df.columns and len(analyzed_df) >= 1 else close_price
        recent_low_20 = float(analyzed_df["low"].tail(20).min()) if "low" in analyzed_df.columns and len(analyzed_df) >= 1 else close_price
        from_20d_high_pct = ((close_price / recent_high_20) - 1) * 100 if recent_high_20 > 0 else 0
        from_20d_low_pct = ((close_price / recent_low_20) - 1) * 100 if recent_low_20 > 0 else 0
        ma_alignment = sum(
            1
            for cond in [
                close_price >= ma5 > 0,
                close_price >= ma10 > 0,
                close_price >= ma20 > 0,
                ma20 >= ma60 > 0,
            ]
            if cond
        )
        stretch_from_ma20_pct = ((close_price / ma20) - 1) * 100 if ma20 > 0 else 0
        overheated = bool(rsi >= 78 or stretch_from_ma20_pct >= 10 or return_20d_pct >= 24 or curr_pct_change >= 6.5)
        broken_downtrend = bool(
            return_20d_pct <= -14
            or from_20d_high_pct <= -22
            or (ma20 > 0 and ma60 > 0 and close_price < ma20 * 0.96 and ma20 < ma60)
        )
        rebound_day = bool(curr_pct_change > 0.6 and prev_pct_change < 0)
        oversold = bool(rsi <= 35)
        macd_repair = bool(macd_hist >= -0.03)
        pullback_score = (
            (24 if oversold else 0)
            + (18 if near_lower_band else 0)
            + (16 if rebound_day else 0)
            + (12 if macd_repair else 0)
            + (8 if reclaim_middle_band else 0)
        )
        return {
            "rsi": rsi,
            "macd_hist": macd_hist,
            "close_price": close_price,
            "boll_lower": boll_lower,
            "boll_middle": boll_middle,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "volume_ratio": volume_ratio,
            "near_lower_band": near_lower_band,
            "reclaim_middle_band": reclaim_middle_band,
            "prev_pct_change": prev_pct_change,
            "curr_pct_change": curr_pct_change,
            "return_5d_pct": return_5d_pct,
            "return_20d_pct": return_20d_pct,
            "from_20d_high_pct": from_20d_high_pct,
            "from_20d_low_pct": from_20d_low_pct,
            "ma_alignment": ma_alignment,
            "stretch_from_ma20_pct": stretch_from_ma20_pct,
            "overheated": overheated,
            "broken_downtrend": broken_downtrend,
            "rebound_day": rebound_day,
            "oversold": oversold,
            "macd_repair": macd_repair,
            "pullback_score": pullback_score,
        }

    @staticmethod
    def _normalize_strategy_code(strategy_code: Optional[str]) -> str:
        code = str(strategy_code or "trend_breakout").strip()
        return code if code in {"trend_breakout", "pullback_rebound"} else "trend_breakout"

    @staticmethod
    def _infer_board_industry(symbol: str) -> str:
        if str(symbol).startswith("688"):
            return "科创板"
        if str(symbol).startswith("300"):
            return "创业板"
        if str(symbol).startswith("60"):
            return "沪主板"
        if str(symbol).startswith("00"):
            return "深主板"
        if str(symbol).startswith(("8", "4")):
            return "北交所"
        return "未知行业"

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
