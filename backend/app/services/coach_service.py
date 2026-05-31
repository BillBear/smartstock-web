"""
投资教练服务（V1）
基于现有实时行情 + 技术分析，生成可执行推荐。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from statistics import mean, pstdev
from threading import RLock

import pandas as pd

from app.services.coach_store import CoachStore
from app.services.technical_analyzer import TechnicalAnalyzer


class CoachService:
    """AI自动选股教练（V1基础版）"""

    CANDIDATE_POOL = [
        "000001", "000333", "000338", "000651", "002594",
        "300058", "300750", "600036", "600519", "601318",
        "601398", "601899",
    ]

    # 全A快照短暂不可用时的真实股票兜底池。只保存代码，不保存行情价格；
    # 后续评分仍会拉取真实K线/实时行情，避免回退到过小样本或mock数据。
    CURATED_FALLBACK_POOL = [
        "000001", "000002", "000063", "000100", "000157", "000166", "000301", "000333",
        "000338", "000425", "000538", "000568", "000596", "000625", "000651", "000661",
        "000725", "000776", "000786", "000858", "000876", "000895", "000938", "000963",
        "001979", "002027", "002049", "002050", "002074", "002129", "002142", "002179",
        "002230", "002236", "002241", "002271", "002304", "002311", "002352", "002371",
        "002415", "002459", "002460", "002466", "002475", "002493", "002594", "002600",
        "002601", "002603", "002648", "002709", "002714", "002736", "002812", "002916",
        "002920", "002938", "003816", "300014", "300015", "300033", "300059", "300122",
        "300124", "300274", "300308", "300316", "300347", "300394", "300408", "300413",
        "300418", "300450", "300454", "300496", "300498", "300502", "300628", "300661",
        "300760", "300763", "300782", "300896", "300919", "300957", "300979", "301269",
        "600000", "600009", "600010", "600011", "600015", "600016", "600018", "600019",
        "600025", "600028", "600029", "600030", "600031", "600036", "600048", "600050",
        "600061", "600085", "600089", "600104", "600111", "600150", "600176", "600183",
        "600188", "600196", "600219", "600233", "600276", "600309", "600346", "600362",
        "600406", "600436", "600438", "600460", "600489", "600519", "600522", "600547",
        "600570", "600584", "600585", "600588", "600600", "600660", "600674", "600690",
        "600703", "600741", "600745", "600760", "600795", "600809", "600837", "600845",
        "600875", "600887", "600893", "600900", "600905", "600918", "600926", "600938",
        "600941", "600958", "600999", "601006", "601009", "601012", "601066", "601088",
        "601111", "601117", "601138", "601166", "601169", "601186", "601211", "601225",
        "601229", "601288", "601318", "601319", "601328", "601336", "601360", "601377",
        "601390", "601398", "601600", "601601", "601628", "601633", "601668", "601688",
        "601698", "601728", "601766", "601788", "601800", "601816", "601818", "601857",
        "601872", "601877", "601888", "601899", "601901", "601916", "601919", "601939",
        "601985", "601988", "601989", "601995", "601998", "603019", "603195", "603259",
        "603260", "603288", "603369", "603392", "603501", "603659", "603799", "603806",
        "603833", "603986", "603993", "605117", "605499", "688008", "688012", "688036",
        "688041", "688111", "688126", "688169", "688187", "688223", "688256", "688271",
        "688303", "688363", "688396", "688599", "688981",
    ]

    MARKET_SAMPLE_POOL = ["000001", "000333", "002594", "300750", "600519", "601318"]

    THEME_WATCH_CONFIG: Dict[str, List[str]] = {
        "存储": ["603986", "688008", "301308", "688525", "001309", "300223", "000021", "300475"],
        "算力": ["601138", "300308", "300502", "300394", "000977", "603019", "000938", "688256"],
        "AI服务器": ["601138", "000977", "603019", "000938", "002463", "301308"],
        "光模块": ["300308", "300502", "300394", "002281", "603083", "688313"],
        "液冷": ["002837", "301018", "300499", "300602", "002011"],
        "半导体": ["688981", "603501", "688012", "688041", "600584", "600460", "603986", "688008"],
    }

    THEME_KEYWORDS = {
        "存储": ["存储", "半导体", "芯片", "DRAM", "NAND"],
        "算力": ["算力", "服务器", "计算机", "通信设备", "数据中心"],
        "AI服务器": ["服务器", "数据中心", "计算机设备"],
        "光模块": ["光模块", "光通信", "通信设备"],
        "液冷": ["液冷", "制冷", "温控", "数据中心"],
        "半导体": ["半导体", "芯片", "集成电路", "电子元件"],
    }

    THEME_SYMBOL_NAMES = {
        "603986": "兆易创新", "688008": "澜起科技", "301308": "江波龙", "688525": "佰维存储",
        "001309": "德明利", "300223": "北京君正", "000021": "深科技", "300475": "香农芯创",
        "601138": "工业富联", "300308": "中际旭创", "300502": "新易盛", "300394": "天孚通信",
        "000977": "浪潮信息", "603019": "中科曙光", "000938": "紫光股份", "688256": "寒武纪",
        "002463": "沪电股份", "002281": "光迅科技", "603083": "剑桥科技", "688313": "仕佳光子",
        "002837": "英维克", "301018": "申菱环境", "300499": "高澜股份", "300602": "飞荣达",
        "002011": "盾安环境", "688981": "中芯国际", "603501": "韦尔股份", "688012": "中微公司",
        "688041": "海光信息", "600584": "长电科技", "600460": "士兰微",
    }

    DEFAULT_RISK_PROFILE: Dict[str, Any] = {
        "risk_level": "medium",
        "horizon_days_min": 5,
        "horizon_days_max": 20,
        "max_position_pct": 10,
        "max_industry_pct": 30,
    }

    STRATEGY_PRESET_LIBRARY: Dict[str, List[Dict[str, Any]]] = {
        "trend_breakout": [
            {
                "profile_key": "breakout_balanced",
                "label": "突破-均衡(推荐)",
                "description": "适合大多数个人投资者，兼顾收益与回撤。",
                "config": {
                    "risk_level": "medium",
                    "holding_days": 15,
                    "stop_profit_pct": 15,
                    "stop_loss_pct": 8,
                    "score_threshold": 72,
                    "commission": 0.0003,
                    "slippage": 0.001,
                    "max_positions": 5,
                    "max_position_pct": 10,
                    "universe_size": 140,
                },
            },
            {
                "profile_key": "breakout_aggressive",
                "label": "突破-进攻",
                "description": "提高交易频率与进攻性，波动更大。",
                "config": {
                    "risk_level": "high",
                    "holding_days": 12,
                    "stop_profit_pct": 18,
                    "stop_loss_pct": 10,
                    "score_threshold": 68,
                    "commission": 0.0003,
                    "slippage": 0.0012,
                    "max_positions": 6,
                    "max_position_pct": 12,
                    "universe_size": 180,
                },
            },
            {
                "profile_key": "breakout_defensive",
                "label": "突破-防守",
                "description": "过滤更严格，优先控制回撤。",
                "config": {
                    "risk_level": "low",
                    "holding_days": 18,
                    "stop_profit_pct": 12,
                    "stop_loss_pct": 6,
                    "score_threshold": 78,
                    "commission": 0.0003,
                    "slippage": 0.0008,
                    "max_positions": 4,
                    "max_position_pct": 8,
                    "universe_size": 110,
                },
            },
        ],
        "pullback_rebound": [
            {
                "profile_key": "rebound_balanced",
                "label": "回调修复-均衡(推荐)",
                "description": "偏向震荡修复段，胜率优先。",
                "config": {
                    "risk_level": "medium",
                    "holding_days": 12,
                    "stop_profit_pct": 12,
                    "stop_loss_pct": 7,
                    "score_threshold": 68,
                    "commission": 0.0003,
                    "slippage": 0.001,
                    "max_positions": 5,
                    "max_position_pct": 9,
                    "universe_size": 130,
                },
            },
            {
                "profile_key": "rebound_fast",
                "label": "回调修复-快进快出",
                "description": "更短持仓，更快止盈止损。",
                "config": {
                    "risk_level": "medium",
                    "holding_days": 8,
                    "stop_profit_pct": 10,
                    "stop_loss_pct": 6,
                    "score_threshold": 66,
                    "commission": 0.0003,
                    "slippage": 0.0012,
                    "max_positions": 6,
                    "max_position_pct": 10,
                    "universe_size": 150,
                },
            },
            {
                "profile_key": "rebound_defensive",
                "label": "回调修复-防守",
                "description": "强调风险控制，降低仓位暴露。",
                "config": {
                    "risk_level": "low",
                    "holding_days": 14,
                    "stop_profit_pct": 10,
                    "stop_loss_pct": 5,
                    "score_threshold": 72,
                    "commission": 0.0003,
                    "slippage": 0.0008,
                    "max_positions": 4,
                    "max_position_pct": 7,
                    "universe_size": 100,
                },
            },
        ],
    }
    LIVE_GATE_RULES: List[Dict[str, Any]] = [
        {"key": "mock_fallback_disabled", "label": "禁用Mock兜底", "threshold": "必须禁用"},
        {"key": "closed_roundtrips", "label": "闭环交易数", "threshold": ">= 80"},
        {"key": "calendar_days", "label": "回测自然日", "threshold": ">= 360"},
        {"key": "valid_history_symbols", "label": "有效样本股票", "threshold": ">= 120"},
        {"key": "sharpe", "label": "夏普比率", "threshold": ">= 1.00"},
        {"key": "max_drawdown", "label": "最大回撤", "threshold": "<= 20.00%"},
        {"key": "win_rate", "label": "胜率", "threshold": ">= 54.00%"},
        {"key": "profit_loss_ratio", "label": "盈亏比", "threshold": ">= 1.35"},
        {"key": "monthly_positive_ratio", "label": "月度正收益占比", "threshold": ">= 55.00%"},
        {"key": "monthly_count", "label": "月度样本数", "threshold": ">= 9"},
        {"key": "credibility_score", "label": "可信度评分", "threshold": ">= 80"},
    ]

    def __init__(
        self,
        data_source_manager,
        store: CoachStore,
        news_service=None,
        ml_model_service=None,
        ml_explain_service=None,
        market_snapshot_service=None,
        data_quality_service=None,
        universe_service=None,
        feature_service=None,
        market_theme_service=None,
        scoring_service=None,
        today_picks_cache_ttl_seconds: int = 0,
        universe_refresh_seconds: int = 1200,
        universe_intraday_refresh_seconds: int = 90,
        universe_min_amount_yi: float = 2.0,
        universe_max_analyze_count: int = 60,
        universe_industry_cap: int = 3,
        universe_min_price: float = 2.0,
    ):
        self.data_source_manager = data_source_manager
        self.store = store
        self.news_service = news_service
        self.ml_model_service = ml_model_service
        self.ml_explain_service = ml_explain_service
        self.market_snapshot_service = market_snapshot_service
        self.data_quality_service = data_quality_service
        self.universe_service = universe_service
        self.feature_service = feature_service
        self.market_theme_service = market_theme_service
        self.scoring_service = scoring_service
        self._pick_history: Dict[str, List[Dict[str, Any]]] = {}
        self._daily_snapshots: Dict[str, Dict[str, Any]] = {}
        self._backtest_runs: Dict[str, Dict[str, Any]] = {}
        self._today_picks_cache: Dict[str, Dict[str, Any]] = {}
        self._refresh_state: Dict[str, Any] = {
            "is_refreshing": False,
            "last_started_at": None,
            "last_finished_at": None,
            "last_error": None,
        }
        self._today_picks_cache_ttl_seconds = max(0, int(today_picks_cache_ttl_seconds or 0))
        self._universe_refresh_seconds = max(60, int(universe_refresh_seconds or 1200))
        self._universe_intraday_refresh_seconds = max(15, int(universe_intraday_refresh_seconds or 90))
        self._universe_min_amount_yi = max(0.1, float(universe_min_amount_yi or 2.0))
        self._universe_max_analyze_count = max(20, min(int(universe_max_analyze_count or 60), 200))
        self._universe_industry_cap = max(1, min(int(universe_industry_cap or 3), 8))
        self._universe_min_price = max(0.1, float(universe_min_price or 2.0))
        self._universe_lock = RLock()
        self._universe_state: Dict[str, Any] = {
            "entries": [],
            "entry_map": {},
            "last_full_refresh_ts": 0.0,
            "last_full_refresh_at": None,
            "last_refresh_attempt_ts": 0.0,
            "last_incremental_refresh_ts": 0.0,
            "last_incremental_refresh_at": None,
            "last_meta": {},
        }

    def get_refresh_state(self) -> Dict[str, Any]:
        return copy.deepcopy(self._refresh_state)

    def mark_refresh_started(self) -> None:
        self._refresh_state.update(
            {
                "is_refreshing": True,
                "last_started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_error": None,
            }
        )

    def mark_refresh_finished(self, error: Optional[str] = None) -> None:
        self._refresh_state.update(
            {
                "is_refreshing": False,
                "last_finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_error": error,
            }
        )

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _extract_symbol_from_pick_id(pick_id: str) -> str:
        parts = pick_id.split("-")
        # pick_id 格式示例: 2026-02-25-300058-S1，需要从尾部反向提取 6 位代码
        for part in reversed(parts):
            if re.fullmatch(r"\d{6}", part or ""):
                return part
        return ""

    def _invalidate_user_cache(self, user_id: str) -> None:
        prefix = f":{user_id}:"
        keys = [key for key in self._today_picks_cache.keys() if prefix in key]
        for key in keys:
            self._today_picks_cache.pop(key, None)

    @staticmethod
    def _now_ts() -> float:
        return datetime.now().timestamp()

    def _infer_snapshot_trade_date(self, snapshot: Optional[Dict[str, Any]]) -> str:
        """Prefer the quote timestamp over wall-clock date for weekends/holidays."""
        fallback = datetime.now().strftime("%Y-%m-%d")
        items = list((snapshot or {}).get("items") or [])
        dates: List[str] = []
        for item in items[: min(len(items), 200)]:
            raw = item.get("trade_date") or item.get("date") or item.get("update_time")
            text = str(raw or "").strip()
            if len(text) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", text):
                dates.append(text[:10])
            elif len(text) >= 8 and re.match(r"^\d{8}", text):
                dates.append(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
        if dates:
            return max(dates)
        return str((snapshot or {}).get("trade_date") or fallback)

    def _recommendation_trade_date(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        if self.market_snapshot_service:
            try:
                snapshot = self.market_snapshot_service.get_latest_valid_snapshot(today)
                if snapshot:
                    return self._infer_snapshot_trade_date(snapshot)
            except Exception:
                pass
        return today

    def _curated_fallback_candidates(self, target_size: Optional[int] = None) -> List[Dict[str, Any]]:
        theme_symbols: List[str] = []
        for symbols in self.THEME_WATCH_CONFIG.values():
            theme_symbols.extend(symbols)
        # 兜底候选只用于数据源降级时维持页面可用，不能让固定主题名单主导推荐。
        merged_pool = list(dict.fromkeys([*self.CURATED_FALLBACK_POOL, *theme_symbols]))
        limit = max(30, min(int(target_size or 120), len(merged_pool)))
        return [{"symbol": symbol} for symbol in merged_pool[:limit]]

    @staticmethod
    def _is_excluded_name(name: str) -> bool:
        if not name:
            return True
        upper = name.upper()
        return ("ST" in upper) or ("退" in name)

    @staticmethod
    def _infer_board_industry(symbol: str) -> str:
        if symbol.startswith("688"):
            return "科创板"
        if symbol.startswith("300"):
            return "创业板"
        if symbol.startswith("60"):
            return "沪主板"
        if symbol.startswith("00"):
            return "深主板"
        if symbol.startswith(("8", "4")):
            return "北交所"
        return "未知行业"

    @classmethod
    def _theme_tags_for_stock(cls, symbol: str, name: str = "", industry: str = "") -> List[str]:
        tags = []
        text = f"{name} {industry}".upper()
        for theme, symbols in cls.THEME_WATCH_CONFIG.items():
            keywords = cls.THEME_KEYWORDS.get(theme, [])
            if symbol in symbols or any(str(keyword).upper() in text for keyword in keywords):
                tags.append(theme)
        return list(dict.fromkeys(tags))

    @staticmethod
    def _is_generic_market_theme(theme_name: str) -> bool:
        text = str(theme_name or "")
        generic_keywords = [
            "高股息",
            "证金",
            "融资融券",
            "沪股通",
            "深股通",
            "国企改革",
            "超级品牌",
            "MSCI",
            "标普",
        ]
        return any(keyword in text for keyword in generic_keywords)

    def _get_market_theme_context(self, limit: int = 12) -> Dict[str, Any]:
        if not self.market_theme_service:
            return {"status": "unavailable", "theme_rank": [], "data_quality": {"is_reliable": False}}
        try:
            payload = self.market_theme_service.get_today_themes(force=False, limit=limit) or {}
            if (payload.get("data_quality") or {}).get("is_reliable") is False:
                return payload
            return payload
        except Exception:
            return {"status": "unavailable", "theme_rank": [], "data_quality": {"is_reliable": False}}

    def _compute_theme_alignment(
        self,
        symbol: str,
        name: str,
        industry: str,
        theme_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        themes = list((theme_payload or {}).get("theme_rank") or [])
        if not themes:
            return {
                "theme_rank_score": 0.0,
                "theme_tags": [],
                "matched_theme_ids": [],
                "matched_themes": [],
                "theme_alignment_reason": "市场主线数据不可用，未参与评分。",
                "theme_alignment_quality": "unavailable",
            }

        text = f"{symbol} {name} {industry}".lower()
        matched = []
        for rank_no, theme in enumerate(themes, start=1):
            theme_name = str(theme.get("theme_name") or "").strip()
            if not theme_name:
                continue
            top_symbols = theme.get("top_symbols") or []
            symbol_hit = any(str(item.get("symbol") or "") == str(symbol) for item in top_symbols)
            lower_theme = theme_name.lower()
            text_hit = lower_theme in text or (industry and str(industry).strip() in theme_name)
            # 行业细分经常比板块名称更窄，例如“火力发电”应归入“电力”。
            if not symbol_hit and not text_hit and len(theme_name) >= 2:
                text_hit = theme_name[:2] in text
            if not (symbol_hit or text_hit):
                continue
            strength = self._safe_float(theme.get("strength_score"), 0)
            money = self._safe_float(theme.get("money_flow_score"), 0)
            rank_bonus = max(0.0, 16.0 - rank_no * 1.4)
            score = self._clamp(strength * 0.55 + money * 0.25 + rank_bonus, 0, 100)
            if self._is_generic_market_theme(theme_name):
                score = min(score, 62.0)
            matched.append(
                {
                    "theme_id": theme.get("theme_id"),
                    "theme_name": theme_name,
                    "category": theme.get("category"),
                    "rank_no": rank_no,
                    "strength_score": round(strength, 2),
                    "money_flow_score": round(money, 2),
                    "alignment_score": round(score, 2),
                    "generic": self._is_generic_market_theme(theme_name),
                }
            )

        matched.sort(key=lambda item: item.get("alignment_score", 0), reverse=True)
        best_score = self._safe_float((matched[0] if matched else {}).get("alignment_score"), 0)
        theme_tags = [item["theme_name"] for item in matched[:3] if item.get("theme_name")]
        matched_ids = [item["theme_id"] for item in matched[:3] if item.get("theme_id")]
        return {
            "theme_rank_score": round(best_score, 2),
            "theme_tags": theme_tags,
            "matched_theme_ids": matched_ids,
            "matched_themes": matched[:3],
            "theme_alignment_reason": (
                f"匹配当前市场主线：{'、'.join(theme_tags)}"
                if matched
                else "未匹配到当前前排市场主线，排序会小幅降权。"
            ),
            "theme_alignment_quality": "matched" if matched else "unmatched",
        }

    def _apply_theme_alignment(
        self,
        picks: List[Dict[str, Any]],
        candidate_rows: List[Dict[str, Any]],
        theme_payload: Dict[str, Any],
    ) -> None:
        if not picks:
            return
        row_map = {str(row.get("symbol") or ""): row for row in candidate_rows or []}
        reliable = bool((theme_payload or {}).get("data_quality", {}).get("is_reliable"))
        for pick in picks:
            symbol = str(pick.get("symbol") or "")
            row = row_map.get(symbol) or {}
            industry = str(pick.get("industry") or row.get("industry") or "")
            name = str(pick.get("name") or row.get("name") or symbol)
            alignment = self._compute_theme_alignment(symbol, name, industry, theme_payload if reliable else {})
            pick.update(
                {
                    "industry": industry,
                    "theme_rank_score": alignment.get("theme_rank_score", 0),
                    "theme_tags": alignment.get("theme_tags") or [],
                    "matched_theme_ids": alignment.get("matched_theme_ids") or [],
                    "matched_themes": alignment.get("matched_themes") or [],
                }
            )
            evidence = pick.setdefault("evidence_summary", {})
            evidence["theme_alignment"] = {
                "score": alignment.get("theme_rank_score", 0),
                "quality": alignment.get("theme_alignment_quality"),
                "reason": alignment.get("theme_alignment_reason"),
            }
            reasons = pick.setdefault("reasons", [])
            reason = alignment.get("theme_alignment_reason")
            if reason and reason not in reasons:
                reasons.append(reason)
                pick["reasons"] = reasons[:5]

            breakdown = pick.setdefault("score_breakdown", {})
            theme_score = self._safe_float(alignment.get("theme_rank_score"), 0)
            if self.scoring_service:
                self.scoring_service.apply_theme_adjustment(pick, theme_score, reliable)
            else:
                breakdown["theme"] = round(theme_score, 2)
                if "pre_theme_total" not in breakdown:
                    breakdown["pre_theme_total"] = round(self._safe_float(breakdown.get("total"), pick.get("score") or 0), 2)
                current_total = self._safe_float(breakdown.get("pre_theme_total"), breakdown.get("total") or pick.get("score") or 0)
                if not reliable:
                    adjustment = 0.0
                elif theme_score > 0:
                    adjustment = self._clamp((theme_score - 55.0) * 0.10, -1.0, 4.5)
                else:
                    adjustment = -3.0
                breakdown["theme_adjustment"] = round(adjustment, 2)
                breakdown["total"] = round(self._clamp(current_total + adjustment, 0, 100), 2)
                pick["score_breakdown"] = breakdown
                pick["score"] = breakdown["total"]

    def _theme_momentum_metrics(self, symbol: str, quote: Dict[str, Any]) -> Dict[str, Any]:
        price = self._safe_float(quote.get("price") or quote.get("current_price"), 0)
        pct_change = self._safe_float(quote.get("pct_change") or quote.get("change_percent"), 0)
        amount = self._safe_float(quote.get("amount") or quote.get("turnover"), 0)
        metrics = {
            "current_price": round(price, 3) if price > 0 else None,
            "return_1d_pct": round(pct_change, 2),
            "return_5d_pct": None,
            "return_10d_pct": None,
            "return_20d_pct": None,
            "amount_ratio_20d": None,
            "new_high_20d": False,
        }
        try:
            df = self.data_source_manager.get_history_data(symbol, days=32)
            if df is None or df.empty or "close" not in df.columns:
                return metrics
            closes = [self._safe_float(v, 0) for v in df["close"].tolist() if self._safe_float(v, 0) > 0]
            current = price or (closes[-1] if closes else 0)
            if current > 0:
                metrics["current_price"] = round(current, 3)
            for days, key in [(5, "return_5d_pct"), (10, "return_10d_pct"), (20, "return_20d_pct")]:
                if current > 0 and len(closes) > days and closes[-days - 1] > 0:
                    metrics[key] = round((current / closes[-days - 1] - 1) * 100, 2)
            if current > 0 and closes:
                recent = closes[-20:] if len(closes) >= 20 else closes
                metrics["new_high_20d"] = current >= max(recent)
            amount_col = None
            for col in ["amount", "turnover"]:
                if col in df.columns:
                    amount_col = col
                    break
            if amount_col:
                amounts = [self._safe_float(v, 0) for v in df[amount_col].tolist() if self._safe_float(v, 0) > 0]
                if amount > 0 and len(amounts) >= 5:
                    base = mean(amounts[-20:]) if len(amounts) >= 20 else mean(amounts)
                    if base > 0:
                        metrics["amount_ratio_20d"] = round(amount / base, 2)
        except Exception:
            return metrics
        return metrics

    def _build_theme_watchlist(
        self,
        entries: List[Dict[str, Any]],
        industry_map: Dict[str, str],
        limit: int = 24,
    ) -> List[Dict[str, Any]]:
        entry_map = {str(item.get("symbol") or ""): item for item in entries if item.get("symbol")}
        configured_symbols = []
        for symbols in self.THEME_WATCH_CONFIG.values():
            configured_symbols.extend(symbols)
        configured_symbols = list(dict.fromkeys(configured_symbols))

        missing_symbols = [symbol for symbol in configured_symbols if symbol not in entry_map]
        quote_map: Dict[str, Dict[str, Any]] = {}
        if missing_symbols:
            try:
                quote_map = self.data_source_manager.get_realtime_quotes_batch(missing_symbols[:80]) or {}
            except Exception:
                quote_map = {}
        basic_map: Dict[str, Dict[str, Any]] = {}
        try:
            basic_map = self.data_source_manager.get_stock_basic_map() or {}
        except Exception:
            basic_map = {}

        rows: List[Dict[str, Any]] = []
        candidate_symbols = list(dict.fromkeys([*configured_symbols, *list(entry_map.keys())]))
        history_metric_deadline = self._now_ts() + 4.0
        for symbol in candidate_symbols:
            row = copy.deepcopy(entry_map.get(symbol) or quote_map.get(symbol) or {"symbol": symbol})
            basic = basic_map.get(symbol) or {}
            raw_name = str(row.get("name") or basic.get("name") or "").strip()
            name = raw_name if raw_name and raw_name != symbol else self.THEME_SYMBOL_NAMES.get(symbol, symbol)
            industry = str(industry_map.get(symbol) or row.get("industry") or basic.get("industry") or self._infer_board_industry(symbol))
            tags = self._theme_tags_for_stock(symbol, name, industry)
            if not tags:
                continue
            row["industry"] = industry
            should_fetch_history = symbol in configured_symbols and self._now_ts() < history_metric_deadline
            metrics = self._theme_momentum_metrics(symbol, row) if should_fetch_history else {
                "current_price": self._safe_float(row.get("price") or row.get("current_price"), 0) or None,
                "return_1d_pct": round(self._safe_float(row.get("pct_change"), 0), 2),
                "return_5d_pct": None,
                "return_10d_pct": None,
                "return_20d_pct": None,
                "amount_ratio_20d": None,
                "new_high_20d": False,
            }
            return_20 = self._safe_float(metrics.get("return_20d_pct"), 0)
            return_10 = self._safe_float(metrics.get("return_10d_pct"), 0)
            return_5 = self._safe_float(metrics.get("return_5d_pct"), 0)
            return_1 = self._safe_float(metrics.get("return_1d_pct"), 0)
            amount_ratio = self._safe_float(metrics.get("amount_ratio_20d"), 1)
            theme_score = self._clamp(
                50 + return_20 * 1.1 + return_10 * 0.9 + return_5 * 0.7 + return_1 * 0.5 + (amount_ratio - 1) * 10,
                0,
                100,
            )
            if metrics.get("new_high_20d"):
                theme_score = self._clamp(theme_score + 6, 0, 100)
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "industry": industry,
                    "themes": tags,
                    "price": self._safe_float(row.get("price") or row.get("current_price") or metrics.get("current_price"), 0),
                    "pct_change": round(self._safe_float(row.get("pct_change") or row.get("change_percent"), 0), 2),
                    "amount_yi": round(self._safe_float(row.get("amount") or row.get("turnover"), 0) / 100000000, 2),
                    "theme_score": round(theme_score, 2),
                    "momentum_metrics": metrics,
                    "source": "configured_theme" if symbol in configured_symbols else "snapshot_theme_keyword",
                }
            )
        rows.sort(key=lambda item: (item.get("theme_score", 0), item.get("amount_yi", 0)), reverse=True)
        return rows[:limit]

    def _build_excluded_examples(
        self,
        theme_watchlist: List[Dict[str, Any]],
        analyzed_picks: List[Dict[str, Any]],
        final_picks: List[Dict[str, Any]],
        candidate_rows: List[Dict[str, Any]],
        limit: int = 12,
    ) -> List[Dict[str, Any]]:
        final_symbols = {str(p.get("symbol") or "") for p in final_picks}
        analyzed_by_symbol = {str(p.get("symbol") or ""): p for p in analyzed_picks if p.get("symbol")}
        candidate_symbols = {str(row.get("symbol") or "") for row in candidate_rows}
        examples: List[Dict[str, Any]] = []
        for item in theme_watchlist:
            symbol = str(item.get("symbol") or "")
            if not symbol or symbol in final_symbols:
                continue
            analyzed = analyzed_by_symbol.get(symbol)
            if analyzed:
                breakdown = analyzed.get("score_breakdown") or {}
                dd_prob = self._safe_float(analyzed.get("dd_prob"), 0)
                action = analyzed.get("action")
                if dd_prob >= 0.30:
                    reason = f"强势主题但回撤概率偏高（{dd_prob * 100:.1f}%），暂不进入买入池"
                elif action != "buy":
                    reason = "强势主题进入观察，但当前策略动作不是买入"
                elif self._safe_float(breakdown.get("total"), 0) < 68:
                    reason = f"综合评分不足（{self._safe_float(breakdown.get('total'), 0):.1f}），保留观察"
                else:
                    reason = "通过部分条件但未进入最终仓位上限，保留观察"
                score = breakdown.get("total")
            elif symbol in candidate_symbols:
                reason = "进入预筛候选，但未排入本轮深度分析预算"
                score = None
            else:
                reason = "属于强势主题观察池，但未满足当前策略的基础流动性/形态过滤"
                score = None
            examples.append(
                {
                    "symbol": symbol,
                    "name": item.get("name") or symbol,
                    "themes": item.get("themes") or [],
                    "theme_score": item.get("theme_score"),
                    "score": score,
                    "reason": reason,
                }
            )
            if len(examples) >= limit:
                break
        return examples

    def _get_universe_rules(self, risk_level: str) -> Dict[str, Any]:
        if risk_level == "low":
            return {
                "min_amount_yi": max(self._universe_min_amount_yi, 4.0),
                "min_turnover_rate": 0.8,
                "max_turnover_rate": 12.0,
                "max_abs_pct_change": 8.0,
                "max_analyze_count": min(max(self._universe_max_analyze_count, 90), 120),
                "industry_cap": self._universe_industry_cap,
                "min_price": self._universe_min_price,
            }
        if risk_level == "high":
            return {
                "min_amount_yi": max(self._universe_min_amount_yi * 0.5, 1.0),
                "min_turnover_rate": 0.5,
                "max_turnover_rate": 35.0,
                "max_abs_pct_change": 15.0,
                "max_analyze_count": min(max(self._universe_max_analyze_count + 60, 140), 200),
                "industry_cap": min(self._universe_industry_cap + 1, 8),
                "min_price": max(self._universe_min_price * 0.8, 1.0),
            }
        return {
            "min_amount_yi": self._universe_min_amount_yi,
            "min_turnover_rate": 0.8,
            "max_turnover_rate": 20.0,
            "max_abs_pct_change": 12.0,
            "max_analyze_count": max(self._universe_max_analyze_count, 120),
            "industry_cap": self._universe_industry_cap,
            "min_price": self._universe_min_price,
        }

    def _get_universe_snapshot(self, force: bool = False) -> List[Dict[str, Any]]:
        now_ts = self._now_ts()
        with self._universe_lock:
            cache_ok = (
                not force
                and self._universe_state["entries"]
                and (now_ts - float(self._universe_state.get("last_full_refresh_ts") or 0) < self._universe_refresh_seconds)
            )
            if cache_ok:
                return copy.deepcopy(self._universe_state["entries"])
            recent_attempt = now_ts - float(self._universe_state.get("last_refresh_attempt_ts") or 0) < 120
            if recent_attempt and self._universe_state["entries"]:
                return copy.deepcopy(self._universe_state["entries"])
            if recent_attempt and not force:
                return []
            self._universe_state["last_refresh_attempt_ts"] = now_ts

        items = []
        executor = ThreadPoolExecutor(max_workers=1)
        snapshot_payload = {}
        if self.market_snapshot_service:
            future = executor.submit(self.market_snapshot_service.ensure_snapshot_for_recommendation)
        else:
            future = executor.submit(self.data_source_manager.get_a_share_snapshot)
        try:
            completed, pending = wait([future], timeout=8)
            if future in completed:
                result = future.result() or []
                if isinstance(result, dict):
                    snapshot_payload = result
                    items = result.get("items") or []
                else:
                    items = result or []
            else:
                future.cancel()
        except Exception:
            items = []
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if not items:
            with self._universe_lock:
                return copy.deepcopy(self._universe_state["entries"])

        entry_map = {item["symbol"]: item for item in items if item.get("symbol")}
        refresh_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._universe_lock:
            self._universe_state["entries"] = items
            self._universe_state["entry_map"] = entry_map
            self._universe_state["last_full_refresh_ts"] = now_ts
            self._universe_state["last_full_refresh_at"] = refresh_at
            self._universe_state["last_snapshot_payload"] = copy.deepcopy(snapshot_payload)
        return copy.deepcopy(items)

    def _refresh_intraday_candidates(self, symbols: List[str]) -> None:
        now_ts = self._now_ts()
        with self._universe_lock:
            if now_ts - float(self._universe_state.get("last_incremental_refresh_ts") or 0) < self._universe_intraday_refresh_seconds:
                return
            entry_map = copy.deepcopy(self._universe_state.get("entry_map") or {})

        changed = 0
        symbol_batch = symbols[: min(80, len(symbols))]
        quotes_map = self.data_source_manager.get_realtime_quotes_batch(symbol_batch)
        for symbol in symbol_batch:
            quote = quotes_map.get(symbol)
            if not quote:
                continue
            prev = entry_map.get(symbol, {})
            prev.update(
                {
                    "symbol": symbol,
                    "name": quote.get("name", prev.get("name", symbol)),
                    "price": float(quote.get("price") or prev.get("price") or 0),
                    "change": float(quote.get("change") or prev.get("change") or 0),
                    "pct_change": float(quote.get("pct_change") or prev.get("pct_change") or 0),
                    "open": float(quote.get("open") or prev.get("open") or 0),
                    "high": float(quote.get("high") or prev.get("high") or 0),
                    "low": float(quote.get("low") or prev.get("low") or 0),
                    "volume": float(quote.get("volume") or prev.get("volume") or 0),
                    "amount": float(quote.get("amount") or prev.get("amount") or 0),
                    "turnover_rate": float(quote.get("turnover_rate") or prev.get("turnover_rate") or 0),
                    "update_time": quote.get("update_time"),
                    "industry": prev.get("industry", "未知行业"),
                }
            )
            entry_map[symbol] = prev
            changed += 1

        if changed <= 0:
            return

        with self._universe_lock:
            self._universe_state["entry_map"] = entry_map
            self._universe_state["entries"] = list(entry_map.values())
            self._universe_state["last_incremental_refresh_ts"] = now_ts
            self._universe_state["last_incremental_refresh_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _build_dynamic_candidates(
        self,
        risk_level: str,
        target_size: Optional[int] = None,
        strategy_code: str = "trend_breakout",
    ) -> Dict[str, Any]:
        if self.universe_service:
            return self.universe_service.build_dynamic_candidates(
                risk_level=risk_level,
                target_size=target_size,
                strategy_code=strategy_code,
            )
        entries = self._get_universe_snapshot(force=False)
        industry_map = self.data_source_manager.get_stock_industry_map()
        if not entries:
            fallback = self._curated_fallback_candidates(target_size)
            theme_watchlist = self._build_theme_watchlist(fallback, industry_map)
            source_status = {}
            try:
                source_status = self.data_source_manager.get_health_status()
            except Exception:
                source_status = {}
            return {
                "candidates": fallback,
                "theme_watchlist": theme_watchlist,
                "meta": {
                    "source": "fallback_curated",
                    "snapshot_count": 0,
                    "fallback_reason": "全A快照暂不可用，已退回扩展主题兜底池；买入列表仍按真实行情/K线评分，不使用mock资金流。",
                    "data_source_status": source_status,
                    "total_universe_count": 0,
                    "after_prefilter_count": len(fallback),
                    "candidate_count": len(fallback),
                    "theme_watch_count": len(theme_watchlist),
                    "industry_count": 0,
                    "industry_map_count": len(industry_map),
                    "rules": {},
                    "full_refresh_at": None,
                    "incremental_refresh_at": None,
                    "pipeline_counts": {
                        "snapshot": 0,
                        "prefilter": len(fallback),
                        "candidate": len(fallback),
                        "theme_watch": len(theme_watchlist),
                    },
                },
            }

        rules = self._get_universe_rules(risk_level)
        target_candidate_size = max(30, min(int(target_size or rules["max_analyze_count"]), 220))
        strategy = self._normalize_strategy_code(strategy_code)
        filtered: List[Dict[str, Any]] = []
        industries = set()

        for item in entries:
            symbol = str(item.get("symbol") or "")
            if len(symbol) != 6 or not symbol.isdigit() or symbol[0] not in {"0", "3", "6"}:
                continue
            name = str(item.get("name") or symbol)
            if self._is_excluded_name(name):
                continue
            price = float(item.get("price") or 0)
            if price < rules["min_price"]:
                continue
            amount_yi = float(item.get("amount") or 0) / 100000000
            if amount_yi < rules["min_amount_yi"]:
                continue
            turnover_rate = float(item.get("turnover_rate") or 0)
            if turnover_rate <= 0:
                circ_mv = float(item.get("circ_mv") or 0)
                if circ_mv > 0:
                    turnover_rate = self._clamp((float(item.get("amount") or 0) / circ_mv) * 100, 0, 60)
                else:
                    turnover_rate = self._clamp(amount_yi * 0.35, 0.2, 25)
            if turnover_rate < rules["min_turnover_rate"] or turnover_rate > rules["max_turnover_rate"]:
                continue
            pct_change = float(item.get("pct_change") or 0)
            if abs(pct_change) > rules["max_abs_pct_change"]:
                continue

            if turnover_rate <= 2:
                turnover_score = 45 + turnover_rate * 6
            elif turnover_rate <= 10:
                turnover_score = 57 + (turnover_rate - 2) * 3.5
            elif turnover_rate <= 20:
                turnover_score = 85 - (turnover_rate - 10) * 2
            else:
                turnover_score = 65 - (turnover_rate - 20) * 2
            turnover_score = self._clamp(turnover_score, 0, 100)
            liquidity_score = self._clamp(amount_yi * 6, 0, 100)
            intraday_position = 0.5
            day_range = float(item.get("high") or 0) - float(item.get("low") or 0)
            if day_range > 0 and float(item.get("price") or 0) > 0:
                intraday_position = self._clamp((float(item.get("price") or 0) - float(item.get("low") or 0)) / day_range, 0, 1)
            if strategy == "pullback_rebound":
                momentum_score = self._clamp(12 - abs(pct_change + 1.8), 0, 12)
                intraday_score = self._clamp((1 - abs(intraday_position - 0.45)) * 100, 0, 100)
                score = 0.34 * liquidity_score + 0.24 * turnover_score + 0.22 * intraday_score + 0.20 * (momentum_score * 8.2)
            else:
                momentum_score = self._clamp(12 - abs(pct_change - 2.5), 0, 12)
                intraday_score = self._clamp((0.25 + intraday_position) * 80, 0, 100)
                score = 0.38 * liquidity_score + 0.26 * turnover_score + 0.20 * intraday_score + 0.16 * (momentum_score * 8.2)

            industry = (
                str(industry_map.get(symbol) or "").strip()
                or str(item.get("industry") or "").strip()
                or self._infer_board_industry(symbol)
            )
            industries.add(industry)
            row = copy.deepcopy(item)
            row["turnover_rate"] = turnover_rate
            row["industry"] = industry
            row["pre_score"] = round(score, 4)
            filtered.append(row)

        # 行业分散：每个行业最多保留 N 只，避免候选池过度集中
        by_industry: Dict[str, List[Dict[str, Any]]] = {}
        for row in filtered:
            by_industry.setdefault(row.get("industry", "未知行业"), []).append(row)
        diversified: List[Dict[str, Any]] = []
        dynamic_industry_cap = max(rules["industry_cap"], min(10, max(2, target_candidate_size // 28)))
        for industry_rows in by_industry.values():
            industry_rows.sort(key=lambda x: x.get("pre_score", 0), reverse=True)
            diversified.extend(industry_rows[: dynamic_industry_cap])

        diversified.sort(key=lambda x: x.get("pre_score", 0), reverse=True)
        candidates = diversified[: target_candidate_size]
        candidate_symbols = [row["symbol"] for row in candidates]
        self._refresh_intraday_candidates(candidate_symbols)

        with self._universe_lock:
            entry_map = copy.deepcopy(self._universe_state.get("entry_map") or {})
            full_refresh_at = self._universe_state.get("last_full_refresh_at")
            incremental_refresh_at = self._universe_state.get("last_incremental_refresh_at")

        refreshed_candidates = []
        for row in candidates:
            merged = copy.deepcopy(row)
            latest = entry_map.get(row["symbol"])
            if latest:
                merged.update(latest)
            refreshed_candidates.append(merged)

        if not refreshed_candidates:
            fallback = self._curated_fallback_candidates(target_candidate_size)
            theme_watchlist = self._build_theme_watchlist([*filtered, *fallback], industry_map)
            source_status = {}
            try:
                source_status = self.data_source_manager.get_health_status()
            except Exception:
                source_status = {}
            meta = {
                "source": "fallback_curated_after_prefilter",
                "snapshot_count": len(entries),
                "fallback_reason": "全A快照可用但预筛/增量刷新后无有效候选，已退回扩展主题兜底池。",
                "data_source_status": source_status,
                "total_universe_count": len(entries),
                "after_prefilter_count": len(filtered),
                "candidate_count": len(fallback),
                "theme_watch_count": len(theme_watchlist),
                "industry_count": len(industries),
                "industry_map_count": len(industry_map),
                "rules": {**rules, "strategy_target_size": target_candidate_size, "industry_cap_effective": dynamic_industry_cap},
                "full_refresh_at": full_refresh_at,
                "incremental_refresh_at": incremental_refresh_at,
                "pipeline_counts": {
                    "snapshot": len(entries),
                    "prefilter": len(filtered),
                    "candidate": len(fallback),
                    "theme_watch": len(theme_watchlist),
                },
            }
            with self._universe_lock:
                self._universe_state["last_meta"] = meta
            return {"candidates": fallback, "theme_watchlist": theme_watchlist, "meta": meta}

        theme_watchlist = self._build_theme_watchlist(entries, industry_map)
        source_status = {}
        try:
            source_status = self.data_source_manager.get_health_status()
        except Exception:
            source_status = {}
        meta = {
            "source": "a_share_snapshot",
            "snapshot_count": len(entries),
            "fallback_reason": None,
            "data_source_status": source_status,
            "total_universe_count": len(entries),
            "after_prefilter_count": len(filtered),
            "candidate_count": len(refreshed_candidates),
            "theme_watch_count": len(theme_watchlist),
            "industry_count": len(industries),
            "industry_map_count": len(industry_map),
            "rules": {**rules, "strategy_target_size": target_candidate_size, "industry_cap_effective": dynamic_industry_cap},
            "full_refresh_at": full_refresh_at,
            "incremental_refresh_at": incremental_refresh_at,
            "pipeline_counts": {
                "snapshot": len(entries),
                "prefilter": len(filtered),
                "candidate": len(refreshed_candidates),
                "theme_watch": len(theme_watchlist),
            },
        }
        with self._universe_lock:
            self._universe_state["last_meta"] = meta

        return {"candidates": refreshed_candidates, "theme_watchlist": theme_watchlist, "meta": meta}

    def _get_latest_action_map(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        return self.store.get_latest_pick_actions(user_id=user_id)

    def _attach_user_actions(self, picks: List[Dict[str, Any]], user_id: str) -> None:
        action_map = self._get_latest_action_map(user_id)
        for pick in picks:
            action = action_map.get(pick.get("pick_id"))
            if action:
                pick["user_action"] = {
                    "action_type": action.get("action_type"),
                    "action_price": action.get("action_price"),
                    "action_qty": action.get("action_qty"),
                    "note": action.get("note"),
                    "created_at": action.get("created_at"),
                }
            else:
                pick["user_action"] = None

    def _latest_today_snapshot(self) -> Optional[Dict[str, Any]]:
        trade_date = self._recommendation_trade_date()
        snapshot = self._daily_snapshots.get(trade_date)
        if snapshot:
            return copy.deepcopy(snapshot)
        latest_cache = None
        latest_ts = -1.0
        for item in self._today_picks_cache.values():
            ts = float(item.get("ts") or 0)
            data = item.get("data") or {}
            if data.get("trade_date") == trade_date and ts > latest_ts:
                latest_cache = data
                latest_ts = ts
        return copy.deepcopy(latest_cache) if latest_cache else None

    def get_cached_today_picks(self, max_count: int = 30, user_id: str = "default") -> Optional[Dict[str, Any]]:
        data = self._latest_today_snapshot()
        if not data:
            try:
                restored = self.store.get_latest_pick_snapshots_result(
                    user_id=user_id,
                    trade_date=self._recommendation_trade_date(),
                    limit=max_count,
                )
                if not restored:
                    restored = self.store.get_latest_pick_snapshots_result(user_id=user_id, limit=max_count)
            except Exception:
                restored = None
            if not restored:
                return None
            market_snapshot = None
            if self.market_snapshot_service:
                try:
                    market_snapshot = self.market_snapshot_service.get_latest_valid_snapshot(restored.get("trade_date"))
                except Exception:
                    market_snapshot = None
            picks = restored.get("picks") or []
            data = {
                "status": "cached_from_store",
                "trade_date": restored.get("trade_date"),
                "updated_at": restored.get("updated_at"),
                "is_refreshing": bool(self._refresh_state.get("is_refreshing")),
                "market_state": self.get_market_state_today(),
                "risk_profile": self.get_risk_profile(user_id),
                "universe_meta": {
                    "source": "pick_snapshots",
                    "snapshot_count": int((market_snapshot or {}).get("snapshot_count") or 0),
                    "fallback_reason": None if market_snapshot else "已从推荐快照恢复，但未找到可用全A市场快照。",
                    "pipeline_counts": {
                        "snapshot": int((market_snapshot or {}).get("snapshot_count") or 0),
                        "restored_picks": len(picks),
                        "final_output": len(picks),
                    },
                },
                "strategy_health": None,
                "trade_plan": self._attach_trade_plan(
                    picks,
                    strategy_health={},
                    market_state=self.get_market_state_today(),
                    risk_profile=self.get_risk_profile(user_id),
                ),
                "theme_watchlist": [],
                "excluded_examples": [],
                "picks": picks,
                "no_trade": len(picks) == 0,
                "no_trade_reason": "当前没有可展示的缓存推荐。" if not picks else None,
            }
        result = copy.deepcopy(data)
        result["picks"] = (result.get("picks") or [])[: max(1, min(int(max_count or 30), 60))]
        self._attach_user_actions(result["picks"], user_id)
        meta = result.get("universe_meta") or {}
        result["status"] = result.get("status") or "cached"
        if result["status"] == "fresh":
            result["status"] = "cached"
        result["updated_at"] = result.get("updated_at") or meta.get("incremental_refresh_at") or meta.get("full_refresh_at")
        result["is_refreshing"] = bool(self._refresh_state.get("is_refreshing"))
        result["data_quality"] = self._build_data_quality(result)
        result["data_diagnostics"] = self._build_data_diagnostics(result)
        return result

    def get_smart_screen_summary(self, user_id: str = "default", risk_level: str = "medium") -> Dict[str, Any]:
        cached = self.get_cached_today_picks(max_count=5, user_id=user_id)
        refresh_state = self.get_refresh_state()
        if cached:
            picks = cached.get("picks") or []
            trade_plan = cached.get("trade_plan") or {}
            market_state = cached.get("market_state") or {}
            strategy_health = cached.get("strategy_health") or {}
            return {
                "status": "cached",
                "trade_date": cached.get("trade_date"),
                "updated_at": cached.get("updated_at"),
                "is_refreshing": bool(refresh_state.get("is_refreshing")),
                "market_state": market_state,
                "trade_plan": trade_plan,
                "strategy_health": strategy_health,
                "top_picks": picks[:5],
                "pick_count": len(cached.get("picks") or []),
                "core_count": len([p for p in picks if (p.get("decision") or {}).get("grade") in {"A", "B"}]),
                "data_quality": cached.get("data_quality"),
                "data_diagnostics": cached.get("data_diagnostics"),
                "message": "已展示最近一次缓存结果，刷新会在后台完成。",
            }

        state = self.get_market_state_today()
        return {
            "status": "empty",
            "trade_date": datetime.now().strftime("%Y-%m-%d"),
            "updated_at": None,
            "is_refreshing": bool(refresh_state.get("is_refreshing")),
            "market_state": state,
            "trade_plan": {
                "primary_action": "watch",
                "headline": "等待生成今日交易计划",
                "summary": "页面先展示市场环境，完整选股会在后台刷新后更新。",
                "core_count": 0,
                "trial_count": 0,
                "suggested_total_exposure_pct": 0,
            },
            "strategy_health": None,
            "top_picks": [],
            "pick_count": 0,
            "core_count": 0,
            "data_quality": {
                "snapshot_status": "unknown",
                "money_flow_coverage": "unknown",
                "diagnostic_mode": "hidden",
            },
            "data_diagnostics": {"refresh_state": refresh_state},
            "message": "暂无缓存推荐，已可触发后台刷新。",
        }

    def _build_data_quality(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if self.data_quality_service:
            return self.data_quality_service.build_recommendation_quality(
                result.get("picks") or [],
                result.get("universe_meta") or {},
            )
        picks = result.get("picks") or []
        real_count = len([p for p in picks if p.get("money_flow_quality") == "real"])
        proxy_count = len([p for p in picks if p.get("money_flow_quality") == "proxy"])
        unavailable_count = len([p for p in picks if p.get("money_flow_quality") == "unavailable"])
        meta = result.get("universe_meta") or {}
        snapshot_count = int(self._safe_float(meta.get("snapshot_count"), 0))
        source = str(meta.get("source") or "")
        snapshot_status = "fallback" if source.startswith("fallback_") else "ok"
        if snapshot_count < 500:
            snapshot_status = "insufficient_data"
        return {
            "snapshot_status": snapshot_status,
            "snapshot_count": snapshot_count,
            "fallback_reason": meta.get("fallback_reason"),
            "is_reliable": snapshot_status == "ok",
            "money_flow_quality": {
                "real": real_count,
                "proxy": proxy_count,
                "unavailable": unavailable_count,
                "total": len(picks),
            },
            "money_flow_coverage": round(real_count / len(picks), 4) if picks else 0,
            "diagnostic_mode": "hidden",
        }

    def _build_data_diagnostics(self, result: Dict[str, Any]) -> Dict[str, Any]:
        meta = result.get("universe_meta") or {}
        return {
            "universe_meta": meta,
            "pipeline_counts": meta.get("pipeline_counts") or {},
            "fallback_reason": meta.get("fallback_reason"),
            "refresh_state": self.get_refresh_state(),
        }

    def _build_degraded_today_result(
        self,
        trade_date: str,
        market_state: Dict[str, Any],
        risk_profile: Dict[str, Any],
        universe_meta: Dict[str, Any],
        theme_watchlist: List[Dict[str, Any]],
        user_id: str,
    ) -> Dict[str, Any]:
        snapshot_count = int(self._safe_float((universe_meta or {}).get("snapshot_count"), 0))
        fallback_reason = (universe_meta or {}).get("fallback_reason") or (
            f"全A快照样本量不足（{snapshot_count} < 500），不生成正常核心候选。"
        )
        meta = copy.deepcopy(universe_meta or {})
        meta["fallback_reason"] = fallback_reason
        meta["is_reliable"] = False
        pipeline_counts = meta.setdefault("pipeline_counts", {})
        if isinstance(pipeline_counts, dict):
            pipeline_counts["final_output"] = 0
            pipeline_counts["strict_buy"] = 0
        trade_plan = self._attach_trade_plan(
            [],
            strategy_health={},
            market_state=market_state,
            risk_profile=risk_profile,
        )
        trade_plan["headline"] = "数据降级，今日不生成买入清单"
        trade_plan["summary"] = fallback_reason
        result = {
            "status": "degraded",
            "trade_date": trade_date,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_refreshing": bool(self._refresh_state.get("is_refreshing")),
            "market_state": market_state,
            "risk_profile": risk_profile,
            "universe_meta": meta,
            "strategy_health": {
                "status": "data_degraded",
                "summary": fallback_reason,
                "live_ready": False,
            },
            "trade_plan": trade_plan,
            "theme_watchlist": theme_watchlist or [],
            "excluded_examples": [],
            "picks": [],
            "no_trade": True,
            "no_trade_reason": fallback_reason,
        }
        result["data_quality"] = self._build_data_quality(result)
        result["data_diagnostics"] = self._build_data_diagnostics(result)
        self._daily_snapshots[trade_date] = copy.deepcopy(result)
        return result

    def _find_pick_by_id(self, pick_id: str) -> Optional[Dict[str, Any]]:
        # 当日快照优先
        for snapshot in self._daily_snapshots.values():
            for pick in snapshot.get("picks", []):
                if pick.get("pick_id") == pick_id:
                    return pick

        for picks in self._pick_history.values():
            for pick in picks:
                if pick.get("pick_id") == pick_id:
                    return pick

        symbol = self._extract_symbol_from_pick_id(pick_id)
        if symbol:
            quote = self.data_source_manager.get_realtime_quote(symbol)
            if quote:
                return {
                    "pick_id": pick_id,
                    "symbol": symbol,
                    "name": quote.get("name", symbol),
                    "entry_range": [quote.get("price"), quote.get("price")],
                    "score_breakdown": {},
                }
        return None

    @staticmethod
    def _normalize_strategy_code(strategy_code: Optional[str]) -> str:
        code = str(strategy_code or "trend_breakout").strip().lower()
        if code not in {"trend_breakout", "pullback_rebound"}:
            return "trend_breakout"
        return code

    def _sanitize_strategy_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        cfg = copy.deepcopy(config or {})
        risk_level = str(cfg.get("risk_level") or "medium").strip().lower()
        if risk_level not in {"low", "medium", "high"}:
            risk_level = "medium"
        return {
            "risk_level": risk_level,
            "holding_days": max(3, min(90, int(self._safe_float(cfg.get("holding_days"), 15)))),
            "stop_profit_pct": round(self._clamp(self._safe_float(cfg.get("stop_profit_pct"), 15), 5, 40), 2),
            "stop_loss_pct": round(self._clamp(self._safe_float(cfg.get("stop_loss_pct"), 8), 2, 25), 2),
            "score_threshold": round(self._clamp(self._safe_float(cfg.get("score_threshold"), 70), 50, 95), 2),
            "commission": round(self._clamp(self._safe_float(cfg.get("commission"), 0.0003), 0, 0.01), 6),
            "slippage": round(self._clamp(self._safe_float(cfg.get("slippage"), 0.001), 0, 0.01), 6),
            "max_positions": max(1, min(20, int(self._safe_float(cfg.get("max_positions"), 5)))),
            "max_position_pct": round(self._clamp(self._safe_float(cfg.get("max_position_pct"), 10), 2, 30), 2),
            "universe_size": max(20, min(300, int(self._safe_float(cfg.get("universe_size"), 90)))),
        }

    def _get_strategy_presets(self, strategy_code: str) -> List[Dict[str, Any]]:
        code = self._normalize_strategy_code(strategy_code)
        presets = self.STRATEGY_PRESET_LIBRARY.get(code) or self.STRATEGY_PRESET_LIBRARY["trend_breakout"]
        normalized = []
        for idx, item in enumerate(presets):
            normalized.append(
                {
                    "profile_key": item.get("profile_key") or f"{code}_{idx}",
                    "label": item.get("label") or f"{code}-{idx}",
                    "description": item.get("description") or "",
                    "is_recommended": idx == 0,
                    "config": self._sanitize_strategy_config(item.get("config") or {}),
                }
            )
        return normalized

    def _find_preset(self, strategy_code: str, profile_key: Optional[str]) -> Optional[Dict[str, Any]]:
        presets = self._get_strategy_presets(strategy_code)
        if not presets:
            return None
        if not profile_key:
            return presets[0]
        key = str(profile_key).strip()
        for item in presets:
            if item.get("profile_key") == key:
                return item
        return presets[0]

    def get_strategy_config_options(self, user_id: str = "default", strategy_code: str = "trend_breakout") -> Dict[str, Any]:
        code = self._normalize_strategy_code(strategy_code)
        presets = self._get_strategy_presets(code)
        user_row = self.store.get_strategy_profile(user_id=user_id, strategy_code=code)
        active_row = self.store.get_active_strategy_profile(user_id=user_id)

        recommended = presets[0] if presets else None
        current_profile_key = (user_row or {}).get("profile_key") or (recommended or {}).get("profile_key")
        current_config = self._sanitize_strategy_config(
            (user_row or {}).get("config") or ((recommended or {}).get("config") or {})
        )

        return {
            "strategy_code": code,
            "presets": presets,
            "recommended_profile_key": (recommended or {}).get("profile_key"),
            "current_profile_key": current_profile_key,
            "current_config": current_config,
            "active_strategy_code": self._normalize_strategy_code((active_row or {}).get("strategy_code")),
            "active_profile_key": (active_row or {}).get("profile_key"),
            "active_config": self._sanitize_strategy_config((active_row or {}).get("config") or {}),
            "updated_at": (user_row or {}).get("updated_at"),
        }

    def get_active_strategy_config(self, user_id: str = "default") -> Dict[str, Any]:
        active_row = self.store.get_active_strategy_profile(user_id=user_id)
        if active_row:
            return {
                "strategy_code": self._normalize_strategy_code(active_row.get("strategy_code")),
                "profile_key": active_row.get("profile_key"),
                "config": self._sanitize_strategy_config(active_row.get("config") or {}),
                "updated_at": active_row.get("updated_at"),
            }

        presets = self._get_strategy_presets("trend_breakout")
        default = presets[0] if presets else {"profile_key": "default", "config": {}}
        return {
            "strategy_code": "trend_breakout",
            "profile_key": default.get("profile_key"),
            "config": self._sanitize_strategy_config(default.get("config") or {}),
            "updated_at": None,
        }

    def apply_strategy_config(
        self,
        user_id: str,
        strategy_code: str,
        profile_key: Optional[str] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
        set_active: bool = True,
    ) -> Dict[str, Any]:
        code = self._normalize_strategy_code(strategy_code)
        preset = self._find_preset(code, profile_key) or {}
        base_config = preset.get("config") or {}
        merged = copy.deepcopy(base_config)
        if config_overrides:
            merged.update(config_overrides)
        merged = self._sanitize_strategy_config(merged)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        saved = self.store.upsert_strategy_profile(
            user_id=user_id,
            strategy_code=code,
            profile_key=(preset.get("profile_key") if preset else profile_key),
            config=merged,
            updated_at=now_str,
            is_active=bool(set_active),
        )

        # 同步风险偏好，确保智能选股页默认风险等级与策略模板一致
        current_risk = self.get_risk_profile(user_id=user_id)
        current_risk.update(
            {
                "risk_level": merged.get("risk_level", current_risk.get("risk_level", "medium")),
                "max_position_pct": merged.get("max_position_pct", current_risk.get("max_position_pct", 10)),
            }
        )
        self.set_risk_profile(user_id=user_id, profile=current_risk)
        self._invalidate_user_cache(user_id)

        return {
            "user_id": user_id,
            "strategy_code": code,
            "profile_key": saved.get("profile_key"),
            "config": merged,
            "is_active": bool(set_active),
            "updated_at": now_str,
        }

    def set_risk_profile(self, user_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        current = self.DEFAULT_RISK_PROFILE.copy()
        current.update(profile)
        saved = self.store.upsert_risk_profile(
            user_id=user_id,
            profile=current,
            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._invalidate_user_cache(user_id)
        return {
            "risk_level": saved["risk_level"],
            "horizon_days_min": saved["horizon_days_min"],
            "horizon_days_max": saved["horizon_days_max"],
            "max_position_pct": saved["max_position_pct"],
            "max_industry_pct": saved["max_industry_pct"],
        }

    def get_risk_profile(self, user_id: str = "default") -> Dict[str, Any]:
        loaded = self.store.get_risk_profile(user_id)
        if loaded:
            return {
                "risk_level": loaded["risk_level"],
                "horizon_days_min": loaded["horizon_days_min"],
                "horizon_days_max": loaded["horizon_days_max"],
                "max_position_pct": loaded["max_position_pct"],
                "max_industry_pct": loaded["max_industry_pct"],
            }
        if user_id != "default":
            return self.get_risk_profile("default")
        return self.DEFAULT_RISK_PROFILE.copy()

    def get_market_state_today(self) -> Dict[str, Any]:
        quotes = []
        for symbol in self.MARKET_SAMPLE_POOL:
            quote = self.data_source_manager.get_realtime_quote(symbol)
            if quote:
                quotes.append(quote)

        news_context = {
            "policy_score": 50.0,
            "policy_net": 0.0,
            "risk_bias": "neutral",
            "latest_events": [],
            "reasons": [],
            "updated_at": None,
        }
        if self.news_service:
            try:
                news_context = self.news_service.get_market_news_summary()
            except Exception:
                news_context = news_context

        if not quotes:
            return {
                "state_tag": "neutral",
                "state_score": 50.0,
                "state_confidence": "low",
                "suggested_exposure_min_pct": 20,
                "suggested_exposure_max_pct": 40,
                "summary": "样本不足，默认中性",
                "reasons": ["市场样本数据不足，建议谨慎分散建仓"],
                "drivers": {
                    "trend_score": 50.0,
                    "breadth_score": 50.0,
                    "money_flow_score": 50.0,
                    "risk_score": 50.0,
                    "news_score": float(news_context.get("policy_score", 50.0)),
                },
                "news_context": news_context,
            }

        avg_change = sum(float(q.get("pct_change", 0) or 0) for q in quotes) / len(quotes)
        up_ratio = sum(1 for q in quotes if float(q.get("pct_change", 0) or 0) > 0) / len(quotes)

        trend_score = self._clamp(50 + avg_change * 4, 0, 100)
        breadth_score = self._clamp(up_ratio * 100, 0, 100)
        money_flow_score = self._clamp(45 + avg_change * 3, 0, 100)
        risk_score = self._clamp(65 - abs(avg_change) * 4, 0, 100)
        news_score = self._clamp(self._safe_float(news_context.get("policy_score"), 50.0), 0, 100)

        state_score = self._clamp(
            0.28 * trend_score
            + 0.22 * breadth_score
            + 0.16 * money_flow_score
            + 0.16 * risk_score
            + 0.18 * news_score,
            0,
            100,
        )

        if state_score >= 65:
            state_tag = "offensive"
            exposure = (50, 75)
            summary = "市场偏进攻，可适度提高仓位"
        elif state_score >= 45:
            state_tag = "neutral"
            exposure = (30, 50)
            summary = "市场中性震荡，精选个股为主"
        else:
            state_tag = "defensive"
            exposure = (10, 30)
            summary = "市场偏防守，控制仓位与回撤"

        confidence = "high" if len(quotes) >= 5 else "medium"

        reasons = [
            f"样本平均涨跌幅 {avg_change:.2f}%",
            f"样本上涨占比 {up_ratio * 100:.1f}%",
            f"政策/资讯温度 {news_score:.1f}",
            "建议先看风险，再做进攻配置",
        ]
        reasons.extend((news_context.get("reasons") or [])[:2])

        return {
            "state_tag": state_tag,
            "state_score": round(state_score, 2),
            "state_confidence": confidence,
            "suggested_exposure_min_pct": exposure[0],
            "suggested_exposure_max_pct": exposure[1],
            "summary": summary,
            "reasons": reasons,
            "drivers": {
                "trend_score": round(trend_score, 2),
                "breadth_score": round(breadth_score, 2),
                "money_flow_score": round(money_flow_score, 2),
                "risk_score": round(risk_score, 2),
                "news_score": round(news_score, 2),
            },
            "news_context": news_context,
        }

    def _build_pick(
        self,
        symbol: str,
        risk_profile: Dict[str, Any],
        market_state: Dict[str, Any],
        quote_override: Optional[Dict[str, Any]] = None,
        strategy_code: str = "trend_breakout",
    ) -> Optional[Dict[str, Any]]:
        if not self.feature_service:
            return None
        feature_payload = self.feature_service.build_pick_features(
            symbol=symbol,
            quote_override=quote_override,
            strategy_code=strategy_code,
        )
        if not feature_payload:
            return None

        quote = feature_payload.get("quote") or {}
        history_df = feature_payload.get("history_df")
        analyzed_df = feature_payload.get("analyzed_df")
        indicators = feature_payload.get("indicators") or {}
        signal = feature_payload.get("signal") or {}
        strategy = feature_payload.get("strategy") or self._normalize_strategy_code(strategy_code)
        current_price = self._safe_float(feature_payload.get("current_price"), 0)
        if current_price <= 0:
            return None

        signal_score = float(signal.get("score", 0) or 0)
        up_prob = self._clamp(0.52 + signal_score / 250.0, 0.05, 0.95)
        dd_prob = self._clamp(0.34 - signal_score / 400.0, 0.05, 0.90)

        money_flow_source = str(feature_payload.get("money_flow_source") or "unavailable")
        money_flow_quality = str(feature_payload.get("money_flow_quality") or "unavailable")
        money_flow_confidence = self._safe_float(feature_payload.get("money_flow_confidence"), 0.0)
        main_net_inflow_yi = self._safe_float(feature_payload.get("main_net_inflow_yi"), 0.0)
        industry_name = str(feature_payload.get("industry_name") or self._infer_board_industry(symbol))
        news_factor = feature_payload.get("news_factor") or {}
        turnover_rate = self._safe_float(feature_payload.get("turnover_rate"), 0.0)

        flow_multiplier = 8 if money_flow_quality == "real" else (3 if money_flow_quality == "proxy" else 0)
        flow_score = self._clamp(50 + main_net_inflow_yi * flow_multiplier, 0, 100)
        if turnover_rate <= 2:
            turnover_score = 45 + turnover_rate * 6
        elif turnover_rate <= 8:
            turnover_score = 60 + (turnover_rate - 2) * 4
        elif turnover_rate <= 15:
            turnover_score = 84 - (turnover_rate - 8) * 2
        else:
            turnover_score = 70 - (turnover_rate - 15) * 3
        turnover_score = self._clamp(turnover_score, 0, 100)

        # 资金流与换手率会直接影响概率
        flow_prob_weight = 0.012 if money_flow_quality == "real" else (0.004 if money_flow_quality == "proxy" else 0.0)
        up_prob = self._clamp(up_prob + self._clamp(main_net_inflow_yi * flow_prob_weight, -0.05, 0.05), 0.05, 0.95)
        if turnover_rate > 15:
            dd_prob = self._clamp(dd_prob + 0.05, 0.05, 0.90)
        elif turnover_rate < 1:
            dd_prob = self._clamp(dd_prob + 0.02, 0.05, 0.90)
        elif 3 <= turnover_rate <= 10:
            dd_prob = self._clamp(dd_prob - 0.01, 0.05, 0.90)

        news_net_score = self._safe_float(news_factor.get("net_score"), 0.0)
        if news_net_score != 0:
            up_prob = self._clamp(up_prob + self._clamp(news_net_score / 500.0, -0.06, 0.06), 0.05, 0.95)
            dd_prob = self._clamp(dd_prob - self._clamp(news_net_score / 700.0, -0.05, 0.05), 0.05, 0.90)

        rsi = self._safe_float(feature_payload.get("rsi"), 50)
        macd_hist = self._safe_float(feature_payload.get("macd_hist"), 0)
        close_price = self._safe_float(feature_payload.get("close_price"), current_price)
        ma5 = self._safe_float(feature_payload.get("ma5"), close_price)
        ma10 = self._safe_float(feature_payload.get("ma10"), close_price)
        ma20 = self._safe_float(feature_payload.get("ma20"), close_price)
        ma60 = self._safe_float(feature_payload.get("ma60"), close_price)
        volume_ratio = self._safe_float(feature_payload.get("volume_ratio"), 1.0)
        near_lower_band = bool(feature_payload.get("near_lower_band"))
        reclaim_middle_band = bool(feature_payload.get("reclaim_middle_band"))
        prev_pct_change = self._safe_float(feature_payload.get("prev_pct_change"), 0.0)
        curr_pct_change = self._safe_float(feature_payload.get("curr_pct_change"), 0.0)
        return_5d_pct = self._safe_float(feature_payload.get("return_5d_pct"), 0.0)
        return_20d_pct = self._safe_float(feature_payload.get("return_20d_pct"), 0.0)
        from_20d_high_pct = self._safe_float(feature_payload.get("from_20d_high_pct"), 0.0)
        ma_alignment = int(self._safe_float(feature_payload.get("ma_alignment"), 0.0))
        stretch_from_ma20_pct = self._safe_float(feature_payload.get("stretch_from_ma20_pct"), 0.0)
        overheated = bool(feature_payload.get("overheated"))
        broken_downtrend = bool(feature_payload.get("broken_downtrend"))
        rebound_day = bool(feature_payload.get("rebound_day"))
        oversold = bool(feature_payload.get("oversold"))
        macd_repair = bool(feature_payload.get("macd_repair"))
        pullback_score = self._safe_float(feature_payload.get("pullback_score"), 0.0)
        if strategy == "pullback_rebound":
            up_prob = self._clamp(up_prob - 0.08 + pullback_score / 180.0 + self._clamp(main_net_inflow_yi * 0.01, -0.04, 0.04), 0.05, 0.95)
            dd_prob = self._clamp(dd_prob + 0.05 - pullback_score / 220.0, 0.05, 0.90)
            flow_score = self._clamp(flow_score * 0.7 + pullback_score * 0.3, 0, 100)
            turnover_score = self._clamp(turnover_score * 0.85 + (50 if 1.0 <= turnover_rate <= 10 else 36) * 0.15, 0, 100)
            signal_score = signal_score * 0.72 + pullback_score * 0.75

        if strategy == "trend_breakout":
            breakout_quality = (
                (18 if ma_alignment >= 3 else 0)
                + (14 if 1.5 <= return_20d_pct <= 20 else 0)
                + (10 if return_5d_pct >= 0 else 0)
                + (12 if -2.0 <= from_20d_high_pct <= 4.0 else 0)
                + (10 if 0.9 <= volume_ratio <= 2.8 else 0)
                + (8 if main_net_inflow_yi >= 0 else 0)
            )
            extension_penalty = (
                (14 if curr_pct_change >= 6.5 else 0)
                + (12 if return_20d_pct >= 28 else 0)
                + (8 if stretch_from_ma20_pct >= 10 else 0)
                + (8 if turnover_rate >= 18 else 0)
                + (6 if main_net_inflow_yi < -0.3 else 0)
            )
            up_prob = self._clamp(up_prob + breakout_quality / 260.0 - extension_penalty / 520.0, 0.05, 0.95)
            dd_prob = self._clamp(dd_prob - breakout_quality / 420.0 + extension_penalty / 460.0, 0.05, 0.90)
            signal_score = signal_score * 0.78 + breakout_quality * 0.82 - extension_penalty * 0.55
            quality_score = self._clamp(56 + signal_score * 0.16 + breakout_quality * 0.40 - extension_penalty * 0.32, 0, 100)
        else:
            rebound_quality = (
                pullback_score
                + (12 if -14 <= return_20d_pct <= 6 else 0)
                + (10 if -3 <= from_20d_high_pct <= 0 else 0)
                + (8 if 0.8 <= volume_ratio <= 2.2 else 0)
                + (8 if main_net_inflow_yi >= -0.2 else 0)
            )
            rebound_penalty = (
                (10 if curr_pct_change >= 7 else 0)
                + (8 if turnover_rate >= 18 else 0)
                + (6 if main_net_inflow_yi < -0.5 else 0)
            )
            up_prob = self._clamp(up_prob + rebound_quality / 340.0 - rebound_penalty / 600.0, 0.05, 0.95)
            dd_prob = self._clamp(dd_prob - rebound_quality / 520.0 + rebound_penalty / 500.0, 0.05, 0.90)
            quality_score = self._clamp(58 + signal_score * 0.12 + rebound_quality * 0.28 - rebound_penalty * 0.22, 0, 100)

        state_tag = market_state.get("state_tag", "neutral")
        if state_tag == "defensive":
            up_prob = self._clamp(up_prob - 0.03, 0.05, 0.95)
            dd_prob = self._clamp(dd_prob + 0.05, 0.05, 0.90)
        elif state_tag == "offensive":
            up_prob = self._clamp(up_prob + 0.02, 0.05, 0.95)
            dd_prob = self._clamp(dd_prob - 0.03, 0.05, 0.90)

        quality_notes: List[str] = []
        disqualify_buy = False
        disqualify_watch = False
        structure_penalty = 0.0

        if money_flow_quality != "real":
            quality_notes.append("资金流为代理或不可用：资金面只作弱参考，不支持高置信买入")
            structure_penalty += 4.0 if money_flow_quality == "proxy" else 8.0

        if broken_downtrend:
            quality_notes.append("趋势结构破位：20日跌幅/高位回撤过大或价格跌破中期均线")
            disqualify_buy = True
            disqualify_watch = True
            structure_penalty += 24.0

        if strategy == "trend_breakout":
            trend_structure_ok = (
                ma_alignment >= 3
                and -3.0 <= return_20d_pct <= 18.0
                and from_20d_high_pct >= -10.0
                and stretch_from_ma20_pct <= 7.5
                and rsi <= 72.0
            )
            trend_volume_ok = 0.75 <= volume_ratio <= 3.2
            trend_flow_ok = main_net_inflow_yi >= -0.35
            if not trend_structure_ok:
                quality_notes.append("趋势突破质量不足：均线、20日涨幅、RSI 或乖离率不满足买入闸门")
                disqualify_buy = True
                structure_penalty += 10.0
            if not trend_volume_ok:
                quality_notes.append("量能结构不理想：放量不足或短线放量过猛")
                disqualify_buy = True
                structure_penalty += 5.0
            if not trend_flow_ok:
                quality_notes.append("资金闸门未通过：近3日主力资金流出偏多")
                disqualify_buy = True
                structure_penalty += 6.0
            if overheated:
                quality_notes.append("短线过热：RSI、均线乖离或20日涨幅偏高，禁止追高买入")
                disqualify_buy = True
                structure_penalty += 12.0
        else:
            pullback_structure_ok = (
                -18.0 <= return_20d_pct <= 8.0
                and from_20d_high_pct >= -20.0
                and rsi <= 48.0
                and (rebound_day or reclaim_middle_band or macd_repair)
            )
            pullback_flow_ok = main_net_inflow_yi >= -0.6
            if not pullback_structure_ok:
                quality_notes.append("回调修复质量不足：尚未出现止跌、修复或均线收复信号")
                disqualify_buy = True
                structure_penalty += 10.0
            if not pullback_flow_ok:
                quality_notes.append("资金闸门未通过：回调阶段资金仍持续流出")
                disqualify_buy = True
                structure_penalty += 6.0
            if rsi < 22:
                quality_notes.append("极端弱势：RSI过低，优先等待止跌确认")
                disqualify_buy = True
                disqualify_watch = True
                structure_penalty += 12.0

        if news_net_score <= -18:
            quality_notes.append("资讯闸门偏负面：政策/公告风险未消化")
            disqualify_buy = True
            structure_penalty += 6.0

        if structure_penalty:
            up_prob = self._clamp(up_prob - structure_penalty / 380.0, 0.05, 0.86)
            dd_prob = self._clamp(dd_prob + structure_penalty / 320.0, 0.08, 0.90)
            quality_score = self._clamp(quality_score - structure_penalty, 0, 100)
            signal_score -= structure_penalty * 0.65
            if money_flow_quality == "unavailable":
                disqualify_buy = True
        # 当前概率仍是量价/资讯代理，不允许展示成“几乎确定”的胜率。
        up_prob = self._clamp(up_prob, 0.05, 0.80)
        dd_prob = self._clamp(dd_prob, 0.10, 0.90)

        risk_level = risk_profile.get("risk_level", "medium")
        if risk_level == "low":
            stop_loss_ratio = 0.06
            take_profit_ratio = 0.10
            base_position = min(8.0, float(risk_profile.get("max_position_pct", 10)))
            if strategy == "pullback_rebound":
                buy_cond = up_prob >= 0.56 and dd_prob <= 0.30 and (oversold or near_lower_band) and macd_repair
                watch_cond = up_prob >= 0.50 and dd_prob <= 0.36 and (oversold or rebound_day)
            else:
                buy_cond = up_prob >= 0.62 and dd_prob <= 0.26 and flow_score >= 45
                watch_cond = up_prob >= 0.54 and dd_prob <= 0.34
        elif risk_level == "high":
            stop_loss_ratio = 0.10
            take_profit_ratio = 0.18
            base_position = min(12.0, float(risk_profile.get("max_position_pct", 10)))
            if strategy == "pullback_rebound":
                buy_cond = up_prob >= 0.52 and dd_prob <= 0.42 and (oversold or near_lower_band or rebound_day)
                watch_cond = up_prob >= 0.47 and dd_prob <= 0.52 and (oversold or rebound_day)
            else:
                buy_cond = up_prob >= 0.56 and dd_prob <= 0.38
                watch_cond = up_prob >= 0.47 and dd_prob <= 0.50
        else:
            stop_loss_ratio = 0.08
            take_profit_ratio = 0.14
            base_position = min(10.0, float(risk_profile.get("max_position_pct", 10)))
            if strategy == "pullback_rebound":
                buy_cond = up_prob >= 0.54 and dd_prob <= 0.35 and (oversold or near_lower_band) and (rebound_day or macd_repair)
                watch_cond = up_prob >= 0.48 and dd_prob <= 0.42 and (oversold or rebound_day)
            else:
                buy_cond = up_prob >= 0.60 and dd_prob <= 0.30
                watch_cond = up_prob >= 0.50 and dd_prob <= 0.40

        expected_edge_pct = up_prob * (take_profit_ratio * 100.0) - dd_prob * (stop_loss_ratio * 100.0)
        profit_factor_proxy = ((up_prob * take_profit_ratio) + 0.005) / ((dd_prob * stop_loss_ratio) + 0.005)
        execution_penalty = 0.0
        if main_net_inflow_yi < 0:
            execution_penalty += min(10.0, abs(main_net_inflow_yi) * 5.0)
        if turnover_rate < 0.8:
            execution_penalty += 6.0
        elif turnover_rate > 18:
            execution_penalty += min(10.0, (turnover_rate - 18) * 1.2)
        if strategy == "trend_breakout" and curr_pct_change > 6:
            execution_penalty += 6.0
        if strategy == "pullback_rebound" and curr_pct_change > 8:
            execution_penalty += 4.0

        edge_score = self._clamp(48 + expected_edge_pct * 6.5 + (profit_factor_proxy - 1) * 15 - execution_penalty, 0, 100)
        score_reliability_penalty = 0.0
        if money_flow_quality == "proxy":
            score_reliability_penalty += 5.0
            flow_score = self._clamp(50 + (flow_score - 50) * 0.55, 0, 100)
        elif money_flow_quality == "unavailable":
            score_reliability_penalty += 9.0
            flow_score = 50.0
        flow_score = self._clamp(flow_score - execution_penalty * 0.35, 0, 100)
        turnover_score = self._clamp(turnover_score - execution_penalty * 0.25, 0, 100)
        quality_score = self._clamp(quality_score * 0.68 + edge_score * 0.32, 0, 100)

        if risk_level == "low":
            edge_gate = 2.6
            pf_gate = 1.55
            watch_edge_gate = 1.2
        elif risk_level == "high":
            edge_gate = 1.0
            pf_gate = 1.22
            watch_edge_gate = 0.2
        else:
            edge_gate = 1.8
            pf_gate = 1.38
            watch_edge_gate = 0.6

        buy_cond = bool(buy_cond and expected_edge_pct >= edge_gate and profit_factor_proxy >= pf_gate)
        watch_cond = bool(watch_cond and expected_edge_pct >= watch_edge_gate)
        if disqualify_buy:
            buy_cond = False
        if disqualify_watch:
            watch_cond = False

        if buy_cond:
            action = "buy"
        elif watch_cond:
            action = "watch"
        else:
            action = "pass"

        if action == "buy" and expected_edge_pct < watch_edge_gate:
            action = "watch"
        if action == "watch" and expected_edge_pct < 0:
            action = "pass"

        if action == "pass":
            return None

        confidence = "high" if (up_prob >= 0.68 and dd_prob <= 0.22) else ("medium" if up_prob >= 0.55 else "low")

        entry_min = round(current_price * 0.992, 2)
        entry_max = round(current_price * 1.008, 2)
        take_profit = round(current_price * (1 + take_profit_ratio), 2)
        stop_loss = round(current_price * (1 - stop_loss_ratio), 2)

        reasons = [text for text in signal.get("signals", [])[:2]]
        if main_net_inflow_yi > 0:
            reasons.append(f"近3日主力净流入 {main_net_inflow_yi:.2f} 亿")
        elif main_net_inflow_yi < 0:
            reasons.append(f"近3日主力净流出 {abs(main_net_inflow_yi):.2f} 亿，需控制节奏")

        if turnover_rate >= 3:
            reasons.append(f"换手率 {turnover_rate:.2f}%，流动性较活跃")
        else:
            reasons.append(f"换手率 {turnover_rate:.2f}%，交易活跃度一般")

        if news_net_score >= 8:
            reasons.append(f"资讯因子偏正面，资讯贡献分 {self._safe_float(news_factor.get('total_score'), 50):.1f}")
        elif news_net_score <= -8:
            reasons.append(f"资讯因子偏负面，需提防事件扰动（资讯贡献分 {self._safe_float(news_factor.get('total_score'), 50):.1f}）")
        reasons.append(f"赔率边际 {expected_edge_pct:.2f}%，盈亏比代理 {profit_factor_proxy:.2f}")

        risks = [f"回撤风险概率 {dd_prob * 100:.1f}%", "若跌破止损位需严格执行退出"]
        if main_net_inflow_yi < 0:
            risks.append("主力资金呈净流出，短线波动可能放大")
        if turnover_rate > 15:
            risks.append("换手率过高，短线博弈强，追高风险较大")
        if expected_edge_pct < edge_gate:
            risks.append("当前赔率边际一般，若追求更高胜率应等待更优入场点")
        if state_tag == "defensive":
            risks.append("当前市场偏防守，注意控制仓位")
        if news_net_score <= -10:
            risks.append("近期公告/政策偏负面，需降低主观乐观预期")
        risks.extend(quality_notes[:2])

        trend_score = self._clamp(50 + signal_score * 0.4, 0, 100)
        risk_adjusted_score = self._clamp(74 - dd_prob * 68 - execution_penalty * 0.55, 0, 100)
        news_display_score = self._clamp(self._safe_float(news_factor.get("total_score"), 50.0), 0, 100)

        if risk_level == "low":
            if strategy == "pullback_rebound":
                total_score = (
                    trend_score * 0.10
                    + flow_score * 0.12
                    + turnover_score * 0.10
                    + quality_score * 0.24
                    + risk_adjusted_score * 0.26
                    + edge_score * 0.08
                    + news_display_score * 0.10
                )
            else:
                total_score = (
                    trend_score * 0.12
                    + flow_score * 0.14
                    + turnover_score * 0.10
                    + quality_score * 0.20
                    + risk_adjusted_score * 0.18
                    + edge_score * 0.16
                    + news_display_score * 0.10
                )
        elif risk_level == "high":
            if strategy == "pullback_rebound":
                total_score = (
                    trend_score * 0.16
                    + flow_score * 0.18
                    + turnover_score * 0.13
                    + quality_score * 0.24
                    + risk_adjusted_score * 0.10
                    + edge_score * 0.09
                    + news_display_score * 0.10
                )
            else:
                total_score = (
                    trend_score * 0.20
                    + flow_score * 0.23
                    + turnover_score * 0.13
                    + quality_score * 0.16
                    + risk_adjusted_score * 0.08
                    + edge_score * 0.10
                    + news_display_score * 0.10
                )
        else:
            if strategy == "pullback_rebound":
                total_score = (
                    trend_score * 0.12
                    + flow_score * 0.14
                    + turnover_score * 0.10
                    + quality_score * 0.24
                    + risk_adjusted_score * 0.22
                    + edge_score * 0.08
                    + news_display_score * 0.10
                )
            else:
                total_score = (
                    trend_score * 0.12
                    + flow_score * 0.18
                    + turnover_score * 0.10
                    + quality_score * 0.16
                    + risk_adjusted_score * 0.16
                    + edge_score * 0.18
                    + news_display_score * 0.10
                )

        total_score = self._clamp(total_score - score_reliability_penalty, 0, 100)

        ml_enrichment: Dict[str, Any] = {}
        if self.ml_model_service:
            try:
                feature_payload = self.ml_model_service.feature_builder.build_live_features(
                    analyzed_df,
                    market_state=market_state,
                    news_factor=news_factor,
                    money_flow_proxy_yi=main_net_inflow_yi,
                    turnover_rate=turnover_rate,
                )
                model_prediction = self.ml_model_service.predict_live(
                    feature_payload,
                    pick_context={
                        "symbol": symbol,
                        "take_profit_ratio": take_profit_ratio,
                        "stop_loss_ratio": stop_loss_ratio,
                    },
                )
                if model_prediction:
                    model_probability = model_prediction.get("model_probability") or {}
                    model_up_prob = self._safe_float(model_probability.get("model_up_prob"), up_prob)
                    model_dd_prob = self._safe_float(model_probability.get("model_dd_prob"), dd_prob)
                    model_final_score = self._safe_float(model_probability.get("final_score"), total_score)
                    up_prob = self._clamp(up_prob * 0.45 + model_up_prob * 0.55, 0.05, 0.90)
                    dd_prob = self._clamp(dd_prob * 0.45 + model_dd_prob * 0.55, 0.05, 0.85)
                    total_score = self._clamp(total_score * 0.65 + model_final_score * 0.35, 0, 100)
                    ml_enrichment = {
                        **model_prediction,
                        "model_version_id": model_prediction.get("model_version_id"),
                    }
            except Exception:
                ml_enrichment = {}

        expected_mult = 16 if risk_level == "low" else (24 if risk_level == "high" else 20)
        expected_return = round((up_prob - dd_prob) * expected_mult, 2)

        now_date = datetime.now().strftime("%Y-%m-%d")
        display_score = round(self._clamp(total_score, 0, 100), 2)
        return {
            "pick_id": f"{now_date}-{symbol}-S1",
            "symbol": symbol,
            "name": quote.get("name", symbol),
            "industry": industry_name,
            "action": action,
            "score": display_score,
            "up_prob": round(up_prob, 4),
            "dd_prob": round(dd_prob, 4),
            "confidence_level": confidence,
            "horizon_days": 15,
            "expected_return_pct": expected_return,
            "expected_edge_pct": round(expected_edge_pct, 2),
            "profit_factor_proxy": round(profit_factor_proxy, 3),
            "entry_range": [entry_min, entry_max],
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "position_pct": round(base_position if action == "buy" else base_position * 0.5, 2),
            "reasons": reasons[:4],
            "risks": risks[:4],
            "invalid_conditions": [
                f"收盘价跌破 {stop_loss}",
                "成交量连续2日显著萎缩",
                "主力资金由净流入转为持续净流出",
            ],
            "market_metrics": {
                "main_net_inflow_yi": round(main_net_inflow_yi, 3),
                "turnover_rate": round(turnover_rate, 3),
                "money_flow_source": money_flow_source,
                "money_flow_quality": money_flow_quality,
            },
            "money_flow_quality": money_flow_quality,
            "money_flow_confidence": money_flow_confidence,
            "news_factor": news_factor,
            "evidence_summary": {
                "strategy_code": strategy,
                "strategy_version": ("v1.3-rebound-ml-calibrated" if strategy == "pullback_rebound" else "v1.3-breakout-ml-calibrated") if ml_enrichment else ("v1.2-rebound-gated" if strategy == "pullback_rebound" else "v1.2-breakout-gated"),
                "model_win_rate_proxy": round(self._clamp(up_prob, 0.30, 0.82), 4),
                "model_drawdown_proxy": round(self._clamp(dd_prob, 0.08, 0.45), 4),
                "proxy_only": not bool(ml_enrichment),
                "state_tag": state_tag,
                "quality_gate_passed": not disqualify_buy,
                "quality_notes": quality_notes[:4],
                "score_reliability_penalty": round(score_reliability_penalty, 2),
            },
            "score_breakdown": {
                "trend": round(trend_score, 2),
                "money_flow": round(flow_score, 2),
                "turnover_liquidity": round(turnover_score, 2),
                "quality": round(quality_score, 2),
                "risk_adjusted": round(risk_adjusted_score, 2),
                "news": round(news_display_score, 2),
                "total": display_score,
            },
            "teaching_points": [
                "先看市场状态，再决定是否进攻",
                "资金流与换手率要结合看：放量流入优于放量分歧",
                "概率高不代表必赚，仓位纪律同样关键",
            ],
            **ml_enrichment,
        }

    def _rank_score(self, pick: Dict[str, Any], risk_level: str) -> float:
        if self.scoring_service:
            return self.scoring_service.rank_score(pick, risk_level)
        up_prob = float(pick.get("up_prob", 0))
        dd_prob = float(pick.get("dd_prob", 1))
        total_score = float((pick.get("score_breakdown") or {}).get("total", 0))
        risk_adjusted = float((pick.get("score_breakdown") or {}).get("risk_adjusted", 0))
        edge_pct = float(pick.get("expected_edge_pct", 0) or 0)
        profit_factor = float(pick.get("profit_factor_proxy", 1) or 1)
        theme_score = self._safe_float(pick.get("theme_rank_score"), 0)
        theme_component = theme_score if theme_score > 0 else 35.0
        edge_score = self._clamp(50 + edge_pct * 6, 0, 100)
        pf_score = self._clamp(45 + (profit_factor - 1) * 22, 0, 100)
        anti_dd_score = (1 - dd_prob) * 100
        up_score = up_prob * 100

        if risk_level == "low":
            return anti_dd_score * 0.30 + edge_score * 0.22 + risk_adjusted * 0.21 + pf_score * 0.09 + total_score * 0.10 + theme_component * 0.08
        if risk_level == "high":
            return up_score * 0.20 + edge_score * 0.27 + pf_score * 0.16 + total_score * 0.16 + anti_dd_score * 0.10 + theme_component * 0.11
        return up_score * 0.18 + anti_dd_score * 0.18 + edge_score * 0.25 + pf_score * 0.13 + total_score * 0.17 + theme_component * 0.09

    def _risk_specific_pick_sort_key(self, pick: Dict[str, Any], risk_level: str) -> float:
        """风险等级必须改变排序偏好，而不只是改变文案。

        低风险：优先低回撤、风险调整分和流动性稳定。
        中风险：保持赔率/胜率/风险均衡。
        高风险：优先弹性、换手活跃度和预期收益，允许更高波动。
        """
        if self.scoring_service:
            return self.scoring_service.risk_specific_sort_key(pick, risk_level)
        up_prob = self._safe_float(pick.get("up_prob"), 0)
        dd_prob = self._safe_float(pick.get("dd_prob"), 1)
        expected_return = self._safe_float(pick.get("expected_return_pct"), 0)
        edge_pct = self._safe_float(pick.get("expected_edge_pct"), 0)
        profit_factor = self._safe_float(pick.get("profit_factor_proxy"), 1)
        breakdown = pick.get("score_breakdown") or {}
        total_score = self._safe_float(breakdown.get("total"), 0)
        risk_adjusted = self._safe_float(breakdown.get("risk_adjusted"), 0)
        quality = self._safe_float(breakdown.get("quality"), 0)
        trend = self._safe_float(breakdown.get("trend"), 0)
        metrics = pick.get("market_metrics") or {}
        turnover = self._safe_float(metrics.get("turnover_rate"), 0)
        flow_yi = self._safe_float(metrics.get("main_net_inflow_yi"), 0)
        theme_score = self._safe_float(pick.get("theme_rank_score"), 0)
        theme_component = theme_score if theme_score > 0 else 35.0
        symbol = str(pick.get("symbol") or "")
        board_penalty = 4.0 if symbol.startswith(("300", "688")) else 0.0

        if risk_level == "low":
            turnover_stability = 100 - abs(turnover - 4.0) * 8
            return (
                (1 - dd_prob) * 34
                + risk_adjusted * 0.28
                + quality * 0.16
                + self._clamp(turnover_stability, 0, 100) * 0.10
                + self._clamp(flow_yi * 8 + 50, 0, 100) * 0.08
                + total_score * 0.04
                + theme_component * 0.08
                - board_penalty
            )
        if risk_level == "high":
            activity_score = self._clamp(turnover * 7.5, 0, 100)
            watch_bonus = 14.0 if pick.get("action") == "watch" else 0.0
            active_bonus = 8.0 if turnover >= 10 else (4.0 if turnover >= 8 else 0.0)
            growth_board_bonus = 4.0 if symbol.startswith(("300", "688")) else 0.0
            return (
                up_prob * 22
                + expected_return * 1.6
                + edge_pct * 2.2
                + activity_score * 0.42
                + trend * 0.14
                + total_score * 0.06
                + (profit_factor - 1) * 8
                + watch_bonus
                + active_bonus
                + growth_board_bonus
                + theme_component * 0.14
                - dd_prob * 6
            )
        return self._rank_score(pick, risk_level)

    def _apply_risk_specific_selection(self, picks: List[Dict[str, Any]], risk_level: str) -> List[Dict[str, Any]]:
        if self.scoring_service:
            return self.scoring_service.apply_risk_specific_selection(picks, risk_level)
        if not picks:
            return []

        if risk_level == "low":
            selected = [
                p for p in picks
                if (
                    p.get("action") == "buy"
                    and self._safe_float(p.get("dd_prob"), 1) <= 0.24
                    and self._safe_float((p.get("score_breakdown") or {}).get("risk_adjusted"), 0) >= 56
                    and self._safe_float((p.get("market_metrics") or {}).get("turnover_rate"), 0) <= 9
                    and self._safe_float((p.get("market_metrics") or {}).get("main_net_inflow_yi"), 0) >= -0.2
                )
            ]
            if len(selected) < 8:
                selected = [
                    p for p in picks
                    if (
                        p.get("action") == "buy"
                        and self._safe_float(p.get("dd_prob"), 1) <= 0.32
                        and self._safe_float((p.get("score_breakdown") or {}).get("risk_adjusted"), 0) >= 50
                    )
                ]
            selected.sort(key=lambda x: self._risk_specific_pick_sort_key(x, "low"), reverse=True)
            return selected

        if risk_level == "high":
            selected = [
                p for p in picks
                if (
                    p.get("action") in {"buy", "watch"}
                    and self._safe_float(p.get("dd_prob"), 1) <= 0.55
                    and self._safe_float(p.get("expected_edge_pct"), 0) >= 0.0
                )
            ]
            active_selected = [
                p for p in selected
                if (
                    p.get("action") == "watch"
                    or self._safe_float((p.get("market_metrics") or {}).get("turnover_rate"), 0) >= 9
                    or str(p.get("symbol") or "").startswith(("300", "688"))
                )
            ]
            if len(active_selected) >= 10:
                selected = active_selected
            selected.sort(key=lambda x: self._risk_specific_pick_sort_key(x, "high"), reverse=True)
            return selected

        selected = [p for p in picks if self._safe_float(p.get("dd_prob"), 1) <= 0.42]
        selected.sort(key=lambda x: self._risk_specific_pick_sort_key(x, "medium"), reverse=True)
        return selected

    def _calibrate_pick_scores(self, picks: List[Dict[str, Any]], market_state: Dict[str, Any]) -> None:
        """将原始总分映射为更可信的展示分，降低纯相对排名的误导。"""
        if self.scoring_service:
            self.scoring_service.calibrate_pick_scores(picks, market_state)
            return
        if not picks:
            return

        raw_scores: List[float] = []
        for pick in picks:
            breakdown = pick.get("score_breakdown") or {}
            raw_total = float(breakdown.get("total", 0) or 0)
            breakdown["raw_total"] = round(raw_total, 2)
            pick["score_breakdown"] = breakdown
            raw_scores.append(raw_total)

        ordered = sorted(raw_scores)
        n = len(ordered)
        state_tag = str((market_state or {}).get("state_tag") or "neutral")
        state_adjust = -2.0 if state_tag == "defensive" else (1.0 if state_tag == "offensive" else 0.0)

        def _percentile(value: float) -> float:
            if n <= 1:
                return 0.5
            less = sum(1 for x in ordered if x < value)
            equal = sum(1 for x in ordered if x == value)
            return (less + 0.5 * equal) / n

        for pick in picks:
            breakdown = pick.get("score_breakdown") or {}
            raw_total = float(breakdown.get("raw_total", breakdown.get("total", 0)) or 0)
            risk_adjusted = float(breakdown.get("risk_adjusted", 0) or 0)
            edge_pct = float(pick.get("expected_edge_pct", 0) or 0)
            profit_factor = float(pick.get("profit_factor_proxy", 1) or 1)

            up_score = float(pick.get("up_prob", 0) or 0) * 100
            anti_dd_score = (1 - float(pick.get("dd_prob", 1) or 1)) * 100
            edge_score = self._clamp(48 + edge_pct * 6.5, 0, 100)
            pf_score = self._clamp(45 + (profit_factor - 1) * 22, 0, 100)
            relative_score = 48 + _percentile(raw_total) * 24
            quality_score = (
                up_score * 0.22
                + anti_dd_score * 0.20
                + risk_adjusted * 0.20
                + edge_score * 0.24
                + pf_score * 0.14
            )

            bonus = 0.0
            if pick.get("action") == "buy":
                bonus += 2.0
            confidence = str(pick.get("confidence_level") or "")
            if confidence == "high":
                bonus += 4.0
            elif confidence == "medium":
                bonus += 2.0
            flow_yi = float((pick.get("market_metrics") or {}).get("main_net_inflow_yi", 0) or 0)
            if flow_yi > 2:
                bonus += 2.0
            elif flow_yi < -1:
                bonus -= 4.0
            if float(pick.get("dd_prob", 1) or 1) <= 0.20:
                bonus += 1.0
            if edge_pct < 0.6:
                bonus -= 8.0
            elif edge_pct < 1.5:
                bonus -= 3.0
            if profit_factor < 1.15:
                bonus -= 6.0
            elif profit_factor < 1.30:
                bonus -= 2.0

            display_total = self._clamp(
                raw_total * 0.34 + quality_score * 0.46 + relative_score * 0.20 + bonus + state_adjust,
                0,
                100,
            )
            breakdown["total"] = round(display_total, 2)
            breakdown["pre_theme_total"] = breakdown["total"]
            pick["score_breakdown"] = breakdown
            pick["score"] = breakdown["total"]

    def _apply_universe_quality_guard(self, picks: List[Dict[str, Any]], universe_meta: Dict[str, Any]) -> None:
        """数据源降级时降低展示分和执行级别，避免固定兜底池产生虚假高分。"""
        if self.scoring_service:
            self.scoring_service.apply_universe_quality_guard(picks, universe_meta)
            return
        if not picks:
            return
        source = str((universe_meta or {}).get("source") or "")
        snapshot_count = int(self._safe_float((universe_meta or {}).get("snapshot_count"), 0))
        is_fallback = source.startswith("fallback_") or snapshot_count <= 0
        if not is_fallback:
            return

        for pick in picks:
            breakdown = pick.get("score_breakdown") or {}
            penalty = 7.0
            if pick.get("money_flow_quality") != "real":
                penalty += 4.0
            if not pick.get("theme_tags") and not pick.get("matched_theme_ids"):
                penalty += 2.0
            raw_total = self._safe_float(breakdown.get("total"), 0)
            capped = min(raw_total - penalty, 78.0 if pick.get("money_flow_quality") != "real" else 82.0)
            breakdown["total"] = round(self._clamp(capped, 0, 100), 2)
            breakdown["universe_quality_penalty"] = round(penalty, 2)
            pick["score_breakdown"] = breakdown
            pick["score"] = breakdown["total"]
            pick["data_quality_warning"] = "全A快照不可用，当前来自兜底候选池；评分已按数据置信度降权。"
            if pick.get("action") == "buy" and pick.get("money_flow_quality") != "real":
                pick["action"] = "watch"
                pick["position_pct"] = round(self._safe_float(pick.get("position_pct"), 0) * 0.5, 2)
                risks = pick.setdefault("risks", [])
                risks.insert(0, "数据源降级且资金流非真实数据，暂不升级为核心买入。")

    def _upgrade_final_money_flow(self, picks: List[Dict[str, Any]]) -> None:
        """Fetch real money-flow for final visible picks only.

        Candidate prefiltering may use quote-derived proxy factors for speed, but
        the final cards should prefer real money-flow when the data source is
        available.
        """
        targets = [p for p in (picks or []) if p.get("symbol") and p.get("money_flow_quality") != "real"]
        if not targets:
            return
        max_workers = min(4, len(targets))
        executor = ThreadPoolExecutor(max_workers=max_workers)
        future_map = {
            executor.submit(self.data_source_manager.get_money_flow, pick.get("symbol"), 3): pick
            for pick in targets
        }
        try:
            completed, pending = wait(list(future_map.keys()), timeout=10)
            for future in completed:
                pick = future_map.get(future)
                if not pick:
                    continue
                try:
                    money_flow = future.result()
                except Exception:
                    money_flow = None
                if money_flow:
                    self._apply_money_flow_to_pick(pick, money_flow)
            for future in pending:
                future.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _apply_money_flow_to_pick(self, pick: Dict[str, Any], money_flow: Dict[str, Any]) -> None:
        if self.scoring_service:
            repricing = self.scoring_service.apply_money_flow_to_pick(pick, money_flow)
            quality = repricing.get("quality") or ("proxy" if money_flow.get("quality") == "proxy" else "real")
            source = repricing.get("source") or str(money_flow.get("source") or "remote")
            try:
                self.store.upsert_money_flow_snapshot(
                    trade_date=self._recommendation_trade_date(),
                    symbol=str(pick.get("symbol") or money_flow.get("symbol") or ""),
                    payload={**money_flow, "quality": quality, "available": True, "source": source},
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception:
                pass
            return

        quality = "proxy" if money_flow.get("quality") == "proxy" else "real"
        source = str(money_flow.get("source") or "remote")
        main_net_inflow_yi = float(money_flow.get("main_net_inflow") or 0) / 100000000
        confidence = 1.0 if quality == "real" else 0.45
        metrics = pick.setdefault("market_metrics", {})
        old_flow_yi = self._safe_float(metrics.get("main_net_inflow_yi"), 0)
        metrics.update(
            {
                "main_net_inflow_yi": round(main_net_inflow_yi, 3),
                "money_flow_source": source,
                "money_flow_quality": quality,
                "money_flow_display_mode": "proxy" if quality == "proxy" else "normal",
            }
        )
        pick["money_flow_quality"] = quality
        pick["money_flow_confidence"] = confidence
        pick["money_flow_source"] = source
        pick["money_flow_display_mode"] = "proxy" if quality == "proxy" else "normal"

        breakdown = pick.get("score_breakdown") or {}
        old_flow_score = self._safe_float(breakdown.get("money_flow"), 50)
        flow_multiplier = 8 if quality == "real" else 3
        new_flow_score = self._clamp(50 + main_net_inflow_yi * flow_multiplier, 0, 100)
        breakdown["money_flow"] = round(new_flow_score, 2)
        breakdown["money_flow_repriced"] = True
        breakdown["money_flow_source"] = source
        total = self._safe_float(breakdown.get("total"), 0)
        breakdown["total"] = round(self._clamp(total + (new_flow_score - old_flow_score) * 0.08, 0, 100), 2)
        pick["score_breakdown"] = breakdown
        pick["score"] = breakdown["total"]

        reasons = pick.setdefault("reasons", [])
        label = "真实资金流" if quality == "real" else "代理资金强度"
        flow_text = f"{label}净流入 {main_net_inflow_yi:.2f} 亿" if main_net_inflow_yi >= 0 else f"{label}净流出 {abs(main_net_inflow_yi):.2f} 亿"
        if flow_text not in reasons:
            reasons.append(flow_text)
        if quality == "real":
            risks = [
                risk for risk in (pick.get("risks") or [])
                if "资金流为代理或不可用" not in str(risk)
            ]
            if old_flow_yi >= 0 and main_net_inflow_yi < 0:
                risks.insert(0, "真实资金流转为净流出，需降低执行优先级。")
            pick["risks"] = risks
        try:
            self.store.upsert_money_flow_snapshot(
                trade_date=self._recommendation_trade_date(),
                symbol=str(pick.get("symbol") or money_flow.get("symbol") or ""),
                payload={**money_flow, "quality": quality, "available": True, "source": source},
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception:
            pass

    def _build_pick_decision(
        self,
        pick: Dict[str, Any],
        strategy_health: Dict[str, Any],
        market_state: Dict[str, Any],
        risk_level: str,
    ) -> Dict[str, Any]:
        """Translate a numeric pick into a beginner-readable decision."""
        breakdown = pick.get("score_breakdown") or {}
        total = self._safe_float(breakdown.get("total"), 0)
        up_prob = self._safe_float(pick.get("up_prob"), 0)
        dd_prob = self._safe_float(pick.get("dd_prob"), 1)
        edge_pct = self._safe_float(pick.get("expected_edge_pct"), 0)
        profit_factor = self._safe_float(pick.get("profit_factor_proxy"), 1)
        action = str(pick.get("action") or "watch")
        state_tag = str((market_state or {}).get("state_tag") or "neutral")
        live_ready = bool((strategy_health or {}).get("live_ready"))
        failed_checks = (strategy_health or {}).get("failed_checks") or []
        probability_model = pick.get("probability_model") or {}

        grade = "C"
        level = "观察"
        executable = False
        if action == "buy" and total >= 86 and up_prob >= 0.66 and dd_prob <= 0.24 and edge_pct >= 2.2 and profit_factor >= 1.35:
            grade = "A"
            level = "核心候选"
            executable = True
        elif action == "buy" and total >= 76 and up_prob >= 0.58 and dd_prob <= 0.34 and edge_pct >= 1.0:
            grade = "B"
            level = "小仓试错"
            executable = True
        elif action == "watch" or total >= 66:
            grade = "C"
            level = "观察等待"
        else:
            grade = "D"
            level = "不建议"

        if state_tag == "defensive" and grade == "A":
            grade = "B"
            level = "防守小仓"
        if risk_level == "low" and dd_prob > 0.28 and grade in {"A", "B"}:
            grade = "C"
            level = "低风险用户观察"
            executable = False

        real_money_allowed = bool(executable and live_ready and grade in {"A", "B"})
        mode = "real_allowed" if real_money_allowed else ("paper_only" if executable else "watch_only")
        reason = []
        if not live_ready:
            reason.append("策略尚未通过实盘准入，建议只做模拟验证")
        if state_tag == "defensive":
            reason.append("市场处于防守状态，需降低仓位和交易频率")
        if failed_checks:
            reason.append("最近回测仍有未通过项：" + "、".join(str(x.get("label") or x.get("key") or x) for x in failed_checks[:2]))
        if not reason and real_money_allowed:
            reason.append("策略证据、赔率和回撤条件均满足当前准入要求")
        if pick.get("data_quality_warning"):
            reason.insert(0, pick.get("data_quality_warning"))
            if grade in {"A", "B"}:
                grade = "C"
                level = "数据降级观察"
                executable = False
                real_money_allowed = False
                mode = "watch_only"

        return {
            "grade": grade,
            "level": level,
            "mode": mode,
            "executable": executable,
            "real_money_allowed": real_money_allowed,
            "probability_label": probability_model.get("label") or "规则代理概率",
            "probability_reliability": "已按历史评分分层校准" if probability_model.get("calibrated") else "待历史模型校准",
            "evidence_status": (strategy_health or {}).get("status") or "unverified",
            "evidence_grade": (strategy_health or {}).get("credibility_grade"),
            "evidence_score": (strategy_health or {}).get("credibility_score"),
            "summary": "；".join(reason[:3]) if reason else "仅作为观察候选，不建议直接交易。",
        }

    def _find_probability_bucket(self, score: float, buckets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for bucket in buckets or []:
            min_score = self._safe_float(bucket.get("min_score"), 0)
            max_score = self._safe_float(bucket.get("max_score"), 100)
            if min_score <= score < max_score:
                return bucket
        return None

    def _apply_probability_calibration(self, picks: List[Dict[str, Any]], calibration: Dict[str, Any]) -> None:
        buckets = (calibration or {}).get("buckets") or []
        overall_calibrated = bool((calibration or {}).get("calibrated"))
        for pick in picks:
            score = self._safe_float((pick.get("score_breakdown") or {}).get("total"), 0)
            bucket = self._find_probability_bucket(score, buckets)
            if not bucket:
                pick["probability_model"] = {
                    "type": "proxy_rule",
                    "label": "规则代理概率",
                    "calibrated": False,
                    "message": "未找到匹配的历史评分分层，当前概率仍为规则代理值。",
                }
                continue

            sample_count = int(bucket.get("sample_count") or 0)
            bucket_calibrated = bool(bucket.get("calibrated")) and overall_calibrated
            observed_win_rate = self._safe_float(bucket.get("win_rate"), 0)
            loss_rate = self._safe_float(bucket.get("loss_rate"), 0)
            if not bucket_calibrated:
                pick["probability_model"] = {
                    "type": "proxy_rule_with_history_hint",
                    "label": "规则代理概率",
                    "calibrated": False,
                    "sample_count": sample_count,
                    "message": f"同评分区间历史闭环样本仅 {sample_count} 笔，样本不足，不能校准为真实胜率。",
                }
                continue

            original_up = self._safe_float(pick.get("up_prob"), 0.5)
            original_dd = self._safe_float(pick.get("dd_prob"), 0.35)
            # 历史样本只修正概率，不改变入选原因；避免少量样本把模型完全带偏。
            pick["up_prob"] = round(self._clamp(original_up * 0.40 + observed_win_rate * 0.60, 0.05, 0.90), 4)
            pick["dd_prob"] = round(self._clamp(original_dd * 0.50 + loss_rate * 0.50, 0.05, 0.80), 4)
            pick["probability_model"] = {
                "type": "historical_score_bucket",
                "label": "历史校准概率",
                "calibrated": True,
                "sample_count": sample_count,
                "score_bucket": bucket.get("label"),
                "observed_win_rate": round(observed_win_rate, 4),
                "observed_loss_rate": round(loss_rate, 4),
                "message": f"基于最近回测中“{bucket.get('label')}”评分分层的 {sample_count} 笔闭环交易校准。",
            }

    def _attach_trade_plan(
        self,
        picks: List[Dict[str, Any]],
        strategy_health: Dict[str, Any],
        market_state: Dict[str, Any],
        risk_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        risk_level = str((risk_profile or {}).get("risk_level") or "medium")
        max_position_pct = self._safe_float((risk_profile or {}).get("max_position_pct"), 10)
        probability_calibration = (strategy_health or {}).get("probability_calibration") or {}
        self._apply_probability_calibration(picks, probability_calibration)
        for pick in picks:
            model = pick.get("probability_model") or {}
            ml_probability = pick.get("model_probability") or {}
            if ml_probability:
                model = {
                    "type": "ml_explainable_probability",
                    "label": ml_probability.get("label") or "机器学习校准概率",
                    "calibrated": True,
                    "model_version_id": pick.get("model_version_id"),
                    "status": ml_probability.get("status"),
                    "message": (
                        f"基于模型 {pick.get('model_version_id')} 的历史样本概率层；"
                        f"训练区间 {ml_probability.get('train_start') or '-'} 至 {ml_probability.get('train_end') or '-'}。"
                    ),
                }
                pick["probability_model"] = model
            if not model:
                model = {
                    "type": "proxy_rule",
                    "label": "规则代理概率",
                    "calibrated": False,
                    "message": "当前概率由规则和历史回放代理估算；历史样本不足，暂不能作为实盘胜率。",
                }
                pick["probability_model"] = model
            pick["decision"] = self._build_pick_decision(pick, strategy_health, market_state, risk_level)

        core = [p for p in picks if (p.get("decision") or {}).get("grade") == "A"]
        trial = [p for p in picks if (p.get("decision") or {}).get("grade") == "B"]
        watch = [p for p in picks if (p.get("decision") or {}).get("grade") == "C"]
        executable = core + trial
        live_ready = bool((strategy_health or {}).get("live_ready"))
        state_tag = str((market_state or {}).get("state_tag") or "neutral")

        if not picks:
            primary_action = "no_trade"
            headline = "今日不交易"
            summary = "当前市场与策略条件不足，建议等待更高质量信号。"
        elif not executable:
            primary_action = "watch"
            headline = "今日只观察"
            summary = "有候选但未达到交易计划门槛，建议加入观察而不是买入。"
        elif not live_ready:
            primary_action = "paper_only"
            headline = "只建议模拟验证"
            summary = "当前策略尚未通过实盘准入；可以用模拟买入验证，不建议小白用户直接实盘。"
        elif state_tag == "defensive":
            primary_action = "light_trade"
            headline = "防守小仓试错"
            summary = "市场偏防守，仅允许极小仓位执行 A/B 级候选。"
        else:
            primary_action = "trade_plan"
            headline = "今日有交易计划"
            summary = "存在通过策略证据和风险条件的 A/B 级候选。"

        recommended = executable[:3]
        suggested_total_exposure = min(
            sum(self._safe_float(p.get("position_pct"), max_position_pct) for p in recommended),
            max_position_pct * max(1, min(len(recommended), 3)),
            30.0,
        )
        if primary_action in {"paper_only", "watch", "no_trade"}:
            suggested_total_exposure = 0.0
        elif primary_action == "light_trade":
            suggested_total_exposure = min(suggested_total_exposure, 8.0)

        return {
            "primary_action": primary_action,
            "headline": headline,
            "summary": summary,
            "core_count": len(core),
            "trial_count": len(trial),
            "watch_count": len(watch),
            "recommended_count": len(recommended),
            "suggested_total_exposure_pct": round(suggested_total_exposure, 2),
            "probability_model": {
                "type": "ml_explainable_probability" if any(p.get("model_probability") for p in picks) else (probability_calibration.get("type") or "proxy_rule"),
                "label": "机器学习校准概率" if any(p.get("model_probability") for p in picks) else (probability_calibration.get("label") or "规则代理概率"),
                "calibrated": bool(any(p.get("model_probability") for p in picks) or probability_calibration.get("calibrated")),
                "sample_count": probability_calibration.get("sample_count") or 0,
                "next_phase": (
                    "继续用滚动回测监控模型漂移，并只在策略准入通过时小仓实盘。"
                    if any(p.get("model_probability") for p in picks)
                    else "继续滚动回测和模拟交易，扩大每个评分分层样本。"
                    if probability_calibration.get("calibrated")
                    else "需要至少30笔闭环回测交易，才能完成历史概率校准。"
                ),
            },
            "execution_rules": [
                "只执行 A/B 级候选，C 级只观察。",
                "策略未通过实盘准入时，只允许模拟买入验证。",
                "买入后必须同时记录止损、止盈和失效条件。",
            ],
        }

    def get_today_picks(self, max_count: int = 5, user_id: str = "default", risk_level: Optional[str] = None) -> Dict[str, Any]:
        max_count = max(1, min(max_count, 40))

        active_strategy = self.get_active_strategy_config(user_id=user_id)
        strategy_code = self._normalize_strategy_code((active_strategy or {}).get("strategy_code"))
        strategy_profile_key = (active_strategy or {}).get("profile_key")
        strategy_config = self._sanitize_strategy_config((active_strategy or {}).get("config") or {})
        risk_profile = self.get_risk_profile(user_id).copy()
        if risk_level in {"low", "medium", "high"}:
            risk_profile["risk_level"] = risk_level
        elif strategy_config.get("risk_level"):
            risk_profile["risk_level"] = strategy_config.get("risk_level")
        if strategy_config.get("max_position_pct"):
            risk_profile["max_position_pct"] = float(strategy_config["max_position_pct"])

        trade_date = self._recommendation_trade_date()
        level = risk_profile.get("risk_level", "medium")
        score_threshold = self._safe_float(strategy_config.get("score_threshold"), 0)
        cache_key = f"{trade_date}:{user_id}:{level}:{strategy_code}:{int(score_threshold)}"
        now_ts = datetime.now().timestamp()

        cache_item = self._today_picks_cache.get(cache_key)
        if cache_item:
            cached_source = str(
                (((cache_item.get("data") or {}).get("universe_meta") or {}).get("source") or "")
            )
            cache_age = now_ts - float(cache_item.get("ts", 0) or 0)
            fallback_cache_still_usable = (
                cached_source.startswith("fallback_")
                and self._today_picks_cache_ttl_seconds > 0
                and cache_age <= self._today_picks_cache_ttl_seconds
            )
            full_cache_usable = bool(cached_source and not cached_source.startswith("fallback_"))
            if not (full_cache_usable or fallback_cache_still_usable):
                cache_item = None

        if cache_item:
            cached_result = copy.deepcopy(cache_item["data"])
            all_cached_picks = cached_result.get("picks", [])
            cached_result["picks"] = all_cached_picks[:max_count]
            cached_meta = cached_result.get("universe_meta") or {}
            cached_counts = cached_meta.get("pipeline_counts") or {}
            if isinstance(cached_counts, dict):
                cached_counts["visible_output"] = len(cached_result["picks"])
                cached_meta["pipeline_counts"] = cached_counts
                cached_result["universe_meta"] = cached_meta
            cached_result["no_trade"] = len(cached_result["picks"]) == 0
            cached_result["no_trade_reason"] = (
                "当前市场与策略条件不足，建议今日不交易"
                if len(cached_result["picks"]) == 0
                else None
            )
            if "trade_plan" not in cached_result:
                cached_result["trade_plan"] = self._attach_trade_plan(
                    all_cached_picks,
                    strategy_health=cached_result.get("strategy_health") or {},
                    market_state=cached_result.get("market_state") or {},
                    risk_profile=cached_result.get("risk_profile") or {},
                )
            cached_result["status"] = "cached"
            cached_result["is_refreshing"] = bool(self._refresh_state.get("is_refreshing"))
            cached_result["data_quality"] = self._build_data_quality(cached_result)
            cached_result["data_diagnostics"] = self._build_data_diagnostics(cached_result)
            self._attach_user_actions(cached_result["picks"], user_id)
            return cached_result

        market_state = self.get_market_state_today()
        picks: List[Dict[str, Any]] = []
        target_universe_size = int(self._safe_float(strategy_config.get("universe_size"), 120))
        universe_result = self._build_dynamic_candidates(
            level,
            target_size=target_universe_size,
            strategy_code=strategy_code,
        )
        candidate_rows = universe_result.get("candidates", [])
        original_candidate_rows = list(candidate_rows)
        theme_watchlist = universe_result.get("theme_watchlist") or []
        universe_meta = universe_result.get("meta", {})
        snapshot_count = int(self._safe_float((universe_meta or {}).get("snapshot_count"), 0))
        if snapshot_count < 500:
            result = self._build_degraded_today_result(
                trade_date=trade_date,
                market_state=market_state,
                risk_profile=risk_profile,
                universe_meta=universe_meta,
                theme_watchlist=theme_watchlist,
                user_id=user_id,
            )
            result["picks"] = result["picks"][:max_count]
            return result

        # 根据策略配置扩大深度分析池，避免只分析过小样本导致高分不够可靠。
        if level == "high":
            analyze_budget = max(max_count * 4, int(target_universe_size * 0.45), 60)
        elif level == "low":
            analyze_budget = max(max_count * 3, int(target_universe_size * 0.35), 36)
        else:
            analyze_budget = max(max_count * 4, int(target_universe_size * 0.40), 48)
        analyze_budget = min(len(candidate_rows), max(24, min(analyze_budget, 72)))
        candidate_rows = candidate_rows[: analyze_budget]
        if isinstance(universe_meta, dict):
            universe_meta["analyzed_count"] = len(candidate_rows)
            pipeline_counts = universe_meta.setdefault("pipeline_counts", {})
            if isinstance(pipeline_counts, dict):
                pipeline_counts["analyzed"] = len(candidate_rows)

        max_workers = min(6, max(1, len(candidate_rows)))
        futures = []
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = [
                executor.submit(
                    self._build_pick,
                    row.get("symbol"),
                    risk_profile,
                    market_state,
                    row,
                    strategy_code,
                )
                for row in candidate_rows
                if row.get("symbol")
            ]
            completed, pending = wait(futures, timeout=12)
            if isinstance(universe_meta, dict):
                universe_meta["analysis_completed_count"] = len(completed)
                universe_meta["analysis_timeout_count"] = len(pending)
                pipeline_counts = universe_meta.setdefault("pipeline_counts", {})
                if isinstance(pipeline_counts, dict):
                    pipeline_counts["analysis_completed"] = len(completed)
                    pipeline_counts["analysis_timeout"] = len(pending)
            for future in completed:
                try:
                    pick = future.result()
                    if pick:
                        pick["pick_id"] = f"{trade_date}-{pick.get('symbol')}-S1"
                        picks.append(pick)
                except Exception:
                    # 单票失败不影响整体结果（容错）
                    continue
            for future in pending:
                future.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        analyzed_picks_before_filters = copy.deepcopy(picks)
        market_theme_payload = self._get_market_theme_context(limit=12)
        self._apply_theme_alignment(picks, original_candidate_rows, market_theme_payload)
        analyzed_picks_before_filters = copy.deepcopy(picks)
        picks = self._apply_risk_specific_selection(picks, level)

        if market_state["state_tag"] == "defensive":
            if level == "high":
                picks = [p for p in picks if p["action"] in {"buy", "watch"} and p["dd_prob"] <= 0.40]
            else:
                picks = [p for p in picks if p["action"] == "buy" and p["dd_prob"] <= 0.30]

        # 忽略动作应真实生效：从当日候选中移除该推荐
        action_map = self._get_latest_action_map(user_id)
        ignored_pick_ids = {
            pid for pid, action_record in action_map.items()
            if action_record.get("action_type") == "ignored"
        }
        if ignored_pick_ids:
            picks = [p for p in picks if p.get("pick_id") not in ignored_pick_ids]

        self._calibrate_pick_scores(picks, market_state)
        self._apply_universe_quality_guard(picks, universe_meta)
        picks = self._apply_risk_specific_selection(picks, level)
        effective_score_threshold: Optional[float] = None
        if 50 <= score_threshold <= 95:
            risk_threshold_adjust = 4.0 if level == "low" else (-6.0 if level == "high" else 0.0)
            effective_score_threshold = self._clamp(float(score_threshold) + risk_threshold_adjust, 50, 95)
            # 严格控制“可买入”质量：只允许小幅放宽展示，不再为了凑数量大幅降低阈值。
            min_display_target = max(12, min(max_count, 24))
            threshold_picks = [
                p for p in picks
                if self._safe_float((p.get("score_breakdown") or {}).get("total"), 0) >= effective_score_threshold
            ]
            if len(threshold_picks) < min_display_target and effective_score_threshold <= 75 and level != "low":
                relaxed_threshold = max(66.0 if level == "high" else 68.0, effective_score_threshold - 3.0)
                relaxed_picks = [
                    p for p in picks
                    if self._safe_float((p.get("score_breakdown") or {}).get("total"), 0) >= relaxed_threshold
                ]
                if len(relaxed_picks) > len(threshold_picks):
                    threshold_picks = relaxed_picks
                    effective_score_threshold = relaxed_threshold
            picks = threshold_picks

        # 保留更宽的排序结果，智能选股页可展示更完整候选池。
        max_positions = int(self._safe_float(strategy_config.get("max_positions"), 5))
        if level == "low":
            display_cap = max(8, min(18, max_positions * 4))
        elif level == "high":
            display_cap = max(20, min(40, max_positions * 8))
        else:
            display_cap = max(12, min(30, max_positions * 6))
        all_picks = picks[:display_cap]
        for i, item in enumerate(all_picks, start=1):
            item["rank_no"] = i
            item["exclusion_reason"] = None
        self._upgrade_final_money_flow(all_picks)
        self._apply_theme_alignment(all_picks, original_candidate_rows, market_theme_payload)
        all_picks.sort(key=lambda item: self._safe_float((item.get("score_breakdown") or {}).get("total"), 0), reverse=True)
        for i, item in enumerate(all_picks, start=1):
            item["rank_no"] = i
        excluded_examples = self._build_excluded_examples(
            theme_watchlist,
            analyzed_picks_before_filters,
            all_picks,
            original_candidate_rows,
        )
        if isinstance(universe_meta, dict):
            universe_meta["theme_watch_count"] = len(theme_watchlist)
            universe_meta["excluded_examples_count"] = len(excluded_examples)
            universe_meta["market_theme_status"] = market_theme_payload.get("status")
            universe_meta["market_theme_count"] = len(market_theme_payload.get("theme_rank") or [])
            pipeline_counts = universe_meta.setdefault("pipeline_counts", {})
            if isinstance(pipeline_counts, dict):
                pipeline_counts["strict_buy"] = len([p for p in all_picks if p.get("action") == "buy"])
                pipeline_counts["final_output"] = len(all_picks)
                pipeline_counts["excluded_examples"] = len(excluded_examples)

        self._pick_history[trade_date] = copy.deepcopy(all_picks)
        strategy_health = {
            "status": "unverified",
            "summary": "尚未找到该策略的最近回测，请先在策略回测页跑一次全A样本回测。",
            "live_ready": False,
            "credibility_score": None,
            "credibility_grade": None,
            "last_run_id": None,
        }
        try:
            latest_runs = self.store.list_backtest_runs(user_id=user_id, strategy_code=strategy_code, limit=1)
            if latest_runs:
                latest_result = latest_runs[0].get("result") or {}
                credibility = latest_result.get("credibility") or {}
                metrics = latest_result.get("metrics") or {}
                diagnostics = latest_result.get("diagnostics") or {}
                probability_calibration = latest_result.get("probability_calibration") or {}
                live_ready = bool(credibility.get("live_ready"))
                strategy_health = {
                    "status": "live_ready" if live_ready else "paper_only",
                    "summary": credibility.get("summary") or ("满足实盘准入" if live_ready else "未达到实盘准入标准，建议继续模拟盘验证。"),
                    "live_ready": live_ready,
                    "credibility_score": credibility.get("score"),
                    "credibility_grade": credibility.get("grade"),
                    "last_run_id": latest_runs[0].get("run_id"),
                    "metrics": {
                        "annual_return": metrics.get("annual_return"),
                        "max_drawdown": metrics.get("max_drawdown"),
                        "sharpe": metrics.get("sharpe"),
                        "win_rate": metrics.get("win_rate"),
                        "profit_loss_ratio": metrics.get("profit_loss_ratio"),
                        "closed_roundtrips": diagnostics.get("closed_roundtrips"),
                        "valid_history_symbols": diagnostics.get("valid_history_symbols"),
                    },
                    "probability_calibration": probability_calibration,
                    "failed_checks": (credibility.get("failed_checks") or [])[:4],
                }
        except Exception:
            pass

        trade_plan = self._attach_trade_plan(
            all_picks,
            strategy_health=strategy_health,
            market_state=market_state,
            risk_profile=risk_profile,
        )
        try:
            self.store.upsert_pick_snapshots(
                user_id=user_id,
                trade_date=trade_date,
                strategy_code=strategy_code,
                picks=all_picks,
            )
        except Exception:
            # 推荐快照落库失败不能阻断页面，但后续会在验证阶段暴露。
            pass

        full_result = {
            "status": "fresh",
            "trade_date": trade_date,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_refreshing": bool(self._refresh_state.get("is_refreshing")),
            "market_state": market_state,
            "risk_profile": risk_profile,
            "universe_meta": universe_meta,
            "strategy_health": strategy_health,
            "trade_plan": trade_plan,
            "strategy_context": {
                "strategy_code": strategy_code,
                "profile_key": strategy_profile_key,
                "config": {
                    "risk_level": strategy_config.get("risk_level"),
                    "score_threshold": strategy_config.get("score_threshold"),
                    "effective_score_threshold": effective_score_threshold if effective_score_threshold is not None else strategy_config.get("score_threshold"),
                    "max_positions": strategy_config.get("max_positions"),
                    "max_position_pct": strategy_config.get("max_position_pct"),
                },
            },
            "theme_watchlist": theme_watchlist,
            "excluded_examples": excluded_examples,
            "picks": all_picks,
            "no_trade": len(all_picks) == 0,
            "no_trade_reason": "当前市场与策略条件不足，建议今日不交易" if len(all_picks) == 0 else None,
        }
        full_result["data_quality"] = self._build_data_quality(full_result)
        full_result["data_diagnostics"] = self._build_data_diagnostics(full_result)

        self._daily_snapshots[trade_date] = copy.deepcopy(full_result)
        if self._today_picks_cache_ttl_seconds > 0:
            self._today_picks_cache[cache_key] = {
                "ts": now_ts,
                "data": copy.deepcopy(full_result),
            }

        result = copy.deepcopy(full_result)
        result["picks"] = result["picks"][:max_count]
        result_meta = result.get("universe_meta") or {}
        result_counts = result_meta.get("pipeline_counts") or {}
        if isinstance(result_counts, dict):
            result_counts["visible_output"] = len(result["picks"])
            result_meta["pipeline_counts"] = result_counts
            result["universe_meta"] = result_meta
        result["data_quality"] = self._build_data_quality(result)
        result["data_diagnostics"] = self._build_data_diagnostics(result)
        self._attach_user_actions(result["picks"], user_id)
        return result

    def get_pick_detail(self, pick_id: str, user_id: str = "default", risk_level: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # 优先从 pick_id 对应日期查找
        trade_date = pick_id[:10] if len(pick_id) >= 10 else datetime.now().strftime("%Y-%m-%d")
        snapshot_row = self.store.get_pick_snapshot(pick_id, user_id=user_id)
        if snapshot_row and snapshot_row.get("snapshot"):
            snapshot = snapshot_row.get("snapshot") or {}
            result = {
                "trade_date": snapshot_row.get("trade_date"),
                "market_state": (self._latest_today_snapshot() or {}).get("market_state") or self.get_market_state_today(),
                **snapshot,
            }
            if self.news_service and result.get("symbol"):
                try:
                    result["news_factor"] = self.news_service.get_symbol_news_summary(
                        symbol=result.get("symbol"),
                        industry=(result.get("industry") or self._infer_board_industry(result.get("symbol"))),
                        allow_remote=False,
                    )
                except Exception:
                    pass
            result["user_action"] = self._get_latest_action_map(user_id).get(pick_id)
            return result

        data = self._daily_snapshots.get(trade_date)
        if not data:
            data = self.get_cached_today_picks(max_count=60, user_id=user_id) or {}

        for item in data.get("picks", []):
            if item["pick_id"] == pick_id:
                result = {
                    "trade_date": data["trade_date"],
                    "market_state": data["market_state"],
                    **item,
                }
                if self.news_service and result.get("symbol"):
                    try:
                        result["news_factor"] = self.news_service.get_symbol_news_summary(
                            symbol=result.get("symbol"),
                            industry=(result.get("industry") or self._infer_board_industry(result.get("symbol"))),
                            allow_remote=False,
                        )
                    except Exception:
                        pass
                action = self._get_latest_action_map(user_id).get(pick_id)
                result["user_action"] = action
                return result

        symbol = self._extract_symbol_from_pick_id(pick_id)
        if symbol:
            try:
                symbol_snapshot_row = self.store.get_latest_pick_snapshot_by_symbol(symbol, user_id=user_id)
            except Exception:
                symbol_snapshot_row = None
            symbol_snapshot = (symbol_snapshot_row or {}).get("snapshot") or {}
            if symbol_snapshot:
                result = {
                    "trade_date": (symbol_snapshot_row or {}).get("trade_date"),
                    "market_state": (self._latest_today_snapshot() or {}).get("market_state") or self.get_market_state_today(),
                    **symbol_snapshot,
                    "detail_status": "symbol_snapshot_fallback",
                    "detail_message": "未找到原推荐ID，已展示该股票最近一次推荐快照。",
                }
                result["user_action"] = self._get_latest_action_map(user_id).get(symbol_snapshot.get("pick_id"))
                return result
            for item in data.get("picks", []):
                if item.get("symbol") == symbol:
                    result = {
                        "trade_date": data["trade_date"],
                        "market_state": data["market_state"],
                        **item,
                    }
                    if self.news_service and result.get("symbol"):
                        try:
                            result["news_factor"] = self.news_service.get_symbol_news_summary(
                                symbol=result.get("symbol"),
                                industry=(result.get("industry") or self._infer_board_industry(result.get("symbol"))),
                                allow_remote=False,
                            )
                        except Exception:
                            pass
                    action = self._get_latest_action_map(user_id).get(item.get("pick_id"))
                    result["user_action"] = action
                    return result
        return None

    def get_symbol_strategy_context(
        self,
        symbol: str,
        user_id: str = "default",
        risk_level: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the smart-screen strategy score for a symbol.

        Stock detail pages should not invent a second score. They should reuse
        the same scoring output that ranks Smart Screen candidates whenever the
        symbol is in the current strategy universe.
        """
        code = str(symbol or "").strip()
        if len(code) != 6 or not code.isdigit():
            return {"symbol": code, "available": False, "reason": "invalid_symbol"}

        def _context_from_pick(item: Dict[str, Any], source: str, trade_date: Optional[str] = None) -> Dict[str, Any]:
            return {
                "symbol": code,
                "available": True,
                "source": source,
                "trade_date": trade_date,
                "pick_id": item.get("pick_id"),
                "name": item.get("name"),
                "action": item.get("action"),
                "up_prob": item.get("up_prob"),
                "dd_prob": item.get("dd_prob"),
                "expected_return_pct": item.get("expected_return_pct"),
                "expected_edge_pct": item.get("expected_edge_pct"),
                "profit_factor_proxy": item.get("profit_factor_proxy"),
                "confidence_level": item.get("confidence_level"),
                "entry_range": item.get("entry_range"),
                "take_profit": item.get("take_profit"),
                "stop_loss": item.get("stop_loss"),
                "position_pct": item.get("position_pct"),
                "horizon_days": item.get("horizon_days"),
                "invalid_conditions": item.get("invalid_conditions") or [],
                "teaching_points": item.get("teaching_points") or [],
                "score_breakdown": item.get("score_breakdown") or {},
                "reasons": item.get("reasons") or [],
                "risks": item.get("risks") or [],
                "strategy_code": (item.get("evidence_summary") or {}).get("strategy_code"),
                "evidence_summary": item.get("evidence_summary") or {},
                "decision": item.get("decision"),
                "probability_model": item.get("probability_model"),
                "market_metrics": item.get("market_metrics") or {},
                "model_probability": item.get("model_probability"),
                "factor_contributions": item.get("factor_contributions") or [],
                "model_version_id": item.get("model_version_id"),
            }

        action_ref = None
        try:
            for action in self.store.list_pick_actions(user_id=user_id, limit=500):
                action_symbol = action.get("symbol") or self._extract_symbol_from_pick_id(action.get("pick_id") or "")
                if action_symbol == code:
                    action_ref = action
                    break
        except Exception:
            action_ref = None

        if action_ref and action_ref.get("pick_id"):
            snapshot_row = self.store.get_pick_snapshot(action_ref.get("pick_id"), user_id=user_id)
            snapshot = (snapshot_row or {}).get("snapshot") or {}
            if snapshot.get("symbol") == code and snapshot.get("score_breakdown"):
                return _context_from_pick(
                    snapshot,
                    source="latest_user_action_snapshot",
                    trade_date=(snapshot_row or {}).get("trade_date"),
                )
            detail = self.get_pick_detail(action_ref.get("pick_id"), user_id=user_id, risk_level=risk_level)
            if detail and detail.get("symbol") == code and detail.get("score_breakdown"):
                return _context_from_pick(detail, source="latest_user_action")

        data = self.get_cached_today_picks(max_count=60, user_id=user_id) or {}
        for item in data.get("picks", []):
            if item.get("symbol") == code:
                return _context_from_pick(item, source="today_smart_screen")

        return {
            "symbol": code,
            "available": False,
            "source": "not_in_current_strategy_pool",
            "reason": "该股不在当前智能选股输出池中，个股详情仅展示行情分析分。",
        }

    def get_strategy_evidence(self, strategy_code: str, state_tag: Optional[str] = None) -> Dict[str, Any]:
        default_state = state_tag or "neutral"
        code = self._normalize_strategy_code(strategy_code)
        runs = self.store.list_backtest_runs(strategy_code=code, limit=80)
        valid_runs: List[Dict[str, Any]] = []
        for item in runs:
            result = item.get("result") or {}
            metrics = result.get("metrics") or {}
            if not metrics:
                continue
            valid_runs.append(result)

        def _compact_config(config: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "holding_days": config.get("holding_days"),
                "score_threshold": config.get("score_threshold"),
                "stop_profit_pct": config.get("stop_profit_pct"),
                "stop_loss_pct": config.get("stop_loss_pct"),
                "max_positions": config.get("max_positions"),
                "universe_size": config.get("universe_size"),
                "commission": config.get("commission"),
                "slippage": config.get("slippage"),
                "test_start": config.get("test_start"),
                "test_end": config.get("test_end"),
            }

        def _evidence_hash(run: Dict[str, Any]) -> str:
            payload = {
                "run_id": run.get("run_id"),
                "strategy_code": run.get("strategy_code"),
                "config": _compact_config(run.get("config") or {}),
                "diagnostics": run.get("diagnostics") or {},
                "metrics": run.get("metrics") or {},
            }
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

        def _summarize_run(run: Dict[str, Any], include_samples: bool = True) -> Dict[str, Any]:
            metrics = run.get("metrics") or {}
            diagnostics = run.get("diagnostics") or {}
            credibility = run.get("credibility") or {}
            config = run.get("config") or {}
            trade_rows = run.get("trades") or []
            roundtrips = run.get("closed_roundtrips") or []
            closed_count = int(diagnostics.get("closed_roundtrips") or len(roundtrips) or 0)
            summary = {
                "run_id": run.get("run_id"),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "status": run.get("status"),
                "backtest_engine": run.get("backtest_engine") or "historical_replay_v1",
                "metrics": metrics,
                "diagnostics": diagnostics,
                "evidence_hash": _evidence_hash(run),
                "has_closed_trades": closed_count > 0,
                "credibility": {
                    "score": credibility.get("score"),
                    "grade": credibility.get("grade"),
                    "live_ready": bool(credibility.get("live_ready")),
                    "summary": credibility.get("summary"),
                    "failed_checks": (credibility.get("failed_checks") or [])[:5],
                    "gate_checks": (credibility.get("gate_checks") or [])[:8],
                },
                "config": _compact_config(config),
                "sample_summary": {
                    "trade_count": int(diagnostics.get("trade_count") or 0),
                    "closed_roundtrips": closed_count,
                    "valid_history_symbols": int(diagnostics.get("valid_history_symbols") or 0),
                    "universe_size": int(diagnostics.get("universe_size") or config.get("universe_size") or 0),
                    "calendar_days": int(diagnostics.get("calendar_days") or 0),
                    "avg_holding_days": self._safe_float(diagnostics.get("avg_holding_days"), 0.0),
                    "avg_return_pct": self._safe_float(diagnostics.get("avg_return_pct"), 0.0),
                },
            }
            if include_samples:
                summary.update(
                    {
                        "recent_trades": trade_rows[-12:],
                        "recent_roundtrips": roundtrips[-12:],
                        "drawdown_curve": (run.get("drawdown_curve") or [])[-120:],
                        "equity_curve": (run.get("equity_curve") or [])[-120:],
                    }
                )
            return summary

        execution_assumptions = {
            "engine": "historical_replay_v1",
            "scope": "strategy_level",
            "buy_execution": "信号生成后的下一交易日开盘价买入，并计入滑点。",
            "sell_execution": "触发止盈、止损、持有期或评分退出后，按当日收盘价近似卖出，并计入滑点。",
            "cost_model": "回测使用配置中的 commission 和 slippage。",
            "money_flow_caveat": "历史回放中的资金流因子包含量价代理，不等同于逐日真实主力资金流。",
        }

        if not valid_runs:
            return {
                "strategy_code": code,
                "version_no": "derived-from-backtest",
                "evidence_source": {
                    "type": "unavailable",
                    "label": "暂无有效历史回放证据",
                    "display_scope": "unavailable",
                    "is_verifiable": False,
                },
                "unavailable": True,
                "proxy_model": None,
                "display_run": None,
                "latest_run": None,
                "verification_target": {
                    "type": "run_new_backtest",
                    "path": f"/backtest?strategy_code={code}",
                },
                "execution_assumptions": execution_assumptions,
                "sample_summary": {
                    "sample_runs": 0,
                    "closed_roundtrips": 0,
                    "valid_history_symbols": 0,
                    "calendar_days": 0,
                },
                "credibility_summary": {
                    "score": None,
                    "grade": None,
                    "live_ready": False,
                    "summary": "暂无可验证回测证据。",
                    "failed_checks": ["暂无历史回放记录"],
                    "gate_checks": [],
                },
                "overall": {
                    "annual_return": 0.0,
                    "max_drawdown": 0.0,
                    "sharpe": 0.0,
                    "win_rate": 0.0,
                    "profit_loss_ratio": 0.0,
                    "sample_runs": 0,
                    "closed_roundtrips": 0,
                    "avg_return_pct": 0.0,
                },
                "by_state": [
                    {"state_tag": "offensive", "win_rate": 0.0, "max_drawdown": 0.0, "sample_count": 0},
                    {"state_tag": "neutral", "win_rate": 0.0, "max_drawdown": 0.0, "sample_count": 0},
                    {"state_tag": "defensive", "win_rate": 0.0, "max_drawdown": 0.0, "sample_count": 0},
                ],
                "active_state": default_state,
                "notes": [
                    "暂无该策略的真实回测记录，当前不能给出可信度结论。",
                    "请先运行至少10次滚动回测（覆盖不同市场状态）再查看策略证据。",
                ],
            }

        weighted = {"annual_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "win_rate": 0.0, "profit_loss_ratio": 0.0}
        weighted_diagnostics = {"avg_return_pct": 0.0}
        total_weight = 0.0
        state_bucket: Dict[str, Dict[str, float]] = {
            "offensive": {"win_sum": 0.0, "dd_sum": 0.0, "weight": 0.0, "sample_count": 0.0},
            "neutral": {"win_sum": 0.0, "dd_sum": 0.0, "weight": 0.0, "sample_count": 0.0},
            "defensive": {"win_sum": 0.0, "dd_sum": 0.0, "weight": 0.0, "sample_count": 0.0},
        }
        total_closed_roundtrips = 0
        latest_credibility = (valid_runs[0].get("credibility") or {}) if valid_runs else {}
        for run in valid_runs:
            metrics = run.get("metrics") or {}
            diagnostics = run.get("diagnostics") or {}
            run_weight = max(1.0, float(diagnostics.get("closed_roundtrips") or 0))
            total_weight += run_weight
            total_closed_roundtrips += int(diagnostics.get("closed_roundtrips") or 0)
            for key in weighted.keys():
                weighted[key] += self._safe_float(metrics.get(key), 0.0) * run_weight
            weighted_diagnostics["avg_return_pct"] += self._safe_float(diagnostics.get("avg_return_pct"), 0.0) * run_weight

            for item in (run.get("by_state") or []):
                tag = str(item.get("state_tag") or "")
                if tag not in state_bucket:
                    continue
                w = max(1.0, self._safe_float(item.get("sample_count"), 0))
                state_bucket[tag]["win_sum"] += self._safe_float(item.get("win_rate"), 0.0) * w
                state_bucket[tag]["dd_sum"] += self._safe_float(item.get("max_drawdown"), 0.0) * w
                state_bucket[tag]["weight"] += w
                state_bucket[tag]["sample_count"] += self._safe_float(item.get("sample_count"), 0.0)

        if total_weight <= 0:
            total_weight = 1.0
        overall = {
            "annual_return": round(weighted["annual_return"] / total_weight, 6),
            "max_drawdown": round(weighted["max_drawdown"] / total_weight, 6),
            "sharpe": round(weighted["sharpe"] / total_weight, 6),
            "win_rate": round(weighted["win_rate"] / total_weight, 6),
            "profit_loss_ratio": round(weighted["profit_loss_ratio"] / total_weight, 6),
            "sample_runs": len(valid_runs),
            "closed_roundtrips": total_closed_roundtrips,
            "avg_return_pct": round(weighted_diagnostics["avg_return_pct"] / total_weight, 6),
        }

        by_state = []
        for tag in ["offensive", "neutral", "defensive"]:
            bucket = state_bucket[tag]
            weight = bucket.get("weight", 0.0)
            by_state.append(
                {
                    "state_tag": tag,
                    "win_rate": round((bucket["win_sum"] / weight), 6) if weight > 0 else 0.0,
                    "max_drawdown": round((bucket["dd_sum"] / weight), 6) if weight > 0 else 0.0,
                    "sample_count": int(bucket.get("sample_count", 0) or 0),
                }
            )

        credibility_score = self._safe_float(latest_credibility.get("score"), 0.0)
        live_ready = bool(latest_credibility.get("live_ready"))
        notes = [
            f"证据来源：最近 {len(valid_runs)} 次真实历史回放（闭环交易合计 {total_closed_roundtrips} 笔）。",
            "已包含手续费与滑点模拟；买入按次日开盘成交，卖出按当日收盘近似成交。",
            "资金流因子在历史回放中含代理成分（基于量价构造），不应等同于逐日真实主力资金。",
        ]
        if credibility_score > 0:
            notes.append(
                f"最新回测可信度评分 {credibility_score:.1f}/100，实盘准入状态：{'通过' if live_ready else '未通过'}。"
            )

        latest_run = valid_runs[0] if valid_runs else {}
        display_run = next(
            (
                run for run in valid_runs
                if int((run.get("diagnostics") or {}).get("closed_roundtrips") or len(run.get("closed_roundtrips") or []) or 0) > 0
            ),
            None,
        )
        latest_summary = _summarize_run(latest_run) if latest_run else None
        display_summary = _summarize_run(display_run) if display_run else None
        display_scope = "display_run" if display_summary else "overall"
        source_label = "最近一次有闭环交易的历史回放" if display_summary else "多次历史回放总体聚合证据"
        source_type = "historical_replay_run" if display_summary else "aggregate_backtest_evidence"
        credibility_source = (display_summary or latest_summary or {}).get("credibility") or {}
        sample_source = (display_summary or {}).get("sample_summary") or {}
        verification_run_id = (display_summary or {}).get("run_id")
        verification_path = (
            f"/backtest?strategy_code={code}&run_id={verification_run_id}"
            if verification_run_id
            else f"/backtest?strategy_code={code}"
        )

        return {
            "strategy_code": code,
            "version_no": "derived-from-backtest",
            "evidence_source": {
                "type": source_type,
                "label": source_label,
                "display_scope": display_scope,
                "is_verifiable": True,
                "run_id": verification_run_id,
            },
            "unavailable": False,
            "proxy_model": None,
            "verification_target": {
                "type": "backtest_run" if verification_run_id else "strategy_evidence",
                "run_id": verification_run_id,
                "path": verification_path,
            },
            "execution_assumptions": execution_assumptions,
            "sample_summary": {
                "sample_runs": len(valid_runs),
                "closed_roundtrips": total_closed_roundtrips,
                "display_closed_roundtrips": int(sample_source.get("closed_roundtrips") or 0),
                "valid_history_symbols": int(sample_source.get("valid_history_symbols") or 0),
                "universe_size": int(sample_source.get("universe_size") or 0),
                "calendar_days": int(sample_source.get("calendar_days") or 0),
                "avg_holding_days": sample_source.get("avg_holding_days"),
                "avg_return_pct": overall.get("avg_return_pct"),
            },
            "credibility_summary": {
                "score": credibility_source.get("score"),
                "grade": credibility_source.get("grade"),
                "live_ready": bool(credibility_source.get("live_ready")),
                "summary": credibility_source.get("summary"),
                "failed_checks": credibility_source.get("failed_checks") or [],
                "gate_checks": credibility_source.get("gate_checks") or [],
            },
            "overall": overall,
            "by_state": by_state,
            "active_state": default_state,
            "display_run": display_summary,
            "latest_run": latest_summary,
            "recent_runs": [_summarize_run(run, include_samples=False) for run in valid_runs[:12]],
            "notes": notes,
        }

    def record_pick_action(self, user_id: str, pick_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        action_type = (payload.get("action_type") or "").strip()
        if action_type not in {"added_watchlist", "paper_buy", "ignored", "closed"}:
            raise ValueError(f"不支持的动作类型: {action_type}")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pick = self._find_pick_by_id(pick_id)
        symbol = (
            payload.get("symbol")
            or (pick.get("symbol") if pick else None)
            or self._extract_symbol_from_pick_id(pick_id)
        )
        if not symbol:
            raise ValueError("无法识别股票代码，请检查 pick_id")
        name = (pick or {}).get("name", symbol)

        action_price = payload.get("action_price")
        if action_price is None:
            if pick and pick.get("entry_range"):
                action_price = pick["entry_range"][1] or pick["entry_range"][0]
            if action_price is None:
                quote = self.data_source_manager.get_realtime_quote(symbol)
                action_price = (quote or {}).get("price")

        record = {
            "user_id": user_id,
            "pick_id": pick_id,
            "symbol": symbol,
            "action_type": action_type,
            "action_price": float(action_price) if action_price not in {None, ""} else None,
            "action_qty": float(payload.get("action_qty")) if payload.get("action_qty") not in {None, ""} else None,
            "note": payload.get("note"),
            "created_at": now_str,
        }
        saved = self.store.append_pick_action(record)

        position_result = None
        if action_type == "paper_buy":
            qty = record["action_qty"] if record["action_qty"] and record["action_qty"] > 0 else 100.0
            if record["action_price"] is None or record["action_price"] <= 0:
                raise ValueError("模拟买入失败：无法获取有效买入价格")
            position_result = self.store.open_or_add_position(
                user_id=user_id,
                symbol=symbol,
                name=name,
                pick_id=pick_id,
                price=float(record["action_price"]),
                qty=float(qty),
                created_at=now_str,
                reason=record.get("note") or "paper buy from smart screen",
            )
        elif action_type == "closed":
            close_price = record["action_price"]
            if close_price is None or close_price <= 0:
                quote = self.data_source_manager.get_realtime_quote(symbol)
                close_price = float((quote or {}).get("price") or 0)
            close_qty = record["action_qty"]
            position_result = self.store.close_position(
                user_id=user_id,
                symbol=symbol,
                close_price=float(close_price),
                close_qty=float(close_qty) if close_qty else None,
                created_at=now_str,
                reason=record.get("note") or "manual close",
            )

        if action_type == "ignored":
            self._invalidate_user_cache(user_id)
        result = dict(saved)
        result["position_result"] = position_result
        return result

    def get_watchlist(self, user_id: str = "default") -> Dict[str, Any]:
        latest_map = self._get_latest_action_map(user_id)
        items: List[Dict[str, Any]] = []
        by_symbol: Dict[str, Dict[str, Any]] = {}
        fast_name_map: Dict[str, str] = {}
        try:
            for trade in self.store.list_paper_trades(user_id=user_id, limit=500):
                if trade.get("symbol") and trade.get("name"):
                    fast_name_map[str(trade["symbol"])] = str(trade["name"])
            cached_snapshot = self.data_source_manager._get_cache("market:a_share_snapshot") or []
            for row in cached_snapshot:
                if row.get("symbol") and row.get("name"):
                    fast_name_map.setdefault(str(row["symbol"]), str(row["name"]))
        except Exception:
            fast_name_map = {}

        for pick_id, action in latest_map.items():
            symbol = action.get("symbol") or self._extract_symbol_from_pick_id(pick_id)
            if not symbol:
                continue

            existing = by_symbol.get(symbol)
            if existing and existing.get("created_at", "") >= action.get("created_at", ""):
                continue
            by_symbol[symbol] = {"pick_id": pick_id, "action": action}

        for symbol, row in by_symbol.items():
            pick_id = row["pick_id"]
            action = row["action"]
            action_type = action.get("action_type")
            if action_type not in {"added_watchlist", "paper_buy"}:
                continue
            snap = {}
            try:
                snap_row = self.store.get_pick_snapshot(pick_id, user_id=user_id) or self.store.get_latest_pick_snapshot_by_symbol(symbol, user_id=user_id)
                snap = (snap_row or {}).get("snapshot") or {}
            except Exception:
                snap = {}

            items.append(
                {
                    "pick_id": pick_id,
                    "symbol": symbol,
                    "name": snap.get("name") or fast_name_map.get(symbol, symbol),
                    "action_type": action_type,
                    "action_price": action.get("action_price"),
                    "action_qty": action.get("action_qty"),
                    "created_at": action.get("created_at"),
                    "score": (snap.get("score_breakdown") or {}).get("total"),
                    "up_prob": snap.get("up_prob"),
                    "dd_prob": snap.get("dd_prob"),
                    "entry_range": snap.get("entry_range"),
                    "decision": snap.get("decision"),
                    "probability_model": snap.get("probability_model"),
                    "reasons": snap.get("reasons"),
                    "risks": snap.get("risks"),
                    "position_qty": None,
                    "avg_price": None,
                    "current_price": None,
                    "market_value": None,
                    "unrealized_pnl": None,
                    "unrealized_pnl_pct": None,
                    "stop_loss": None,
                    "take_profit": None,
                    "risk_status": None,
                    "risk_message": None,
                }
            )

        portfolio = self.get_paper_portfolio(user_id=user_id, refresh_quotes=False)
        position_rows = {row["symbol"]: row for row in portfolio.get("positions", [])}
        merged: List[Dict[str, Any]] = []
        seen = set()
        for item in items:
            symbol = item.get("symbol")
            if symbol in position_rows:
                pos = position_rows[symbol]
                item["action_type"] = "paper_buy"
                item["name"] = pos.get("name") or item.get("name") or symbol
                item["position_qty"] = pos.get("qty")
                item["avg_price"] = pos.get("avg_price")
                item["current_price"] = pos.get("current_price")
                item["market_value"] = pos.get("market_value")
                item["unrealized_pnl"] = pos.get("unrealized_pnl")
                item["unrealized_pnl_pct"] = pos.get("unrealized_pnl_pct")
                item["stop_loss"] = pos.get("stop_loss")
                item["take_profit"] = pos.get("take_profit")
                item["risk_status"] = pos.get("risk_status")
                item["risk_message"] = pos.get("risk_message")
            merged.append(item)
            seen.add(symbol)

        for symbol, pos in position_rows.items():
            if symbol in seen:
                continue
            snap = {}
            try:
                snap_row = self.store.get_latest_pick_snapshot_by_symbol(symbol, user_id=user_id)
                snap = (snap_row or {}).get("snapshot") or {}
            except Exception:
                snap = {}
            merged.append(
                {
                    "pick_id": pos.get("pick_id") or snap.get("pick_id") or f"paper-{symbol}",
                    "symbol": symbol,
                    "name": pos.get("name") or snap.get("name") or fast_name_map.get(symbol, symbol),
                    "action_type": "paper_buy",
                    "action_price": pos.get("avg_price"),
                    "action_qty": pos.get("qty"),
                    "created_at": pos.get("updated_at"),
                    "score": (snap.get("score_breakdown") or {}).get("total"),
                    "up_prob": snap.get("up_prob"),
                    "dd_prob": snap.get("dd_prob"),
                    "entry_range": snap.get("entry_range"),
                    "decision": snap.get("decision"),
                    "probability_model": snap.get("probability_model"),
                    "reasons": snap.get("reasons"),
                    "risks": snap.get("risks"),
                    "position_qty": pos.get("qty"),
                    "avg_price": pos.get("avg_price"),
                    "current_price": pos.get("current_price"),
                    "market_value": pos.get("market_value"),
                    "unrealized_pnl": pos.get("unrealized_pnl"),
                    "unrealized_pnl_pct": pos.get("unrealized_pnl_pct"),
                    "stop_loss": pos.get("stop_loss"),
                    "take_profit": pos.get("take_profit"),
                    "risk_status": pos.get("risk_status"),
                    "risk_message": pos.get("risk_message"),
                }
            )

        items = merged
        for item in items:
            if item.get("score") is None:
                item["score"] = None

        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"items": items, "portfolio_summary": portfolio.get("summary", {})}

    def get_paper_portfolio(self, user_id: str = "default", refresh_quotes: bool = True) -> Dict[str, Any]:
        rows = self.store.list_open_positions(user_id=user_id)
        latest_actions = self.store.list_pick_actions(user_id=user_id, limit=500)
        latest_action_by_symbol: Dict[str, Dict[str, Any]] = {}
        for action in latest_actions:
            symbol = action.get("symbol") or self._extract_symbol_from_pick_id(action.get("pick_id") or "")
            if not symbol:
                continue
            if symbol not in latest_action_by_symbol:
                latest_action_by_symbol[symbol] = action

        total_cost = 0.0
        total_market_value = 0.0
        total_unrealized = 0.0
        positions: List[Dict[str, Any]] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        symbols = [str(row.get("symbol") or "") for row in rows if row.get("symbol")]
        quote_map = self.data_source_manager.get_realtime_quotes_batch(symbols) if symbols and refresh_quotes else {}
        active_strategy = self.get_active_strategy_config(user_id=user_id)
        active_config = active_strategy.get("config") or {}
        default_stop_loss_ratio = self._clamp(self._safe_float(active_config.get("stop_loss_pct"), 8), 2, 25) / 100.0
        default_take_profit_ratio = self._clamp(self._safe_float(active_config.get("stop_profit_pct"), 15), 5, 40) / 100.0

        for row in rows:
            symbol = row.get("symbol")
            qty = float(row.get("qty") or 0)
            avg_price = float(row.get("avg_price") or 0)
            cost_amount = float(row.get("cost_amount") or (qty * avg_price))

            quote = quote_map.get(symbol) if symbol else None
            if symbol and not quote and refresh_quotes:
                quote = self.data_source_manager.get_realtime_quote(symbol)
            previous_mark = float(row.get("market_value") or 0)
            marked_price = previous_mark / qty if qty > 0 and previous_mark > 0 else 0
            current_price = float((quote or {}).get("price") or marked_price or avg_price or 0)
            name = (quote or {}).get("name") or row.get("name") or symbol

            market_value = round(current_price * qty, 4)
            unrealized = round(market_value - cost_amount, 4)
            unrealized_pct = round((unrealized / cost_amount * 100) if cost_amount > 0 else 0.0, 4)

            if row.get("id"):
                self.store.update_position_mark(
                    position_id=int(row["id"]),
                    market_value=market_value,
                    unrealized_pnl=unrealized,
                    unrealized_pnl_pct=unrealized_pct,
                    updated_at=now_str,
                )

            action_ref = latest_action_by_symbol.get(symbol, {})
            # 自选股列表是高频页面，止损/止盈用持仓均价和当前策略配置快速计算；
            # 避免为历史 pick_id 再触发远程推荐重建或实时查询。
            planned_stop_loss = round(avg_price * (1 - default_stop_loss_ratio), 4) if avg_price > 0 else 0
            planned_take_profit = round(avg_price * (1 + default_take_profit_ratio), 4) if avg_price > 0 else 0
            risk_status = "normal"
            risk_message = "未触发止损/止盈"
            if planned_stop_loss > 0 and current_price <= planned_stop_loss:
                risk_status = "stop_loss"
                risk_message = f"已跌破止损位 {planned_stop_loss:.2f}，应评估平仓纪律"
            elif planned_take_profit > 0 and current_price >= planned_take_profit:
                risk_status = "take_profit"
                risk_message = f"已达到止盈位 {planned_take_profit:.2f}，应评估兑现收益"
            elif unrealized_pct <= -5:
                risk_status = "warning"
                risk_message = "浮亏超过5%，需复核推荐逻辑与持仓理由"
            elif unrealized_pct >= 8:
                risk_status = "profit_watch"
                risk_message = "浮盈较高，需跟踪回撤保护"
            positions.append(
                {
                    "position_id": row.get("id"),
                    "pick_id": action_ref.get("pick_id"),
                    "symbol": symbol,
                    "name": name,
                    "qty": round(qty, 4),
                    "avg_price": round(avg_price, 4),
                    "current_price": round(current_price, 4),
                    "cost_amount": round(cost_amount, 4),
                    "market_value": market_value,
                    "unrealized_pnl": unrealized,
                    "unrealized_pnl_pct": unrealized_pct,
                    "stop_loss": round(planned_stop_loss, 4) if planned_stop_loss > 0 else None,
                    "take_profit": round(planned_take_profit, 4) if planned_take_profit > 0 else None,
                    "risk_status": risk_status,
                    "risk_message": risk_message,
                    "opened_at": row.get("opened_at"),
                    "updated_at": now_str,
                }
            )
            total_cost += cost_amount
            total_market_value += market_value
            total_unrealized += unrealized

        total_pnl_pct = (total_unrealized / total_cost * 100) if total_cost > 0 else 0.0
        positions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return {
            "summary": {
                "position_count": len(positions),
                "total_cost": round(total_cost, 4),
                "total_market_value": round(total_market_value, 4),
                "total_unrealized_pnl": round(total_unrealized, 4),
                "total_unrealized_pnl_pct": round(total_pnl_pct, 4),
            },
            "positions": positions,
            "updated_at": now_str,
        }

    def get_paper_trades(self, user_id: str = "default", limit: int = 200) -> Dict[str, Any]:
        rows = self.store.list_paper_trades(user_id=user_id, limit=limit)
        items = [
            {
                "trade_id": row.get("id"),
                "trade_date": row.get("created_at"),
                "symbol": row.get("symbol"),
                "name": row.get("name") or row.get("symbol"),
                "pick_id": row.get("pick_id"),
                "side": row.get("side"),
                "price": row.get("price"),
                "qty": row.get("qty"),
                "amount": row.get("amount"),
                "reason": row.get("reason"),
            }
            for row in rows
        ]
        return {
            "summary": {
                "total": len(items),
                "buy_count": sum(1 for row in items if row.get("side") == "buy"),
                "sell_count": sum(1 for row in items if row.get("side") == "sell"),
            },
            "items": items,
        }

    def get_paper_review(self, user_id: str = "default") -> Dict[str, Any]:
        """复盘用户根据智能选股产生的观察和模拟交易结果。"""
        watchlist = self.get_watchlist(user_id=user_id)
        items = watchlist.get("items") or []
        portfolio_summary = watchlist.get("portfolio_summary") or {}
        trades = self.store.list_paper_trades(user_id=user_id, limit=500)

        paper_items = [item for item in items if item.get("action_type") == "paper_buy"]
        watch_items = [item for item in items if item.get("action_type") == "added_watchlist"]
        covered_items = [
            item
            for item in items
            if item.get("score") is not None
            or item.get("up_prob") is not None
            or item.get("decision")
        ]
        evaluated_positions = [
            item
            for item in paper_items
            if item.get("unrealized_pnl_pct") is not None and item.get("position_qty")
        ]

        win_count = sum(1 for item in evaluated_positions if float(item.get("unrealized_pnl_pct") or 0) > 0)
        loss_count = sum(1 for item in evaluated_positions if float(item.get("unrealized_pnl_pct") or 0) < 0)
        flat_count = max(0, len(evaluated_positions) - win_count - loss_count)
        avg_unrealized_pct = (
            sum(float(item.get("unrealized_pnl_pct") or 0) for item in evaluated_positions) / len(evaluated_positions)
            if evaluated_positions
            else 0.0
        )

        sell_trades = [row for row in trades if row.get("side") == "sell"]
        buy_trades = [row for row in trades if row.get("side") == "buy"]
        trade_count_by_symbol: Dict[str, int] = {}
        for row in trades:
            symbol = str(row.get("symbol") or "")
            if symbol:
                trade_count_by_symbol[symbol] = trade_count_by_symbol.get(symbol, 0) + 1

        risk_items = [
            item
            for item in paper_items
            if item.get("risk_status") in {"warning", "stop_loss"}
            or float(item.get("unrealized_pnl_pct") or 0) <= -3
        ]
        missing_snapshot_items = [item for item in items if item.get("score") is None and item.get("up_prob") is None]

        review_rows: List[Dict[str, Any]] = []
        for item in sorted(
            paper_items,
            key=lambda row: (
                row.get("risk_status") in {"stop_loss", "warning"},
                abs(float(row.get("unrealized_pnl_pct") or 0)),
            ),
            reverse=True,
        )[:8]:
            pnl_pct = float(item.get("unrealized_pnl_pct") or 0)
            if item.get("risk_status") == "stop_loss":
                verdict = "必须复核"
                suggestion = "已触发止损线，应优先检查是否执行平仓纪律。"
            elif item.get("risk_status") == "warning" or pnl_pct <= -3:
                verdict = "风险复核"
                suggestion = "浮亏扩大，复核推荐理由是否仍成立，避免亏损扩大。"
            elif pnl_pct > 0:
                verdict = "继续跟踪"
                suggestion = "当前模拟收益为正，继续观察是否达到止盈或回撤保护条件。"
            else:
                verdict = "观察中"
                suggestion = "尚未形成明显反馈，等待策略持有周期结束后再评价。"

            review_rows.append(
                {
                    "symbol": item.get("symbol"),
                    "name": item.get("name") or item.get("symbol"),
                    "score": item.get("score"),
                    "decision_grade": (item.get("decision") or {}).get("grade"),
                    "up_prob": item.get("up_prob"),
                    "unrealized_pnl": item.get("unrealized_pnl"),
                    "unrealized_pnl_pct": item.get("unrealized_pnl_pct"),
                    "risk_status": item.get("risk_status") or "normal",
                    "verdict": verdict,
                    "suggestion": suggestion,
                    "trade_count": trade_count_by_symbol.get(str(item.get("symbol") or ""), 0),
                }
            )

        reviewed_count = len(evaluated_positions)
        win_rate = round(win_count / reviewed_count, 4) if reviewed_count else 0.0
        snapshot_coverage = round(len(covered_items) / len(items), 4) if items else 0.0

        if reviewed_count <= 0:
            summary = "当前没有可评价的模拟持仓，建议先用智能选股进行模拟买入，再用复盘结果校验策略。"
        elif win_rate >= 0.55 and avg_unrealized_pct > 0:
            summary = "模拟持仓整体反馈偏正，但仍需继续累计样本，不建议直接放大到实盘。"
        elif avg_unrealized_pct < 0:
            summary = "模拟持仓当前平均收益为负，应降低该策略信任度，并优先复核亏损票的入选理由。"
        else:
            summary = "模拟反馈暂时中性，样本仍不足，应继续观察完整持有周期后的胜率和回撤。"

        return {
            "summary": summary,
            "review_status": "insufficient_sample" if reviewed_count < 10 else "tracking",
            "metrics": {
                "tracked_count": len(items),
                "watch_count": len(watch_items),
                "paper_position_count": len(paper_items),
                "open_position_count": int(portfolio_summary.get("position_count") or 0),
                "snapshot_covered_count": len(covered_items),
                "snapshot_coverage": snapshot_coverage,
                "reviewed_position_count": reviewed_count,
                "open_win_rate": win_rate,
                "win_count": win_count,
                "loss_count": loss_count,
                "flat_count": flat_count,
                "avg_unrealized_pnl_pct": round(avg_unrealized_pct, 4),
                "total_unrealized_pnl": portfolio_summary.get("total_unrealized_pnl") or 0,
                "total_unrealized_pnl_pct": portfolio_summary.get("total_unrealized_pnl_pct") or 0,
                "risk_flag_count": len(risk_items),
                "missing_snapshot_count": len(missing_snapshot_items),
                "buy_trade_count": len(buy_trades),
                "sell_trade_count": len(sell_trades),
            },
            "items": review_rows,
            "warnings": [
                "复盘仅基于当前模拟交易和推荐快照，不代表实盘可用性。",
                "胜率样本低于10笔时，只能作为策略早期反馈，不能作为最终结论。",
            ],
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _build_monitor_path(
        self,
        symbol: str,
        entry_price: float,
        selected_at: Optional[str],
        current_price: float,
    ) -> Dict[str, Any]:
        entry_price = self._safe_float(entry_price, 0)
        current_price = self._safe_float(current_price, 0)
        if entry_price <= 0:
            return {
                "points": [],
                "current_return_pct": 0.0,
                "max_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "data_quality": "unavailable",
            }

        selected_dt = self._parse_trade_time(selected_at) or datetime.now()
        days = max(30, min(240, (datetime.now() - selected_dt).days + 10))
        points: List[Dict[str, Any]] = []
        try:
            history = self.data_source_manager.get_history_data(symbol, days=days)
        except Exception:
            history = pd.DataFrame()

        if history is not None and not history.empty:
            selected_key = selected_dt.strftime("%Y%m%d")
            for _, row in history.iterrows():
                date_text = str(row.get("date") or row.get("trade_date") or "")
                date_key = date_text.replace("-", "")[:8]
                if len(date_key) == 8 and date_key < selected_key:
                    continue
                close_price = self._safe_float(row.get("close"), 0)
                if close_price <= 0:
                    continue
                points.append(
                    {
                        "date": f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}" if len(date_key) == 8 else date_text,
                        "price": round(close_price, 4),
                        "return_pct": round((close_price / entry_price - 1) * 100, 4),
                    }
                )

        today = datetime.now().strftime("%Y-%m-%d")
        if current_price > 0 and (not points or points[-1].get("date") != today):
            points.append(
                {
                    "date": today,
                    "price": round(current_price, 4),
                    "return_pct": round((current_price / entry_price - 1) * 100, 4),
                }
            )

        if not points:
            points.append(
                {
                    "date": today,
                    "price": round(current_price or entry_price, 4),
                    "return_pct": round(((current_price or entry_price) / entry_price - 1) * 100, 4),
                }
            )

        peak_price = entry_price
        max_drawdown = 0.0
        max_return = -999.0
        for point in points:
            price = self._safe_float(point.get("price"), entry_price)
            peak_price = max(peak_price, price)
            drawdown = (price / peak_price - 1) * 100 if peak_price > 0 else 0.0
            max_drawdown = min(max_drawdown, drawdown)
            max_return = max(max_return, self._safe_float(point.get("return_pct"), 0))

        return {
            "points": points[-80:],
            "current_return_pct": round((self._safe_float(points[-1].get("price"), entry_price) / entry_price - 1) * 100, 4),
            "max_return_pct": round(max(max_return, 0.0), 4),
            "max_drawdown_pct": round(abs(max_drawdown), 4),
            "data_quality": "history" if len(points) > 1 else "mark_only",
        }

    def _monitor_conclusion(
        self,
        track_type: str,
        metrics: Dict[str, Any],
        risk_status: Optional[str],
        score: Optional[float],
        money_flow_quality: str,
    ) -> Dict[str, Any]:
        ret = self._safe_float(metrics.get("current_return_pct"), 0)
        max_dd = self._safe_float(metrics.get("max_drawdown_pct"), 0)
        holding_days = int(self._safe_float(metrics.get("holding_days"), 0))

        if track_type == "paper_position":
            if risk_status == "stop_loss":
                status, action = "suggest_exit", "建议退出"
                reason = "已触发止损规则，应优先执行交易纪律。"
            elif risk_status in {"warning"} or ret <= -3 or max_dd >= 8:
                status, action = "risk_review", "风险复核"
                reason = "浮亏或回撤进入警戒区，需复核入选逻辑是否仍成立。"
            elif risk_status == "take_profit" or ret >= 10:
                status, action = "risk_review", "止盈/保护利润"
                reason = "收益达到较高区间，应评估分批止盈或移动止损。"
            else:
                status, action = "continue_hold", "继续持有"
                reason = "收益和回撤仍在策略容忍范围内。"
        else:
            if ret >= 8:
                status, action = "missed_opportunity", "错过机会"
                reason = "观察后涨幅已明显兑现，说明策略可能过严或执行犹豫。"
            elif ret <= -5 or max_dd >= 8:
                status, action = "validation_failed", "验证失败"
                reason = "观察后走势走弱，暂不应升级为买入。"
            else:
                status, action = "waiting_trigger", "等待触发"
                reason = "尚未形成明确后验结果，继续等待入场或失效信号。"

        flags = []
        if score is None:
            flags.append("缺少推荐快照")
        elif self._safe_float(score, 0) < 70:
            flags.append("入选分数偏低")
        if money_flow_quality == "unavailable":
            flags.append("资金流不可用")
        if holding_days >= 20 and track_type == "paper_position":
            flags.append("持有周期偏长")

        return {
            "status": status,
            "label": action,
            "reason": reason,
            "flags": flags,
        }

    def get_monitor_positions(self, user_id: str = "default", persist: bool = False) -> Dict[str, Any]:
        watchlist = self.get_watchlist(user_id=user_id)
        portfolio = self.get_paper_portfolio(user_id=user_id, refresh_quotes=True)
        position_map = {row.get("symbol"): row for row in portfolio.get("positions", [])}
        items = watchlist.get("items") or []
        symbols = [str(item.get("symbol") or "") for item in items if item.get("symbol")]
        quote_map = self.data_source_manager.get_realtime_quotes_batch(list(dict.fromkeys(symbols))) if symbols else {}

        rows: List[Dict[str, Any]] = []
        for item in items:
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            pos = position_map.get(symbol)
            track_type = "paper_position" if pos or item.get("action_type") == "paper_buy" else "watch_only"
            quote = quote_map.get(symbol) or {}
            current_price = self._safe_float(
                (pos or {}).get("current_price")
                or item.get("current_price")
                or quote.get("price")
                or item.get("action_price"),
                0,
            )
            entry_range = item.get("entry_range") or []
            entry_price = self._safe_float(
                (pos or {}).get("avg_price")
                or item.get("action_price")
                or (entry_range[0] if isinstance(entry_range, list) and entry_range else None)
                or current_price,
                0,
            )
            selected_at = item.get("created_at") or (pos or {}).get("opened_at")
            selected_dt = self._parse_trade_time(selected_at) or datetime.now()
            holding_days = max((datetime.now() - selected_dt).days, 0)
            path = self._build_monitor_path(symbol, entry_price, selected_at, current_price)

            snap_row = {}
            try:
                snap_row = self.store.get_pick_snapshot(item.get("pick_id") or "", user_id=user_id) or {}
            except Exception:
                snap_row = {}
            snap = snap_row.get("snapshot") or {}
            score = item.get("score")
            if score is None:
                score = (snap.get("score_breakdown") or {}).get("total")
            money_flow_quality = (
                item.get("money_flow_quality")
                or snap.get("money_flow_quality")
                or ((snap.get("money_flow") or {}).get("quality"))
                or "unavailable"
            )
            risk_status = (pos or {}).get("risk_status") or item.get("risk_status")
            metrics = {
                "entry_price": round(entry_price, 4) if entry_price else None,
                "current_price": round(current_price, 4) if current_price else None,
                "current_return_pct": path.get("current_return_pct"),
                "max_return_pct": path.get("max_return_pct"),
                "max_drawdown_pct": path.get("max_drawdown_pct"),
                "holding_days": holding_days,
                "qty": (pos or {}).get("qty") or item.get("position_qty"),
                "market_value": (pos or {}).get("market_value") or item.get("market_value"),
                "unrealized_pnl": (pos or {}).get("unrealized_pnl") or item.get("unrealized_pnl"),
                "distance_to_stop_loss_pct": None,
                "distance_to_take_profit_pct": None,
            }
            if current_price > 0 and (pos or {}).get("stop_loss"):
                metrics["distance_to_stop_loss_pct"] = round((current_price / self._safe_float(pos.get("stop_loss"), current_price) - 1) * 100, 4)
            if current_price > 0 and (pos or {}).get("take_profit"):
                metrics["distance_to_take_profit_pct"] = round((self._safe_float(pos.get("take_profit"), current_price) / current_price - 1) * 100, 4)

            conclusion = self._monitor_conclusion(
                track_type=track_type,
                metrics=metrics,
                risk_status=risk_status,
                score=score,
                money_flow_quality=str(money_flow_quality),
            )
            data_quality = {
                "price": "real_or_cached" if current_price > 0 else "unavailable",
                "history": path.get("data_quality"),
                "money_flow": money_flow_quality,
                "snapshot": "available" if snap else "missing",
            }
            rows.append(
                {
                    "pick_id": item.get("pick_id"),
                    "symbol": symbol,
                    "name": item.get("name") or (pos or {}).get("name") or symbol,
                    "track_type": track_type,
                    "selected_at": selected_at,
                    "score": score,
                    "decision_grade": ((item.get("decision") or {}).get("grade") or (snap.get("decision") or {}).get("grade")),
                    "up_prob": item.get("up_prob") if item.get("up_prob") is not None else snap.get("up_prob"),
                    "dd_prob": item.get("dd_prob") if item.get("dd_prob") is not None else snap.get("dd_prob"),
                    "stop_loss": (pos or {}).get("stop_loss") or item.get("stop_loss"),
                    "take_profit": (pos or {}).get("take_profit") or item.get("take_profit"),
                    "risk_status": risk_status or "normal",
                    "risk_message": (pos or {}).get("risk_message") or item.get("risk_message"),
                    "theme_tags": item.get("theme_tags") or snap.get("theme_tags") or [],
                    "money_flow_quality": money_flow_quality,
                    "metrics": metrics,
                    "path": path.get("points", []),
                    "conclusion": conclusion,
                    "data_quality": data_quality,
                }
            )

        rows.sort(
            key=lambda row: (
                row.get("conclusion", {}).get("status") in {"suggest_exit", "risk_review", "missed_opportunity"},
                abs(self._safe_float(row.get("metrics", {}).get("current_return_pct"), 0)),
            ),
            reverse=True,
        )
        snapshot_date = datetime.now().strftime("%Y-%m-%d")
        if persist:
            self.store.save_monitor_snapshots(user_id=user_id, snapshot_date=snapshot_date, snapshots=rows)
        return {"items": rows, "snapshot_date": snapshot_date, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    def _build_monitor_feedback(self, user_id: str, positions_payload: Dict[str, Any]) -> Dict[str, Any]:
        items = positions_payload.get("items") or []
        paper_items = [item for item in items if item.get("track_type") == "paper_position"]
        watch_items = [item for item in items if item.get("track_type") == "watch_only"]
        returns = [self._safe_float(item.get("metrics", {}).get("current_return_pct"), 0) for item in paper_items]
        watch_returns = [self._safe_float(item.get("metrics", {}).get("current_return_pct"), 0) for item in watch_items]
        risk_items = [item for item in items if item.get("conclusion", {}).get("status") in {"suggest_exit", "risk_review"}]
        missed_items = [item for item in items if item.get("conclusion", {}).get("status") == "missed_opportunity"]
        money_unavailable = [item for item in items if item.get("money_flow_quality") == "unavailable"]
        max_drawdown = max([self._safe_float(item.get("metrics", {}).get("max_drawdown_pct"), 0) for item in items] or [0])
        win_rate = (sum(1 for r in returns if r > 0) / len(returns)) if returns else 0.0
        avg_return = mean(returns) if returns else 0.0
        avg_watch_return = mean(watch_returns) if watch_returns else 0.0

        diagnostics = self._build_trade_diagnostics(self.get_paper_trades(user_id=user_id, limit=500).get("items") or [])
        closed_roundtrips = int(diagnostics.get("closed_roundtrips") or 0)

        suggestions: List[Dict[str, Any]] = []
        if len(paper_items) + closed_roundtrips < 10:
            suggestions.append(
                {
                    "id": "expand_monitor_sample",
                    "priority": "high",
                    "title": "先扩大模拟样本，不自动改策略参数",
                    "reason": f"当前可评价样本 {len(paper_items) + closed_roundtrips} 笔，未达到稳定复盘门槛。",
                    "impact": "避免用少量样本过拟合策略。",
                }
            )
        if returns and avg_return < 0:
            suggestions.append(
                {
                    "id": "raise_entry_quality",
                    "priority": "high",
                    "title": "提高买入阈值或减少弱信号执行",
                    "reason": f"当前模拟持仓平均收益 {avg_return:.2f}% 为负。",
                    "impact": "降低交易频率，优先保留高置信候选。",
                }
            )
        if max_drawdown >= 8:
            suggestions.append(
                {
                    "id": "tighten_risk_control",
                    "priority": "high",
                    "title": "收紧止损和单票仓位",
                    "reason": f"监控样本最大回撤 {max_drawdown:.2f}% 已进入警戒区。",
                    "impact": "优先控制组合回撤，再追求收益扩张。",
                }
            )
        if len(missed_items) >= 2 or avg_watch_return >= 6:
            suggestions.append(
                {
                    "id": "review_watch_to_buy_gate",
                    "priority": "medium",
                    "title": "复核观察股升级买入的触发条件",
                    "reason": f"观察池出现 {len(missed_items)} 只明显上涨样本，可能存在执行过严或信号滞后。",
                    "impact": "减少强势票只观察不执行的机会成本。",
                }
            )
        if items and len(money_unavailable) / len(items) >= 0.3:
            suggestions.append(
                {
                    "id": "degrade_money_flow_weight",
                    "priority": "medium",
                    "title": "资金流不可用时降低资金因子权重",
                    "reason": f"资金流不可用样本占比 {len(money_unavailable) / len(items) * 100:.1f}%。",
                    "impact": "避免不可用数据污染总评分和复盘结论。",
                }
            )
        if not suggestions:
            suggestions.append(
                {
                    "id": "keep_and_monitor",
                    "priority": "low",
                    "title": "当前无需调整，继续按日复盘",
                    "reason": "收益、回撤和风险提醒暂未触发参数调整条件。",
                    "impact": "保持策略稳定，避免频繁漂移。",
                }
            )

        strategy_health = self._clamp(
            55 + win_rate * 25 + max(avg_return, -10) * 1.2 - max_drawdown * 1.4 - len(risk_items) * 4,
            0,
            100,
        )
        if not items:
            headline = "暂无已选股票，无法形成监控反馈"
        elif risk_items:
            headline = f"今日有 {len(risk_items)} 个风险样本需要处理"
        elif avg_return > 0:
            headline = "已选股票整体反馈偏正，继续按规则跟踪"
        else:
            headline = "已选股票反馈偏弱，优先控制新开仓"

        summary = {
            "headline": headline,
            "review_status": "insufficient_sample" if len(paper_items) + closed_roundtrips < 10 else "tracking",
            "strategy_health_score": round(strategy_health, 2),
            "tracked_count": len(items),
            "paper_position_count": len(paper_items),
            "watch_count": len(watch_items),
            "open_win_rate": round(win_rate, 4),
            "avg_return_pct": round(avg_return, 4),
            "avg_watch_return_pct": round(avg_watch_return, 4),
            "max_drawdown_pct": round(max_drawdown, 4),
            "risk_flag_count": len(risk_items),
            "missed_opportunity_count": len(missed_items),
            "money_flow_unavailable_count": len(money_unavailable),
            "closed_roundtrips": closed_roundtrips,
            "diagnostic_note": "反馈建议只进入复盘，不自动覆盖当前策略参数。",
        }
        return {"summary": summary, "suggestions": suggestions, "diagnostics": diagnostics}

    def get_monitor_overview(self, user_id: str = "default") -> Dict[str, Any]:
        positions_payload = self.get_monitor_positions(user_id=user_id, persist=False)
        feedback = self._build_monitor_feedback(user_id=user_id, positions_payload=positions_payload)
        portfolio = self.get_paper_portfolio(user_id=user_id, refresh_quotes=False)
        latest_report = self.store.get_latest_strategy_feedback_report(user_id=user_id, report_type="daily")
        summary = feedback.get("summary") or {}
        return {
            "summary": {
                **summary,
                "total_market_value": (portfolio.get("summary") or {}).get("total_market_value", 0),
                "total_unrealized_pnl": (portfolio.get("summary") or {}).get("total_unrealized_pnl", 0),
                "total_unrealized_pnl_pct": (portfolio.get("summary") or {}).get("total_unrealized_pnl_pct", 0),
            },
            "latest_report": {
                "report_id": (latest_report or {}).get("report_id"),
                "report_date": (latest_report or {}).get("report_date"),
                "created_at": (latest_report or {}).get("created_at"),
            },
            "updated_at": positions_payload.get("updated_at"),
        }

    def run_daily_monitor_review(self, user_id: str = "default") -> Dict[str, Any]:
        positions_payload = self.get_monitor_positions(user_id=user_id, persist=True)
        feedback = self._build_monitor_feedback(user_id=user_id, positions_payload=positions_payload)
        now = datetime.now()
        report_date = now.strftime("%Y-%m-%d")
        report = self.store.save_strategy_feedback_report(
            report_id=f"monitor_{user_id}_{report_date}",
            user_id=user_id,
            report_date=report_date,
            report_type="daily",
            summary=feedback.get("summary") or {},
            suggestions=feedback.get("suggestions") or [],
            diagnostics={
                **(feedback.get("diagnostics") or {}),
                "snapshot_count": len(positions_payload.get("items") or []),
                "snapshot_date": positions_payload.get("snapshot_date"),
            },
            created_at=now.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return {
            **report,
            "positions": positions_payload.get("items", []),
            "snapshot_date": positions_payload.get("snapshot_date"),
        }

    def get_monitor_feedback_latest(self, user_id: str = "default") -> Dict[str, Any]:
        report = self.store.get_latest_strategy_feedback_report(user_id=user_id, report_type="daily")
        if report:
            return report
        return self.run_daily_monitor_review(user_id=user_id)

    def get_picks_history(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbol: Optional[str] = None,
        action: Optional[str] = None,
    ) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []

        for trade_date, picks in self._pick_history.items():
            if start_date and trade_date < start_date:
                continue
            if end_date and trade_date > end_date:
                continue
            for pick in picks:
                if symbol and pick.get("symbol") != symbol:
                    continue
                if action and pick.get("action") != action:
                    continue
                items.append({"trade_date": trade_date, **pick})

        items.sort(key=lambda x: (x.get("trade_date", ""), x.get("rank_no", 999)), reverse=True)
        return {"items": items}

    @staticmethod
    def _parse_trade_time(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _build_trade_diagnostics(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = []
        for idx, item in enumerate(trades or []):
            dt = self._parse_trade_time(item.get("trade_date"))
            reason = str(item.get("reason") or "")
            score_match = re.search(r"score=([0-9]+(?:\.[0-9]+)?)", reason)
            normalized.append(
                {
                    "idx": idx,
                    "dt": dt,
                    "trade_date": item.get("trade_date"),
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "side": (item.get("side") or "").lower(),
                    "price": self._safe_float(item.get("price")),
                    "qty": self._safe_float(item.get("qty")),
                    "reason": reason,
                    "entry_score": self._safe_float(score_match.group(1), -1) if score_match else None,
                }
            )
        normalized.sort(key=lambda x: (x["dt"] or datetime.min, x["idx"]))

        lots_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        round_trips: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []
        drawdown_curve: List[Dict[str, Any]] = []

        realized_pnl = 0.0
        realized_cost = 0.0
        equity_peak = 1.0
        min_drawdown = 0.0

        for trade in normalized:
            symbol = trade.get("symbol")
            if not symbol:
                continue
            side = trade.get("side")
            price = max(trade.get("price", 0.0), 0.0)
            qty = max(trade.get("qty", 0.0), 0.0)
            if price <= 0 or qty <= 0:
                continue

            if side == "buy":
                lots_by_symbol.setdefault(symbol, []).append(
                    {
                        "qty": qty,
                        "price": price,
                        "dt": trade.get("dt"),
                        "trade_date": trade.get("trade_date"),
                        "name": trade.get("name"),
                        "entry_score": trade.get("entry_score"),
                    }
                )
                continue

            if side != "sell":
                continue

            remain = qty
            symbol_lots = lots_by_symbol.get(symbol, [])
            while remain > 1e-9 and symbol_lots:
                lot = symbol_lots[0]
                matched_qty = min(remain, lot["qty"])
                if matched_qty <= 1e-9:
                    break

                entry_price = lot["price"]
                exit_price = price
                cost_amount = entry_price * matched_qty
                pnl_amount = (exit_price - entry_price) * matched_qty
                return_pct = (pnl_amount / cost_amount * 100) if cost_amount > 0 else 0.0
                entry_dt = lot.get("dt")
                exit_dt = trade.get("dt")
                if entry_dt and exit_dt:
                    hold_days = max((exit_dt - entry_dt).days, 0)
                else:
                    hold_days = 0

                realized_cost += cost_amount
                realized_pnl += pnl_amount

                base = realized_cost if realized_cost > 0 else 1.0
                equity_value = 1.0 + realized_pnl / base
                equity_peak = max(equity_peak, equity_value)
                drawdown = (equity_value - equity_peak) / equity_peak if equity_peak > 0 else 0.0
                min_drawdown = min(min_drawdown, drawdown)

                exit_date_text = trade.get("trade_date") or (
                    exit_dt.strftime("%Y-%m-%d %H:%M:%S") if exit_dt else None
                )
                if exit_date_text:
                    equity_curve.append({"date": exit_date_text, "value": round(equity_value, 6)})
                    drawdown_curve.append({"date": exit_date_text, "value": round(drawdown, 6)})

                round_trips.append(
                    {
                        "symbol": symbol,
                        "name": trade.get("name") or lot.get("name") or symbol,
                        "entry_date": lot.get("trade_date"),
                        "exit_date": trade.get("trade_date"),
                        "entry_price": round(entry_price, 4),
                        "exit_price": round(exit_price, 4),
                        "qty": round(matched_qty, 4),
                        "pnl_amount": round(pnl_amount, 4),
                        "return_pct": round(return_pct, 4),
                        "holding_days": hold_days,
                        "entry_score": lot.get("entry_score"),
                    }
                )

                lot["qty"] = round(max(lot["qty"] - matched_qty, 0.0), 6)
                if lot["qty"] <= 1e-9:
                    symbol_lots.pop(0)
                remain = round(max(remain - matched_qty, 0.0), 6)

        closed_count = len(round_trips)
        returns = [item["return_pct"] for item in round_trips]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        win_rate = len(wins) / closed_count if closed_count > 0 else 0.0
        avg_return_pct = mean(returns) if returns else 0.0
        avg_win_pct = mean(wins) if wins else 0.0
        avg_loss_pct = mean(losses) if losses else 0.0
        profit_loss_ratio = (avg_win_pct / abs(avg_loss_pct)) if avg_loss_pct < 0 else (9.99 if wins else 0.0)
        holding_days_avg = mean([item["holding_days"] for item in round_trips]) if round_trips else 0.0
        total_return_pct = (realized_pnl / realized_cost * 100) if realized_cost > 0 else 0.0

        if closed_count >= 2:
            returns_decimal = [r / 100.0 for r in returns]
            ret_std = pstdev(returns_decimal)
            if ret_std > 1e-9:
                sharpe = (mean(returns_decimal) / ret_std) * (252 ** 0.5)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        first_dt = None
        last_dt = None
        for item in normalized:
            dt = item.get("dt")
            if not dt:
                continue
            if first_dt is None or dt < first_dt:
                first_dt = dt
            if last_dt is None or dt > last_dt:
                last_dt = dt
        period_days = max((last_dt - first_dt).days, 1) if first_dt and last_dt else 1

        if realized_cost > 0 and total_return_pct > -99.9:
            annual_return = (1 + total_return_pct / 100.0) ** (365 / period_days) - 1
            annual_return = self._clamp(annual_return, -0.99, 3.0)
        else:
            annual_return = 0.0

        if not equity_curve:
            base_date = datetime.now().strftime("%Y-%m-%d")
            equity_curve = [{"date": base_date, "value": 1.0}]
        if not drawdown_curve:
            base_date = datetime.now().strftime("%Y-%m-%d")
            drawdown_curve = [{"date": base_date, "value": 0.0}]

        return {
            "source": "paper_trades" if trades else "none",
            "trade_count": len(normalized),
            "closed_roundtrips": closed_count,
            "win_rate": round(win_rate, 6),
            "avg_return_pct": round(avg_return_pct, 6),
            "avg_win_pct": round(avg_win_pct, 6),
            "avg_loss_pct": round(avg_loss_pct, 6),
            "profit_loss_ratio": round(profit_loss_ratio, 6),
            "avg_holding_days": round(holding_days_avg, 4),
            "total_realized_pnl": round(realized_pnl, 6),
            "total_realized_return_pct": round(total_return_pct, 6),
            "annual_return": round(annual_return, 6),
            "max_drawdown": round(abs(min_drawdown), 6),
            "sharpe": round(sharpe, 6),
            "equity_curve": equity_curve[-120:],
            "drawdown_curve": drawdown_curve[-120:],
            "round_trips": round_trips[-200:],
        }

    def _build_probability_calibration(self, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        round_trips = diagnostics.get("round_trips") or []
        bucket_defs = [
            ("90分以上", 90.0, 101.0),
            ("85-90分", 85.0, 90.0),
            ("80-85分", 80.0, 85.0),
            ("75-80分", 75.0, 80.0),
            ("70-75分", 70.0, 75.0),
            ("70分以下", 0.0, 70.0),
        ]
        valid = [
            item
            for item in round_trips
            if item.get("entry_score") is not None and self._safe_float(item.get("entry_score"), -1) >= 0
        ]
        total_sample = len(valid)
        buckets = []
        for label, min_score, max_score in bucket_defs:
            rows = [
                item
                for item in valid
                if min_score <= self._safe_float(item.get("entry_score"), -1) < max_score
            ]
            sample_count = len(rows)
            wins = [item for item in rows if self._safe_float(item.get("return_pct"), 0) > 0]
            losses = [item for item in rows if self._safe_float(item.get("return_pct"), 0) <= 0]
            avg_return = mean([self._safe_float(item.get("return_pct"), 0) for item in rows]) if rows else 0.0
            buckets.append(
                {
                    "label": label,
                    "min_score": min_score,
                    "max_score": max_score,
                    "sample_count": sample_count,
                    "win_rate": round(len(wins) / sample_count, 4) if sample_count else 0.0,
                    "loss_rate": round(len(losses) / sample_count, 4) if sample_count else 0.0,
                    "avg_return_pct": round(avg_return, 4),
                    "calibrated": sample_count >= 8,
                }
            )

        calibrated_bucket_count = sum(1 for item in buckets if item.get("calibrated"))
        calibrated = total_sample >= 30 and calibrated_bucket_count >= 2
        return {
            "type": "historical_score_bucket" if calibrated else "proxy_rule_with_history_hint",
            "label": "历史校准概率" if calibrated else "规则代理概率",
            "calibrated": calibrated,
            "sample_count": total_sample,
            "min_total_sample": 30,
            "min_bucket_sample": 8,
            "calibrated_bucket_count": calibrated_bucket_count,
            "buckets": buckets,
            "message": (
                "已基于回测闭环交易按评分分层校准概率。"
                if calibrated
                else "闭环样本不足，当前只能展示历史分层提示，不能视为真实胜率。"
            ),
        }

    @staticmethod
    def _parse_backtest_date(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        return None

    def _derive_market_state(self, avg_change: float, up_ratio: float) -> Dict[str, Any]:
        trend_score = self._clamp(50 + avg_change * 4, 0, 100)
        breadth_score = self._clamp(up_ratio * 100, 0, 100)
        money_flow_score = self._clamp(45 + avg_change * 3, 0, 100)
        risk_score = self._clamp(65 - abs(avg_change) * 4, 0, 100)
        state_score = self._clamp(
            0.35 * trend_score + 0.25 * breadth_score + 0.20 * money_flow_score + 0.20 * risk_score,
            0,
            100,
        )
        if state_score >= 65:
            state_tag = "offensive"
        elif state_score >= 45:
            state_tag = "neutral"
        else:
            state_tag = "defensive"
        return {
            "state_tag": state_tag,
            "state_score": round(state_score, 2),
            "drivers": {
                "trend_score": round(trend_score, 2),
                "breadth_score": round(breadth_score, 2),
                "money_flow_score": round(money_flow_score, 2),
                "risk_score": round(risk_score, 2),
            },
        }

    def _build_backtest_universe(self, risk_level: str, max_symbols: int) -> Dict[str, Any]:
        entries = self._get_universe_snapshot(force=False) or self.data_source_manager.get_a_share_snapshot()
        if not entries:
            return {
                "items": [{"symbol": s, "name": s, "industry": "未知行业", "pre_score": 0} for s in self.CANDIDATE_POOL],
                "meta": {
                    "source": "fallback_static",
                    "input_count": 0,
                    "prefilter_count": len(self.CANDIDATE_POOL),
                    "selected_count": len(self.CANDIDATE_POOL),
                },
            }

        rules = self._get_universe_rules(risk_level)
        # 回测阶段适度放宽实时筛选阈值，避免样本过窄导致统计偏差
        min_amount_yi = max(0.5, float(rules.get("min_amount_yi", 2.0)) * 0.6)
        min_turnover = max(0.3, float(rules.get("min_turnover_rate", 0.8)) * 0.6)
        max_turnover = min(40.0, float(rules.get("max_turnover_rate", 20.0)) * 1.3)
        max_abs_pct_change = min(18.0, float(rules.get("max_abs_pct_change", 12.0)) * 1.3)
        industry_cap = max(2, min(10, int(rules.get("industry_cap", 3)) + 2))
        min_price = max(1.0, float(rules.get("min_price", 2.0)) * 0.8)

        industry_map = self.data_source_manager.get_stock_industry_map()
        filtered: List[Dict[str, Any]] = []

        for item in entries:
            symbol = str(item.get("symbol") or "")
            if len(symbol) != 6 or not symbol.isdigit() or symbol[0] not in {"0", "3", "6"}:
                continue
            name = str(item.get("name") or symbol)
            if self._is_excluded_name(name):
                continue

            price = self._safe_float(item.get("price"), 0)
            if price < min_price:
                continue

            amount_yi = self._safe_float(item.get("amount"), 0) / 100000000
            if amount_yi < min_amount_yi:
                continue

            turnover_rate = self._safe_float(item.get("turnover_rate"), 0)
            if turnover_rate <= 0:
                circ_mv = self._safe_float(item.get("circ_mv"), 0)
                if circ_mv > 0:
                    turnover_rate = self._clamp((self._safe_float(item.get("amount"), 0) / circ_mv) * 100, 0, 60)
                else:
                    turnover_rate = self._clamp(amount_yi * 0.35, 0.2, 25)
            if turnover_rate < min_turnover or turnover_rate > max_turnover:
                continue

            pct_change = self._safe_float(item.get("pct_change"), 0)
            if abs(pct_change) > max_abs_pct_change:
                continue

            if turnover_rate <= 2:
                turnover_score = 45 + turnover_rate * 6
            elif turnover_rate <= 10:
                turnover_score = 57 + (turnover_rate - 2) * 3.5
            elif turnover_rate <= 20:
                turnover_score = 85 - (turnover_rate - 10) * 2
            else:
                turnover_score = 65 - (turnover_rate - 20) * 2
            turnover_score = self._clamp(turnover_score, 0, 100)
            liquidity_score = self._clamp(amount_yi * 6, 0, 100)
            momentum_score = self._clamp(12 - abs(pct_change), 0, 12)
            pre_score = 0.55 * liquidity_score + 0.35 * turnover_score + 0.10 * momentum_score

            industry = (
                str(industry_map.get(symbol) or "").strip()
                or str(item.get("industry") or "").strip()
                or self._infer_board_industry(symbol)
            )
            row = copy.deepcopy(item)
            row["symbol"] = symbol
            row["name"] = name
            row["industry"] = industry
            row["pre_score"] = round(pre_score, 4)
            filtered.append(row)

        by_industry: Dict[str, List[Dict[str, Any]]] = {}
        for row in filtered:
            by_industry.setdefault(row.get("industry", "未知行业"), []).append(row)

        diversified: List[Dict[str, Any]] = []
        for industry_rows in by_industry.values():
            industry_rows.sort(key=lambda x: x.get("pre_score", 0), reverse=True)
            diversified.extend(industry_rows[:industry_cap])

        diversified.sort(key=lambda x: x.get("pre_score", 0), reverse=True)
        selected = diversified[: max(10, min(max_symbols, 300))]
        if not selected:
            selected = [{"symbol": s, "name": s, "industry": "未知行业", "pre_score": 0} for s in self.CANDIDATE_POOL]

        return {
            "items": selected,
            "meta": {
                "source": "a_share_snapshot_prefilter",
                "input_count": len(entries),
                "prefilter_count": len(filtered),
                "selected_count": len(selected),
                "industry_count": len(by_industry),
                "rules": {
                    "min_amount_yi": round(min_amount_yi, 3),
                    "min_turnover_rate": round(min_turnover, 3),
                    "max_turnover_rate": round(max_turnover, 3),
                    "max_abs_pct_change": round(max_abs_pct_change, 3),
                    "min_price": round(min_price, 3),
                    "industry_cap": industry_cap,
                },
            },
        }

    def _build_historical_pick(
        self,
        symbol: str,
        name: str,
        row: pd.Series,
        risk_profile: Dict[str, Any],
        market_state: Dict[str, Any],
        trade_date: str,
        strategy_code: str,
    ) -> Optional[Dict[str, Any]]:
        close_price = self._safe_float(row.get("close"), 0)
        if close_price <= 0:
            return None

        indicators = {
            "date": trade_date,
            "close": close_price,
            "ma5": row.get("ma5"),
            "ma10": row.get("ma10"),
            "ma20": row.get("ma20"),
            "ma60": row.get("ma60"),
            "macd": row.get("macd"),
            "macd_signal": row.get("macd_signal"),
            "macd_hist": row.get("macd_hist"),
            "rsi": row.get("rsi"),
            "k": row.get("k"),
            "d": row.get("d"),
            "j": row.get("j"),
            "boll_upper": row.get("boll_upper"),
            "boll_middle": row.get("boll_middle"),
            "boll_lower": row.get("boll_lower"),
        }
        signal = TechnicalAnalyzer.generate_signals(indicators)
        signal_score = float(signal.get("score", 0) or 0)
        up_prob = self._clamp(0.52 + signal_score / 250.0, 0.05, 0.95)
        dd_prob = self._clamp(0.34 - signal_score / 400.0, 0.05, 0.90)
        strategy = str(strategy_code or "trend_breakout").strip().lower()

        pct_change = self._safe_float(row.get("pct_change"), 0)
        vol_ratio = self._safe_float(row.get("vol_ratio"), 1.0)
        # 历史重放无法直接逐日取主力净流入，使用成交量放大+涨跌幅构造资金强弱代理
        main_net_inflow_yi = self._clamp((vol_ratio - 1.0) * 1.8 + pct_change * 0.08, -5.0, 5.0)
        turnover_rate = self._clamp(2.0 + vol_ratio * 2.5 + abs(pct_change) * 0.35, 0.3, 25.0)

        flow_score = self._clamp(50 + main_net_inflow_yi * 8, 0, 100)
        if turnover_rate <= 2:
            turnover_score = 45 + turnover_rate * 6
        elif turnover_rate <= 8:
            turnover_score = 60 + (turnover_rate - 2) * 4
        elif turnover_rate <= 15:
            turnover_score = 84 - (turnover_rate - 8) * 2
        else:
            turnover_score = 70 - (turnover_rate - 15) * 3
        turnover_score = self._clamp(turnover_score, 0, 100)

        up_prob = self._clamp(up_prob + self._clamp(main_net_inflow_yi * 0.012, -0.05, 0.05), 0.05, 0.95)
        if turnover_rate > 15:
            dd_prob = self._clamp(dd_prob + 0.05, 0.05, 0.90)
        elif turnover_rate < 1:
            dd_prob = self._clamp(dd_prob + 0.02, 0.05, 0.90)
        elif 3 <= turnover_rate <= 10:
            dd_prob = self._clamp(dd_prob - 0.01, 0.05, 0.90)

        # 独立策略分流：回调修复策略与趋势突破策略使用不同信号结构
        rsi = self._safe_float(indicators.get("rsi"), 50)
        macd_hist = self._safe_float(indicators.get("macd_hist"), 0)
        ma5 = self._safe_float(indicators.get("ma5"), close_price)
        ma10 = self._safe_float(indicators.get("ma10"), close_price)
        ma20 = self._safe_float(indicators.get("ma20"), close_price)
        ma60 = self._safe_float(indicators.get("ma60"), close_price)
        boll_lower = self._safe_float(indicators.get("boll_lower"), 0)
        boll_middle = self._safe_float(indicators.get("boll_middle"), 0)
        near_lower_band = bool(boll_lower > 0 and close_price <= boll_lower * 1.04)
        reclaim_middle_band = bool(boll_middle > 0 and close_price >= boll_middle * 0.99)
        prev_pct_change = self._safe_float(row.get("prev_pct_change"), 0)
        return_5d_pct = self._safe_float(row.get("return_5d_pct"), 0)
        return_20d_pct = self._safe_float(row.get("return_20d_pct"), 0)
        from_20d_high_pct = self._safe_float(row.get("from_20d_high_pct"), 0)
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
        overheated = bool(rsi >= 78 or stretch_from_ma20_pct >= 10 or return_20d_pct >= 24 or pct_change >= 6.5)
        broken_downtrend = bool(
            return_20d_pct <= -14
            or from_20d_high_pct <= -22
            or (ma20 > 0 and ma60 > 0 and close_price < ma20 * 0.96 and ma20 < ma60)
        )
        rebound_day = bool(pct_change > 0.6 and prev_pct_change < 0)
        oversold = bool(rsi <= 35)
        macd_repair = bool(macd_hist >= -0.03)
        pullback_score = (
            (24 if oversold else 0)
            + (18 if near_lower_band else 0)
            + (16 if rebound_day else 0)
            + (12 if macd_repair else 0)
            + (8 if reclaim_middle_band else 0)
        )
        if strategy == "pullback_rebound":
            up_prob = self._clamp(up_prob - 0.08 + pullback_score / 180.0 + self._clamp(main_net_inflow_yi * 0.01, -0.04, 0.04), 0.05, 0.95)
            dd_prob = self._clamp(dd_prob + 0.05 - pullback_score / 220.0, 0.05, 0.90)
            flow_score = self._clamp(flow_score * 0.7 + pullback_score * 0.3, 0, 100)
            turnover_score = self._clamp(turnover_score * 0.85 + (50 if 1.0 <= turnover_rate <= 10 else 36) * 0.15, 0, 100)
            signal_score = signal_score * 0.72 + pullback_score * 0.75

        state_tag = (market_state or {}).get("state_tag", "neutral")
        if state_tag == "defensive":
            up_prob = self._clamp(up_prob - 0.03, 0.05, 0.95)
            dd_prob = self._clamp(dd_prob + 0.05, 0.05, 0.90)
        elif state_tag == "offensive":
            up_prob = self._clamp(up_prob + 0.02, 0.05, 0.95)
            dd_prob = self._clamp(dd_prob - 0.03, 0.05, 0.90)

        quality_notes: List[str] = []
        disqualify_buy = False
        disqualify_watch = False
        structure_penalty = 0.0

        if broken_downtrend:
            quality_notes.append("趋势结构破位：20日跌幅/高位回撤过大或价格跌破中期均线")
            disqualify_buy = True
            disqualify_watch = True
            structure_penalty += 24.0

        if strategy == "trend_breakout":
            trend_structure_ok = (
                ma_alignment >= 3
                and -3.0 <= return_20d_pct <= 18.0
                and from_20d_high_pct >= -10.0
                and stretch_from_ma20_pct <= 7.5
                and rsi <= 72.0
            )
            trend_volume_ok = 0.75 <= vol_ratio <= 3.2
            trend_flow_ok = main_net_inflow_yi >= -0.35
            if not trend_structure_ok:
                quality_notes.append("趋势突破质量不足：均线、20日涨幅、RSI 或乖离率不满足买入闸门")
                disqualify_buy = True
                structure_penalty += 10.0
            if not trend_volume_ok:
                quality_notes.append("量能结构不理想：放量不足或短线放量过猛")
                disqualify_buy = True
                structure_penalty += 5.0
            if not trend_flow_ok:
                quality_notes.append("资金闸门未通过：资金代理强度偏弱")
                disqualify_buy = True
                structure_penalty += 6.0
            if overheated:
                quality_notes.append("短线过热：RSI、均线乖离或20日涨幅偏高，禁止追高买入")
                disqualify_buy = True
                structure_penalty += 12.0
        else:
            pullback_structure_ok = (
                -18.0 <= return_20d_pct <= 8.0
                and from_20d_high_pct >= -20.0
                and rsi <= 48.0
                and (rebound_day or reclaim_middle_band or macd_repair)
            )
            pullback_flow_ok = main_net_inflow_yi >= -0.6
            if not pullback_structure_ok:
                quality_notes.append("回调修复质量不足：尚未出现止跌、修复或均线收复信号")
                disqualify_buy = True
                structure_penalty += 10.0
            if not pullback_flow_ok:
                quality_notes.append("资金闸门未通过：回调阶段资金代理仍偏弱")
                disqualify_buy = True
                structure_penalty += 6.0
            if rsi < 22:
                quality_notes.append("极端弱势：RSI过低，优先等待止跌确认")
                disqualify_buy = True
                disqualify_watch = True
                structure_penalty += 12.0

        if structure_penalty:
            up_prob = self._clamp(up_prob - structure_penalty / 380.0, 0.05, 0.86)
            dd_prob = self._clamp(dd_prob + structure_penalty / 320.0, 0.08, 0.90)
            signal_score -= structure_penalty * 0.65
        up_prob = self._clamp(up_prob, 0.05, 0.80)
        dd_prob = self._clamp(dd_prob, 0.10, 0.90)

        risk_level = str(risk_profile.get("risk_level") or "medium")
        if risk_level == "low":
            stop_loss_ratio = 0.06
            take_profit_ratio = 0.10
            base_position = min(8.0, float(risk_profile.get("max_position_pct", 10)))
            if strategy == "pullback_rebound":
                buy_cond = up_prob >= 0.56 and dd_prob <= 0.30 and (oversold or near_lower_band) and macd_repair
                watch_cond = up_prob >= 0.50 and dd_prob <= 0.36 and (oversold or rebound_day)
            else:
                buy_cond = up_prob >= 0.62 and dd_prob <= 0.26 and flow_score >= 45
                watch_cond = up_prob >= 0.54 and dd_prob <= 0.34
        elif risk_level == "high":
            stop_loss_ratio = 0.10
            take_profit_ratio = 0.18
            base_position = min(12.0, float(risk_profile.get("max_position_pct", 10)))
            if strategy == "pullback_rebound":
                buy_cond = up_prob >= 0.52 and dd_prob <= 0.42 and (oversold or near_lower_band or rebound_day)
                watch_cond = up_prob >= 0.47 and dd_prob <= 0.52 and (oversold or rebound_day)
            else:
                buy_cond = up_prob >= 0.56 and dd_prob <= 0.38
                watch_cond = up_prob >= 0.47 and dd_prob <= 0.50
        else:
            stop_loss_ratio = 0.08
            take_profit_ratio = 0.14
            base_position = min(10.0, float(risk_profile.get("max_position_pct", 10)))
            if strategy == "pullback_rebound":
                buy_cond = up_prob >= 0.54 and dd_prob <= 0.35 and (oversold or near_lower_band) and (rebound_day or macd_repair)
                watch_cond = up_prob >= 0.48 and dd_prob <= 0.42 and (oversold or rebound_day)
            else:
                buy_cond = up_prob >= 0.60 and dd_prob <= 0.30
                watch_cond = up_prob >= 0.50 and dd_prob <= 0.40

        if buy_cond:
            action = "buy"
        elif watch_cond:
            action = "watch"
        else:
            action = "pass"
        if disqualify_buy and action == "buy":
            action = "watch" if not disqualify_watch and watch_cond else "pass"
        if disqualify_watch and action == "watch":
            action = "pass"
        if action == "pass":
            return None

        confidence = "high" if (up_prob >= 0.68 and dd_prob <= 0.22) else ("medium" if up_prob >= 0.55 else "low")
        entry_min = round(close_price * 0.992, 2)
        entry_max = round(close_price * 1.008, 2)
        take_profit = round(close_price * (1 + take_profit_ratio), 2)
        stop_loss = round(close_price * (1 - stop_loss_ratio), 2)

        trend_score = self._clamp(50 + signal_score * 0.4, 0, 100)
        quality_score = self._clamp(58 + signal_score * 0.2 + (pullback_score * 0.25 if strategy == "pullback_rebound" else 0), 0, 100)
        risk_adjusted_score = self._clamp(72 - dd_prob * 65, 0, 100)
        if risk_level == "low":
            if strategy == "pullback_rebound":
                total_score = (
                    trend_score * 0.14
                    + flow_score * 0.12
                    + turnover_score * 0.10
                    + quality_score * 0.29
                    + risk_adjusted_score * 0.35
                )
            else:
                total_score = (
                    trend_score * 0.20
                    + flow_score * 0.15
                    + turnover_score * 0.10
                    + quality_score * 0.20
                    + risk_adjusted_score * 0.35
                )
        elif risk_level == "high":
            if strategy == "pullback_rebound":
                total_score = (
                    trend_score * 0.22
                    + flow_score * 0.18
                    + turnover_score * 0.13
                    + quality_score * 0.31
                    + risk_adjusted_score * 0.16
                )
            else:
                total_score = (
                    trend_score * 0.30
                    + flow_score * 0.25
                    + turnover_score * 0.15
                    + quality_score * 0.20
                    + risk_adjusted_score * 0.10
                )
        else:
            if strategy == "pullback_rebound":
                total_score = (
                    trend_score * 0.16
                    + flow_score * 0.14
                    + turnover_score * 0.10
                    + quality_score * 0.30
                    + risk_adjusted_score * 0.30
                )
            else:
                total_score = (
                    trend_score * 0.25
                    + flow_score * 0.20
                    + turnover_score * 0.10
                    + quality_score * 0.20
                    + risk_adjusted_score * 0.25
                )

        expected_mult = 16 if risk_level == "low" else (24 if risk_level == "high" else 20)
        expected_return = round((up_prob - dd_prob) * expected_mult, 2)

        return {
            "pick_id": f"{trade_date}-{symbol}-BT",
            "symbol": symbol,
            "name": name,
            "action": action,
            "up_prob": round(up_prob, 4),
            "dd_prob": round(dd_prob, 4),
            "confidence_level": confidence,
            "horizon_days": int(risk_profile.get("horizon_days_max", 15) or 15),
            "expected_return_pct": expected_return,
            "entry_range": [entry_min, entry_max],
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "position_pct": round(base_position if action == "buy" else base_position * 0.5, 2),
            "reasons": [
                (
                    f"回调修复分 {pullback_score:.1f}（超跌{('是' if oversold else '否')}、贴近下轨{('是' if near_lower_band else '否')}）"
                    if strategy == "pullback_rebound"
                    else f"技术信号分 {signal_score:.1f}"
                ),
                f"成交量放大系数 {vol_ratio:.2f}",
                f"资金代理强度 {main_net_inflow_yi:.2f} 亿",
            ],
            "risks": [
                f"回撤风险概率 {dd_prob * 100:.1f}%",
                "历史回放仅反映模型在样本区间表现",
                *quality_notes[:2],
            ],
            "market_metrics": {
                "main_net_inflow_yi": round(main_net_inflow_yi, 3),
                "turnover_rate": round(turnover_rate, 3),
            },
            "evidence_summary": {
                "strategy_code": strategy_code,
                "strategy_version": ("historical_replay_pullback_v2_gated" if strategy == "pullback_rebound" else "historical_replay_v2_gated"),
                "state_tag": state_tag,
                "quality_gate_passed": not disqualify_buy,
                "quality_notes": quality_notes[:4],
            },
            "score_breakdown": {
                "trend": round(trend_score, 2),
                "money_flow": round(flow_score, 2),
                "turnover_liquidity": round(turnover_score, 2),
                "quality": round(quality_score, 2),
                "risk_adjusted": round(risk_adjusted_score, 2),
                "total": round(self._clamp(total_score, 0, 100), 2),
            },
        }

    def _run_historical_replay_backtest(
        self,
        payload: Dict[str, Any],
        user_id: str,
        strategy_code: str,
    ) -> Dict[str, Any]:
        config = copy.deepcopy(payload.get("config") or {})
        risk_profile = self.get_risk_profile(user_id=user_id).copy()
        risk_level = str(config.get("risk_level") or risk_profile.get("risk_level") or "medium")
        if risk_level not in {"low", "medium", "high"}:
            risk_level = "medium"
        risk_profile["risk_level"] = risk_level

        end_dt = self._parse_backtest_date(payload.get("test_end")) or datetime.now()
        start_dt = self._parse_backtest_date(payload.get("test_start")) or (end_dt - timedelta(days=240))
        if start_dt >= end_dt:
            start_dt = end_dt - timedelta(days=120)
        if (end_dt - start_dt).days > 720:
            start_dt = end_dt - timedelta(days=720)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        initial_capital = max(10000.0, self._safe_float(config.get("initial_capital"), 100000.0))
        max_positions = max(1, min(20, int(self._safe_float(config.get("max_positions"), 5))))
        max_position_pct = self._clamp(
            self._safe_float(config.get("max_position_pct"), risk_profile.get("max_position_pct", 10)),
            2,
            30,
        )
        holding_days = max(3, min(90, int(self._safe_float(config.get("holding_days"), 15))))
        score_threshold = self._clamp(self._safe_float(config.get("score_threshold"), 70), 50, 95)
        score_exit_threshold = max(45.0, score_threshold - 12.0)
        stop_profit_pct = self._clamp(self._safe_float(config.get("stop_profit_pct"), 15), 5, 40) / 100.0
        stop_loss_pct = self._clamp(self._safe_float(config.get("stop_loss_pct"), 8), 2, 25) / 100.0
        commission = self._clamp(self._safe_float(config.get("commission"), 0.0003), 0, 0.01)
        slippage = self._clamp(self._safe_float(config.get("slippage"), 0.001), 0, 0.01)
        universe_size = max(20, min(300, int(self._safe_float(config.get("universe_size"), 90))))

        universe_bundle = self._build_backtest_universe(risk_level=risk_level, max_symbols=universe_size)
        universe_items = universe_bundle.get("items", [])
        symbol_rows = {
            str(row.get("symbol")): {
                "name": str(row.get("name") or row.get("symbol")),
                "industry": str(row.get("industry") or "未知行业"),
            }
            for row in universe_items
            if row.get("symbol")
        }
        symbols = list(symbol_rows.keys())

        lookback_start = (start_dt - timedelta(days=180)).strftime("%Y-%m-%d")
        fetch_days = max(260, min(900, (end_dt - start_dt).days + 260))
        histories: Dict[str, Dict[str, Any]] = {}

        def _load_history(symbol: str) -> Optional[Dict[str, Any]]:
            df = self.data_source_manager.get_history_data(symbol, days=fetch_days)
            if df is None or df.empty:
                return None
            local = df.copy()
            local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            local = local[local["date"].notna()]
            local = local[(local["date"] >= lookback_start) & (local["date"] <= end_str)]
            local = local.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
            if len(local) < 80:
                return None
            analyzed = TechnicalAnalyzer.analyze_all_indicators(local.copy())
            if analyzed is None or analyzed.empty:
                return None
            analyzed["date"] = pd.to_datetime(analyzed["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            analyzed = analyzed[analyzed["date"].notna()]
            if "amount" not in analyzed.columns:
                analyzed["amount"] = analyzed["close"] * analyzed["volume"]
            analyzed["pct_change"] = analyzed["close"].pct_change().fillna(0) * 100
            analyzed["prev_pct_change"] = analyzed["pct_change"].shift(1).fillna(0)
            analyzed["return_5d_pct"] = (analyzed["close"] / analyzed["close"].shift(5) - 1).replace([pd.NA], 0).fillna(0) * 100
            analyzed["return_20d_pct"] = (analyzed["close"] / analyzed["close"].shift(20) - 1).replace([pd.NA], 0).fillna(0) * 100
            rolling_high_20 = analyzed["high"].rolling(window=20).max().replace(0, pd.NA)
            rolling_low_20 = analyzed["low"].rolling(window=20).min().replace(0, pd.NA)
            analyzed["from_20d_high_pct"] = (analyzed["close"] / rolling_high_20 - 1).fillna(0) * 100
            analyzed["from_20d_low_pct"] = (analyzed["close"] / rolling_low_20 - 1).fillna(0) * 100
            vol_ma20 = analyzed["volume"].rolling(window=20).mean().replace(0, pd.NA)
            analyzed["vol_ratio"] = (analyzed["volume"] / vol_ma20).fillna(1.0).clip(lower=0.1, upper=5.0)
            analyzed = analyzed.reset_index(drop=True)
            if len(analyzed) < 80:
                return None
            date_index = {str(d): idx for idx, d in enumerate(analyzed["date"].tolist())}
            return {"df": analyzed, "date_index": date_index}

        max_workers = min(12, max(1, len(symbols)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_load_history, symbol): symbol for symbol in symbols}
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    loaded = future.result()
                except Exception:
                    loaded = None
                if loaded:
                    histories[symbol] = loaded

        valid_symbols = [s for s in symbols if s in histories]
        if not valid_symbols:
            return {
                "metrics": {
                    "annual_return": 0.0,
                    "max_drawdown": 0.0,
                    "sharpe": 0.0,
                    "win_rate": 0.0,
                    "profit_loss_ratio": 0.0,
                },
                "equity_curve": [{"date": end_str, "value": 1.0}],
                "drawdown_curve": [{"date": end_str, "value": 0.0}],
                "trades": [],
                "closed_roundtrips": [],
                "by_state": [],
                "diagnostics": {
                    "source": "historical_replay",
                    "trade_count": 0,
                    "closed_roundtrips": 0,
                    "avg_holding_days": 0,
                    "avg_return_pct": 0,
                    "total_realized_pnl": 0,
                    "total_realized_return_pct": 0,
                    "calendar_days": 0,
                    "universe_size": len(symbols),
                    "valid_history_symbols": 0,
                },
                "effective_config": {
                    **config,
                    "risk_level": risk_level,
                    "initial_capital": initial_capital,
                    "max_positions": max_positions,
                    "max_position_pct": max_position_pct,
                    "holding_days": holding_days,
                    "score_threshold": score_threshold,
                    "stop_profit_pct": stop_profit_pct * 100,
                    "stop_loss_pct": stop_loss_pct * 100,
                    "commission": commission,
                    "slippage": slippage,
                    "universe_size": len(symbols),
                    "valid_history_symbols": 0,
                    "test_start": start_str,
                    "test_end": end_str,
                    "universe_meta": universe_bundle.get("meta", {}),
                },
            }

        calendar = sorted(
            {
                date
                for symbol in valid_symbols
                for date in histories[symbol]["date_index"].keys()
                if start_str <= date <= end_str
            }
        )
        if not calendar:
            calendar = [end_str]

        daily_stats: Dict[str, Dict[str, float]] = {}
        for symbol in valid_symbols:
            df = histories[symbol]["df"]
            segment = df[(df["date"] >= start_str) & (df["date"] <= end_str)][["date", "pct_change"]]
            for row in segment.itertuples(index=False):
                key = str(row.date)
                stats = daily_stats.setdefault(key, {"sum_change": 0.0, "count": 0.0, "up_count": 0.0})
                pct = self._safe_float(row.pct_change, 0)
                stats["sum_change"] += pct
                stats["count"] += 1
                if pct > 0:
                    stats["up_count"] += 1

        market_state_map = {}
        for date in calendar:
            stats = daily_stats.get(date, {"sum_change": 0.0, "count": 0.0, "up_count": 0.0})
            count = max(int(stats.get("count", 0)), 1)
            avg_change = float(stats.get("sum_change", 0.0)) / count
            up_ratio = float(stats.get("up_count", 0.0)) / count
            market_state_map[date] = self._derive_market_state(avg_change=avg_change, up_ratio=up_ratio)

        cash = float(initial_capital)
        positions: Dict[str, Dict[str, Any]] = {}
        pending_orders: List[Dict[str, Any]] = []
        trades: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []
        state_returns: Dict[str, List[float]] = {"offensive": [], "neutral": [], "defensive": []}

        for idx, trade_date in enumerate(calendar):
            state = market_state_map.get(trade_date, {"state_tag": "neutral"})

            # 先执行上一交易日生成的买入计划（避免当日信号当日成交的未来函数）
            today_orders = [o for o in pending_orders if o.get("exec_date") == trade_date]
            pending_orders = [o for o in pending_orders if o.get("exec_date") != trade_date]
            for order in today_orders:
                symbol = str(order.get("symbol") or "")
                if not symbol or symbol in positions or symbol not in histories:
                    continue
                row_idx = histories[symbol]["date_index"].get(trade_date)
                if row_idx is None:
                    continue
                row = histories[symbol]["df"].iloc[row_idx]
                open_price = self._safe_float(row.get("open"), 0) or self._safe_float(row.get("close"), 0)
                if open_price <= 0:
                    continue
                exec_price = round(open_price * (1 + slippage), 4)
                single_cap = min(initial_capital * (max_position_pct / 100.0), cash)
                slots_left = max(1, max_positions - len(positions))
                slot_budget = cash / slots_left
                budget = min(single_cap, slot_budget)
                qty = int((budget / exec_price) / 100) * 100
                if qty < 100:
                    continue
                amount = round(exec_price * qty, 4)
                fee = round(amount * commission, 4)
                total_cost = amount + fee
                if total_cost > cash:
                    continue
                cash = round(cash - total_cost, 4)
                positions[symbol] = {
                    "symbol": symbol,
                    "name": str(order.get("name") or symbol),
                    "qty": float(qty),
                    "entry_price": float(exec_price),
                    "entry_date": trade_date,
                    "entry_dt": self._parse_backtest_date(trade_date) or datetime.now(),
                    "entry_score": self._safe_float(order.get("score"), 0),
                    "entry_state": str(order.get("state_tag") or "neutral"),
                    "take_profit_price": round(exec_price * (1 + stop_profit_pct), 4),
                    "stop_loss_price": round(exec_price * (1 - stop_loss_pct), 4),
                    "last_price": float(exec_price),
                }
                trades.append(
                    {
                        "trade_date": f"{trade_date} 09:35:00",
                        "symbol": symbol,
                        "name": str(order.get("name") or symbol),
                        "side": "buy",
                        "price": float(exec_price),
                        "qty": float(qty),
                        "amount": amount,
                        "reason": f"replay signal buy(score={self._safe_float(order.get('score'), 0):.2f})",
                    }
                )

            daily_picks: List[Dict[str, Any]] = []
            for symbol in valid_symbols:
                row_idx = histories[symbol]["date_index"].get(trade_date)
                if row_idx is None:
                    continue
                row = histories[symbol]["df"].iloc[row_idx]
                pick = self._build_historical_pick(
                    symbol=symbol,
                    name=symbol_rows.get(symbol, {}).get("name", symbol),
                    row=row,
                    risk_profile=risk_profile,
                    market_state=state,
                    trade_date=trade_date,
                    strategy_code=strategy_code,
                )
                if pick:
                    daily_picks.append(pick)

            if daily_picks:
                self._calibrate_pick_scores(daily_picks, state)
                daily_picks.sort(key=lambda x: self._rank_score(x, risk_level), reverse=True)

            pick_map = {p.get("symbol"): p for p in daily_picks}
            next_date = calendar[idx + 1] if idx + 1 < len(calendar) else None
            pending_symbols = {str(o.get("symbol")) for o in pending_orders if o.get("symbol")}
            available_slots = max_positions - len(positions) - len(pending_symbols)
            if next_date and available_slots > 0:
                for pick in daily_picks:
                    if available_slots <= 0:
                        break
                    if pick.get("action") != "buy":
                        continue
                    total_score = self._safe_float((pick.get("score_breakdown") or {}).get("total"), 0)
                    symbol = str(pick.get("symbol") or "")
                    if total_score < score_threshold or not symbol:
                        continue
                    if symbol in positions or symbol in pending_symbols:
                        continue
                    pending_orders.append(
                        {
                            "exec_date": next_date,
                            "symbol": symbol,
                            "name": pick.get("name"),
                            "score": total_score,
                            "state_tag": (state or {}).get("state_tag", "neutral"),
                        }
                    )
                    pending_symbols.add(symbol)
                    available_slots -= 1

            trade_dt = self._parse_backtest_date(trade_date) or datetime.now()
            for symbol, pos in list(positions.items()):
                row_idx = histories[symbol]["date_index"].get(trade_date)
                if row_idx is None:
                    continue
                row = histories[symbol]["df"].iloc[row_idx]
                close_price = self._safe_float(row.get("close"), 0)
                if close_price <= 0:
                    continue
                pos["last_price"] = close_price
                hold_days = max((trade_dt - pos.get("entry_dt", trade_dt)).days, 0)
                pick = pick_map.get(symbol)
                score_now = self._safe_float((pick.get("score_breakdown") or {}).get("total"), pos.get("entry_score", 0)) if pick else pos.get("entry_score", 0)

                exit_reason = None
                if close_price <= pos.get("stop_loss_price", 0):
                    exit_reason = "触发止损"
                elif close_price >= pos.get("take_profit_price", 0):
                    exit_reason = "触发止盈"
                elif hold_days >= holding_days:
                    exit_reason = "达到持有周期"
                elif pick and score_now < score_exit_threshold:
                    exit_reason = f"评分跌破阈值({score_exit_threshold:.1f})"

                if not exit_reason:
                    continue

                exec_price = round(close_price * (1 - slippage), 4)
                qty = float(pos.get("qty") or 0)
                amount = round(exec_price * qty, 4)
                fee = round(amount * commission, 4)
                cash = round(cash + amount - fee, 4)
                entry_price = self._safe_float(pos.get("entry_price"), 0)
                if entry_price > 0:
                    rtn = (exec_price - entry_price) / entry_price
                    state_returns.setdefault(str(pos.get("entry_state") or "neutral"), []).append(rtn)

                trades.append(
                    {
                        "trade_date": f"{trade_date} 15:00:00",
                        "symbol": symbol,
                        "name": pos.get("name") or symbol,
                        "side": "sell",
                        "price": float(exec_price),
                        "qty": qty,
                        "amount": amount,
                        "reason": f"{exit_reason} | entry_state={pos.get('entry_state', 'neutral')}",
                    }
                )
                positions.pop(symbol, None)

            market_value = 0.0
            for pos in positions.values():
                market_value += self._safe_float(pos.get("last_price"), self._safe_float(pos.get("entry_price"), 0)) * self._safe_float(pos.get("qty"), 0)
            equity_curve.append(
                {
                    "date": trade_date,
                    "value": round((cash + market_value) / initial_capital, 6),
                }
            )

        # 回测区间结束后强制平仓，保证收益统计可闭合
        if positions:
            final_date = calendar[-1]
            for symbol, pos in list(positions.items()):
                price = self._safe_float(pos.get("last_price"), self._safe_float(pos.get("entry_price"), 0))
                if price <= 0:
                    continue
                exec_price = round(price * (1 - slippage), 4)
                qty = self._safe_float(pos.get("qty"), 0)
                amount = round(exec_price * qty, 4)
                fee = round(amount * commission, 4)
                cash = round(cash + amount - fee, 4)
                entry_price = self._safe_float(pos.get("entry_price"), 0)
                if entry_price > 0:
                    rtn = (exec_price - entry_price) / entry_price
                    state_returns.setdefault(str(pos.get("entry_state") or "neutral"), []).append(rtn)
                trades.append(
                    {
                        "trade_date": f"{final_date} 15:00:00",
                        "symbol": symbol,
                        "name": pos.get("name") or symbol,
                        "side": "sell",
                        "price": float(exec_price),
                        "qty": qty,
                        "amount": amount,
                        "reason": "回测结束平仓",
                    }
                )
                positions.pop(symbol, None)
            equity_curve.append({"date": final_date, "value": round(cash / initial_capital, 6)})

        if not equity_curve:
            equity_curve = [{"date": end_str, "value": 1.0}]

        drawdown_curve: List[Dict[str, Any]] = []
        peak = 0.0
        min_drawdown = 0.0
        for point in equity_curve:
            value = self._safe_float(point.get("value"), 1.0)
            peak = max(peak, value)
            drawdown = (value - peak) / peak if peak > 0 else 0.0
            min_drawdown = min(min_drawdown, drawdown)
            drawdown_curve.append({"date": point.get("date"), "value": round(drawdown, 6)})

        values = [self._safe_float(point.get("value"), 1.0) for point in equity_curve]
        daily_returns = []
        for i in range(1, len(values)):
            prev = values[i - 1]
            curr = values[i]
            if prev > 0:
                daily_returns.append(curr / prev - 1)
        if len(daily_returns) >= 2:
            ret_std = pstdev(daily_returns)
            sharpe = (mean(daily_returns) / ret_std) * (252 ** 0.5) if ret_std > 1e-9 else 0.0
        else:
            sharpe = 0.0
        total_return = values[-1] - 1 if values else 0.0
        period_days = max((end_dt - start_dt).days, 1)
        if total_return > -0.99:
            annual_return = (1 + total_return) ** (365 / period_days) - 1
        else:
            annual_return = -0.99

        diagnostics = self._build_trade_diagnostics(trades)
        diagnostics["source"] = "historical_replay"
        diagnostics["trade_count"] = len(trades)
        diagnostics["equity_curve"] = equity_curve[-240:]
        diagnostics["drawdown_curve"] = drawdown_curve[-240:]
        diagnostics["calendar_days"] = len(calendar)
        diagnostics["universe_size"] = len(symbols)
        diagnostics["valid_history_symbols"] = len(valid_symbols)
        diagnostics["total_realized_return_pct"] = round(total_return * 100, 6)
        diagnostics["max_drawdown"] = round(abs(min_drawdown), 6)
        diagnostics["annual_return"] = round(annual_return, 6)
        diagnostics["sharpe"] = round(sharpe, 6)

        by_state = []
        for state_tag in ["offensive", "neutral", "defensive"]:
            state_series = state_returns.get(state_tag, [])
            if state_series:
                win_rate = sum(1 for x in state_series if x > 0) / len(state_series)
                state_max_dd = abs(min(state_series))
            else:
                win_rate = 0.0
                state_max_dd = 0.0
            by_state.append(
                {
                    "state_tag": state_tag,
                    "win_rate": round(win_rate, 4),
                    "max_drawdown": round(state_max_dd, 4),
                    "sample_count": len(state_series),
                }
            )

        metrics = {
            "annual_return": round(self._clamp(annual_return, -0.99, 3.0), 6),
            "max_drawdown": round(self._clamp(abs(min_drawdown), 0.0, 0.95), 6),
            "sharpe": round(self._clamp(sharpe, -5.0, 8.0), 6),
            "win_rate": round(self._clamp(self._safe_float(diagnostics.get("win_rate"), 0), 0.0, 1.0), 6),
            "profit_loss_ratio": round(self._clamp(self._safe_float(diagnostics.get("profit_loss_ratio"), 0), 0.0, 10.0), 6),
        }

        return {
            "metrics": metrics,
            "equity_curve": equity_curve[-240:],
            "drawdown_curve": drawdown_curve[-240:],
            "trades": trades[-600:],
            "closed_roundtrips": diagnostics.get("round_trips", []),
            "by_state": by_state,
            "diagnostics": diagnostics,
            "effective_config": {
                **config,
                "risk_level": risk_level,
                "initial_capital": round(initial_capital, 2),
                "max_positions": max_positions,
                "max_position_pct": round(max_position_pct, 2),
                "holding_days": holding_days,
                "score_threshold": round(score_threshold, 2),
                "stop_profit_pct": round(stop_profit_pct * 100, 2),
                "stop_loss_pct": round(stop_loss_pct * 100, 2),
                "commission": commission,
                "slippage": slippage,
                "universe_size": len(symbols),
                "valid_history_symbols": len(valid_symbols),
                "test_start": start_str,
                "test_end": end_str,
                "universe_meta": universe_bundle.get("meta", {}),
            },
        }

    def _build_optimization_suggestions(
        self,
        diagnostics: Dict[str, Any],
        config: Dict[str, Any],
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:
        suggestions: List[Dict[str, Any]] = []
        cfg = copy.deepcopy(config or {})

        score_threshold = int(self._safe_float(cfg.get("score_threshold", 70), 70))
        stop_loss = self._safe_float(cfg.get("stop_loss_pct", 8), 8)
        stop_profit = self._safe_float(cfg.get("stop_profit_pct", 15), 15)
        holding_days = int(self._safe_float(cfg.get("holding_days", 15), 15))

        closed = int(diagnostics.get("closed_roundtrips", 0) or 0)
        win_rate = self._safe_float(diagnostics.get("win_rate"), 0)
        pl_ratio = self._safe_float(diagnostics.get("profit_loss_ratio"), 0)
        max_dd = self._safe_float(diagnostics.get("max_drawdown"), 0)
        avg_hold = self._safe_float(diagnostics.get("avg_holding_days"), 0)
        avg_return_pct = self._safe_float(diagnostics.get("avg_return_pct"), 0)
        total_realized_return_pct = self._safe_float(diagnostics.get("total_realized_return_pct"), 0)

        if closed < 6:
            suggestions.append(
                {
                    "id": "expand_sample",
                    "priority": "high",
                    "title": "先扩大样本，再做激进参数调整",
                    "reason": f"当前闭环交易仅 {closed} 笔，统计稳定性不足。",
                    "changes": {
                        "min_closed_roundtrips": 20,
                        "paper_trade_days": 10,
                    },
                    "expected_effect": "降低过拟合风险，避免因为少量交易误判策略有效性。",
                }
            )

        if win_rate < 0.50 and closed >= 3:
            new_threshold = min(95, score_threshold + 5)
            cfg["score_threshold"] = new_threshold
            suggestions.append(
                {
                    "id": "raise_threshold",
                    "priority": "high",
                    "title": "提高入选阈值，减少低质量信号",
                    "reason": f"当前胜率 {win_rate * 100:.1f}% 偏低，需强化入场过滤。",
                    "changes": {
                        "score_threshold": new_threshold,
                        "risk_weight_bias": "increase_risk_adjusted",
                    },
                    "expected_effect": "减少交易频次，优先保留高质量信号。",
                }
            )

        if pl_ratio < 1.2 and closed >= 3:
            new_stop_loss = round(max(3.0, stop_loss - 1.5), 2)
            cfg["stop_loss_pct"] = new_stop_loss
            suggestions.append(
                {
                    "id": "tighten_stop_loss",
                    "priority": "high",
                    "title": "收紧止损，控制单笔亏损扩张",
                    "reason": f"盈亏比 {pl_ratio:.2f} 偏低，说明亏损控制弱于盈利兑现。",
                    "changes": {
                        "stop_loss_pct": new_stop_loss,
                        "execution_rule": "strict_stop_loss",
                    },
                    "expected_effect": "降低尾部亏损，提升风险调整后收益。",
                }
            )

        if avg_hold > 0 and avg_hold < holding_days * 0.6 and avg_return_pct > 0:
            new_holding = max(5, int(round(avg_hold + 2)))
            cfg["holding_days"] = new_holding
            suggestions.append(
                {
                    "id": "shorten_holding_window",
                    "priority": "medium",
                    "title": "缩短持有周期，匹配真实交易节奏",
                    "reason": f"平均持有 {avg_hold:.1f} 天，显著低于配置 {holding_days} 天。",
                    "changes": {
                        "holding_days": new_holding,
                    },
                    "expected_effect": "减少超期持仓导致的回吐风险。",
                }
            )

        if win_rate >= 0.60 and avg_return_pct >= 2.0 and pl_ratio >= 1.5:
            new_take_profit = round(min(35.0, stop_profit + 2.0), 2)
            cfg["stop_profit_pct"] = new_take_profit
            suggestions.append(
                {
                    "id": "lift_take_profit",
                    "priority": "medium",
                    "title": "适度上调止盈，延长优势仓位",
                    "reason": "胜率与盈亏比均健康，可适当放大利润段。",
                    "changes": {
                        "stop_profit_pct": new_take_profit,
                    },
                    "expected_effect": "在不明显增加回撤的前提下提升单笔收益上限。",
                }
            )

        if max_dd > 0.12:
            suggestions.append(
                {
                    "id": "reduce_exposure",
                    "priority": "high",
                    "title": "降低仓位暴露，优先回撤管理",
                    "reason": f"最大回撤 {max_dd * 100:.1f}% 偏高。",
                    "changes": {
                        "max_position_pct": "reduce_to_6_8",
                        "state_defensive_only_buy": True,
                    },
                    "expected_effect": "优先压降回撤，再追求收益扩张。",
                }
            )

        port_summary = (portfolio or {}).get("summary", {})
        open_positions = int(port_summary.get("position_count", 0) or 0)
        total_unrealized_pct = self._safe_float(port_summary.get("total_unrealized_pnl_pct"), 0)
        if open_positions > 0 and total_unrealized_pct < -3:
            suggestions.append(
                {
                    "id": "enforce_open_risk_rules",
                    "priority": "high",
                    "title": "对在持仓执行更严格风险阈值",
                    "reason": f"当前组合浮亏 {total_unrealized_pct:.2f}% ，仓位风险偏高。",
                    "changes": {
                        "open_position_review_frequency": "daily",
                        "trailing_stop_enabled": True,
                    },
                    "expected_effect": "降低持仓继续恶化导致的累计回撤。",
                }
            )

        if not suggestions:
            suggestions.append(
                {
                    "id": "keep_and_monitor",
                    "priority": "low",
                    "title": "当前参数可维持，持续滚动评估",
                    "reason": "当前样本下绩效与风险处于可接受区间。",
                    "changes": {"recheck_after_trades": 10},
                    "expected_effect": "保持稳定执行，避免频繁改参数造成策略漂移。",
                }
            )

        return {
            "summary": {
                "closed_roundtrips": closed,
                "win_rate": round(win_rate, 4),
                "profit_loss_ratio": round(pl_ratio, 4),
                "max_drawdown": round(max_dd, 4),
                "total_realized_return_pct": round(total_realized_return_pct, 4),
            },
            "suggested_config": cfg,
            "items": suggestions,
        }

    @staticmethod
    def _to_month_bucket(date_text: str) -> str:
        text = str(date_text or "")
        if len(text) >= 7:
            return text[:7]
        return text

    def _build_monthly_returns(self, equity_curve: List[Dict[str, Any]]) -> List[float]:
        if not equity_curve:
            return []
        month_end_values: Dict[str, float] = {}
        for point in equity_curve:
            month = self._to_month_bucket(point.get("date"))
            month_end_values[month] = self._safe_float(point.get("value"), 1.0)
        month_keys = sorted(month_end_values.keys())
        returns: List[float] = []
        for idx in range(1, len(month_keys)):
            prev = month_end_values.get(month_keys[idx - 1], 1.0)
            curr = month_end_values.get(month_keys[idx], 1.0)
            if prev > 0:
                returns.append(curr / prev - 1)
        return returns

    @staticmethod
    def _credibility_grade(score: float) -> str:
        if score >= 85:
            return "A"
        if score >= 72:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    def _assess_backtest_credibility(
        self,
        metrics: Dict[str, Any],
        diagnostics: Dict[str, Any],
        config: Dict[str, Any],
        by_state: List[Dict[str, Any]],
        equity_curve: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        closed_roundtrips = int(diagnostics.get("closed_roundtrips") or 0)
        calendar_days = int(diagnostics.get("calendar_days") or 0)
        valid_history_symbols = int(diagnostics.get("valid_history_symbols") or 0)
        universe_size = max(1, int(diagnostics.get("universe_size") or valid_history_symbols or 1))
        sharpe = self._safe_float(metrics.get("sharpe"), 0)
        max_drawdown = self._safe_float(metrics.get("max_drawdown"), 0)
        win_rate = self._safe_float(metrics.get("win_rate"), 0)
        profit_loss_ratio = self._safe_float(metrics.get("profit_loss_ratio"), 0)
        annual_return = self._safe_float(metrics.get("annual_return"), 0)

        monthly_returns = self._build_monthly_returns(equity_curve)
        monthly_count = len(monthly_returns)
        monthly_positive_ratio = (
            (sum(1 for r in monthly_returns if r > 0) / monthly_count)
            if monthly_count > 0
            else 0.0
        )
        monthly_vol = pstdev(monthly_returns) if monthly_count >= 2 else 0.0

        state_win_rates = []
        for item in (by_state or []):
            if int(item.get("sample_count") or 0) > 0:
                state_win_rates.append(self._safe_float(item.get("win_rate"), 0))
        state_dispersion = pstdev(state_win_rates) if len(state_win_rates) >= 2 else 0.0

        sample_trade_score = self._clamp((closed_roundtrips / 120.0) * 100.0, 0, 100)
        sample_days_score = self._clamp((calendar_days / 540.0) * 100.0, 0, 100)
        sample_symbol_score = self._clamp((valid_history_symbols / 180.0) * 100.0, 0, 100)
        sample_score = 0.45 * sample_trade_score + 0.35 * sample_days_score + 0.20 * sample_symbol_score

        sharpe_score = self._clamp((sharpe / 1.8) * 100.0, 0, 100)
        drawdown_score = self._clamp((0.30 - max_drawdown) / 0.30 * 100.0, 0, 100)
        win_score = self._clamp((win_rate - 0.45) / 0.20 * 100.0, 0, 100)
        pl_score = self._clamp((profit_loss_ratio / 2.0) * 100.0, 0, 100)
        return_score = self._clamp((annual_return + 0.05) / 0.35 * 100.0, 0, 100)
        risk_return_score = (
            0.30 * sharpe_score
            + 0.25 * drawdown_score
            + 0.20 * win_score
            + 0.15 * pl_score
            + 0.10 * return_score
        )

        monthly_pos_score = self._clamp((monthly_positive_ratio - 0.40) / 0.35 * 100.0, 0, 100)
        monthly_vol_score = self._clamp((0.09 - monthly_vol) / 0.09 * 100.0, 0, 100)
        state_stability_score = self._clamp((0.16 - state_dispersion) / 0.16 * 100.0, 0, 100)
        stability_score = (
            0.45 * monthly_pos_score
            + 0.35 * monthly_vol_score
            + 0.20 * state_stability_score
        )
        if monthly_count < 6:
            stability_score *= 0.55
        elif monthly_count < 9:
            stability_score *= 0.75

        mock_disabled = not bool(getattr(self.data_source_manager, "allow_mock_fallback", False))
        no_mock_score = 100.0 if mock_disabled else 35.0
        coverage_score = self._clamp((valid_history_symbols / universe_size) * 100.0, 0, 100)
        proxy_penalty = 20.0  # 历史回放中资金流仍为量价代理
        data_reality_score = self._clamp(0.65 * no_mock_score + 0.35 * coverage_score - proxy_penalty, 0, 100)

        exec_score = 78.0
        slippage = self._safe_float(config.get("slippage"), 0.001)
        commission = self._safe_float(config.get("commission"), 0.0003)
        if 0.0005 <= slippage <= 0.003:
            exec_score += 4.0
        if 0.0002 <= commission <= 0.001:
            exec_score += 2.0
        exec_score = self._clamp(exec_score, 0, 100)

        dimensions = [
            {"factor": "样本覆盖", "score": round(sample_score, 2), "weight": 0.24},
            {"factor": "风险收益质量", "score": round(risk_return_score, 2), "weight": 0.28},
            {"factor": "时序稳定性", "score": round(stability_score, 2), "weight": 0.20},
            {"factor": "数据真实性", "score": round(data_reality_score, 2), "weight": 0.18},
            {"factor": "执行可落地性", "score": round(exec_score, 2), "weight": 0.10},
        ]

        credibility_score = 0.0
        for item in dimensions:
            credibility_score += self._safe_float(item.get("score"), 0) * self._safe_float(item.get("weight"), 0)
        credibility_score = round(self._clamp(credibility_score, 0, 100), 2)
        grade = self._credibility_grade(credibility_score)

        gate_values = {
            "mock_fallback_disabled": mock_disabled,
            "closed_roundtrips": closed_roundtrips,
            "calendar_days": calendar_days,
            "valid_history_symbols": valid_history_symbols,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "profit_loss_ratio": profit_loss_ratio,
            "monthly_positive_ratio": monthly_positive_ratio,
            "monthly_count": monthly_count,
            "credibility_score": credibility_score,
        }
        gate_checks = [
            {
                "key": "mock_fallback_disabled",
                "label": "禁用Mock兜底",
                "passed": bool(gate_values["mock_fallback_disabled"]),
                "value": gate_values["mock_fallback_disabled"],
                "threshold": "必须禁用",
            },
            {
                "key": "closed_roundtrips",
                "label": "闭环交易数",
                "passed": gate_values["closed_roundtrips"] >= 80,
                "value": gate_values["closed_roundtrips"],
                "threshold": ">= 80",
            },
            {
                "key": "calendar_days",
                "label": "回测自然日",
                "passed": gate_values["calendar_days"] >= 360,
                "value": gate_values["calendar_days"],
                "threshold": ">= 360",
            },
            {
                "key": "valid_history_symbols",
                "label": "有效样本股票",
                "passed": gate_values["valid_history_symbols"] >= 120,
                "value": gate_values["valid_history_symbols"],
                "threshold": ">= 120",
            },
            {
                "key": "sharpe",
                "label": "夏普比率",
                "passed": gate_values["sharpe"] >= 1.0,
                "value": round(gate_values["sharpe"], 4),
                "threshold": ">= 1.00",
            },
            {
                "key": "max_drawdown",
                "label": "最大回撤",
                "passed": gate_values["max_drawdown"] <= 0.20,
                "value": round(gate_values["max_drawdown"], 4),
                "threshold": "<= 0.20",
            },
            {
                "key": "win_rate",
                "label": "胜率",
                "passed": gate_values["win_rate"] >= 0.54,
                "value": round(gate_values["win_rate"], 4),
                "threshold": ">= 0.54",
            },
            {
                "key": "profit_loss_ratio",
                "label": "盈亏比",
                "passed": gate_values["profit_loss_ratio"] >= 1.35,
                "value": round(gate_values["profit_loss_ratio"], 4),
                "threshold": ">= 1.35",
            },
            {
                "key": "monthly_positive_ratio",
                "label": "月度正收益占比",
                "passed": gate_values["monthly_positive_ratio"] >= 0.55,
                "value": round(gate_values["monthly_positive_ratio"], 4),
                "threshold": ">= 0.55",
            },
            {
                "key": "monthly_count",
                "label": "月度样本数",
                "passed": gate_values["monthly_count"] >= 9,
                "value": gate_values["monthly_count"],
                "threshold": ">= 9",
            },
            {
                "key": "credibility_score",
                "label": "可信度评分",
                "passed": gate_values["credibility_score"] >= 80,
                "value": round(gate_values["credibility_score"], 2),
                "threshold": ">= 80",
            },
        ]
        failed = [item for item in gate_checks if not item.get("passed")]
        live_ready = len(failed) == 0 and grade == "A"
        summary = (
            "满足实盘准入，可先小资金分层实盘。"
            if live_ready
            else "未达到实盘准入标准，继续模拟盘与滚动回测。"
        )

        return {
            "score": credibility_score,
            "grade": grade,
            "live_ready": live_ready,
            "summary": summary,
            "dimensions": dimensions,
            "gate_checks": gate_checks,
            "failed_checks": failed,
            "assumptions": {
                "money_flow_proxy_used": True,
                "buy_execution_model": "T+1 next_open_with_slippage",
                "sell_execution_model": "same_day_close_with_slippage",
                "commission_included": True,
                "slippage_included": True,
                "mock_fallback_disabled": mock_disabled,
            },
        }

    @staticmethod
    def _blend_metric(base: float, live: float, weight: float) -> float:
        return base * (1 - weight) + live * weight

    def run_backtest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        run_id = f"bt_{now.strftime('%Y%m%d_%H%M%S')}"
        user_id = payload.get("user_id", "default")
        strategy_code = payload.get("strategy_code", "trend_breakout")

        replay = self._run_historical_replay_backtest(payload=payload, user_id=user_id, strategy_code=strategy_code)
        diagnostics = replay.get("diagnostics", {})
        portfolio = self.get_paper_portfolio(user_id=user_id)
        optimization = self._build_optimization_suggestions(
            diagnostics=diagnostics,
            config=replay.get("effective_config", payload.get("config", {})),
            portfolio=portfolio,
        )
        probability_calibration = self._build_probability_calibration(diagnostics)
        closed_roundtrips = int(diagnostics.get("closed_roundtrips", 0) or 0)
        confidence_weight = self._clamp(closed_roundtrips / 20.0, 0.0, 1.0)
        by_state = replay.get("by_state") or self.get_strategy_evidence(strategy_code=strategy_code, state_tag="neutral").get("by_state", [])
        credibility = self._assess_backtest_credibility(
            metrics=replay.get("metrics", {}),
            diagnostics=diagnostics,
            config=replay.get("effective_config", payload.get("config", {})),
            by_state=by_state,
            equity_curve=replay.get("equity_curve", []),
        )

        result = {
            "run_id": run_id,
            "status": "success",
            "strategy_code": strategy_code,
            "config": replay.get("effective_config", payload.get("config", {})),
            "metrics": replay.get("metrics", {}),
            "metrics_blend_weight": round(confidence_weight, 4),
            "by_state": by_state,
            "equity_curve": replay.get("equity_curve", []),
            "drawdown_curve": replay.get("drawdown_curve", []),
            "trades": replay.get("trades", []),
            "closed_roundtrips": replay.get("closed_roundtrips", []),
            "diagnostics": {
                "source": diagnostics.get("source"),
                "trade_count": diagnostics.get("trade_count"),
                "closed_roundtrips": diagnostics.get("closed_roundtrips"),
                "avg_holding_days": diagnostics.get("avg_holding_days"),
                "avg_return_pct": diagnostics.get("avg_return_pct"),
                "total_realized_pnl": diagnostics.get("total_realized_pnl"),
                "total_realized_return_pct": diagnostics.get("total_realized_return_pct"),
                "calendar_days": diagnostics.get("calendar_days"),
                "universe_size": diagnostics.get("universe_size"),
                "valid_history_symbols": diagnostics.get("valid_history_symbols"),
            },
            "probability_calibration": probability_calibration,
            "optimization_summary": optimization.get("summary"),
            "optimization_suggestions": optimization.get("items", []),
            "suggested_config": optimization.get("suggested_config", {}),
            "paper_portfolio_snapshot": portfolio,
            "credibility": credibility,
            "live_readiness": {
                "ready": bool(credibility.get("live_ready")),
                "grade": credibility.get("grade"),
                "score": credibility.get("score"),
                "summary": credibility.get("summary"),
                "failed_checks": credibility.get("failed_checks", []),
            },
            "backtest_engine": "historical_replay_v1",
            "started_at": now_str,
            "finished_at": now_str,
        }
        self._backtest_runs[run_id] = result
        self.store.save_backtest_run(
            run_id=run_id,
            user_id=user_id,
            strategy_code=strategy_code,
            config=result.get("config", {}),
            result=result,
            status="success",
            started_at=now_str,
            finished_at=now_str,
        )
        self._invalidate_user_cache(user_id)
        return {"run_id": run_id, "status": "running"}

    def get_backtest_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._backtest_runs.get(run_id) or self.store.get_backtest_run(run_id)

    def get_weekly_lesson_latest(self, user_id: str = "default") -> Dict[str, Any]:
        recent_actions = self.store.list_pick_actions(user_id=user_id, limit=20)
        executed = sum(1 for a in recent_actions if a.get("action_type") in {"paper_buy", "closed"})
        watched = sum(1 for a in recent_actions if a.get("action_type") == "added_watchlist")
        ignored = sum(1 for a in recent_actions if a.get("action_type") == "ignored")
        portfolio_summary = self.get_paper_portfolio(user_id=user_id).get("summary", {})

        highlights = [
            "先看市场状态，再决定是否重仓",
            "先定义止损，再谈目标收益",
            "高概率不等于无风险，仓位纪律必须执行",
        ]
        mistakes = [
            "追高后未按失效条件退出",
            "防守市下仍高仓位交易",
            "忽略板块轮动导致胜率下降",
        ]
        return {
            "week_label": datetime.now().strftime("%Y-W%W"),
            "summary": {
                "executed_actions": executed,
                "watch_actions": watched,
                "ignored_actions": ignored,
                "total_actions": len(recent_actions),
                "open_positions": portfolio_summary.get("position_count", 0),
                "paper_unrealized_pnl": portfolio_summary.get("total_unrealized_pnl", 0),
            },
            "highlights": highlights,
            "mistakes": mistakes,
            "next_week_suggestions": [
                "防守状态下将单票仓位降至 6%-8%",
                "仅执行高置信度推荐",
                "严格按止损规则执行，不做主观加仓",
            ],
        }
