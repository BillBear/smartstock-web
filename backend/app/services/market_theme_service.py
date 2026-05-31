"""
Dynamic market theme discovery and drill-down.

Market themes must come from board/concept level data first. Small fallback
samples are treated as insufficient instead of being shown as market hotspots.
"""
from __future__ import annotations

import copy
import hashlib
import re
import time
from datetime import datetime
from statistics import mean
from typing import Any, Dict, List, Optional


class MarketThemeService:
    """Build a dynamic theme ranking from board/concept and fund-flow data."""

    MIN_RELIABLE_MARKET_SAMPLE = 500
    MIN_RELIABLE_THEME_COUNT = 5

    def __init__(self, data_source_manager, store=None, cache_ttl_seconds: int = 300):
        self.data_source_manager = data_source_manager
        self.store = store
        self.cache_ttl_seconds = max(30, int(cache_ttl_seconds or 300))
        self._cache: Dict[str, Any] = {"expires_at": 0.0, "data": None}
        self._theme_lookup: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _theme_id(category: str, theme_name: str) -> str:
        digest = hashlib.sha1(f"{category}:{theme_name}".encode("utf-8")).hexdigest()[:12]
        return f"{category}_{digest}"

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

    def _current_trade_date(self) -> str:
        fallback = datetime.now().strftime("%Y-%m-%d")
        if not self.store:
            return fallback
        try:
            snapshot = self.store.get_latest_valid_market_snapshot(min_count=self.MIN_RELIABLE_MARKET_SAMPLE)
        except Exception:
            snapshot = None
        if not snapshot:
            return fallback
        items = list((snapshot or {}).get("items") or [])
        dates: List[str] = []
        for item in items[: min(len(items), 300)]:
            raw = item.get("trade_date") or item.get("date") or item.get("update_time")
            text = str(raw or "").strip()
            if len(text) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", text):
                dates.append(text[:10])
            elif len(text) >= 8 and re.match(r"^\d{8}", text):
                dates.append(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
        if dates:
            return max(dates)
        return str(snapshot.get("trade_date") or fallback)

    def get_today_themes(self, force: bool = False, limit: int = 12) -> Dict[str, Any]:
        now = time.time()
        if not force and self._cache.get("data") is not None and now < float(self._cache.get("expires_at") or 0):
            return copy.deepcopy(self._cache["data"])

        boards = self.data_source_manager.get_market_theme_boards() or []
        if boards:
            themes = self._rank_board_themes(boards, limit=max(1, min(int(limit or 12), 30)))
            market_sample_count = sum(int(self._safe_float(item.get("stock_count"), 0)) for item in boards)
            is_reliable = len(themes) >= self.MIN_RELIABLE_THEME_COUNT and market_sample_count >= self.MIN_RELIABLE_MARKET_SAMPLE
            payload = self._build_payload(
                themes=themes if is_reliable else [],
                status="ok" if is_reliable else "insufficient_data",
                source="akshare_board_fund_flow",
                market_sample_count=market_sample_count,
                raw_theme_count=len(boards),
                message=(
                    "市场主线来自概念/行业板块资金流、涨跌幅和领涨股。"
                    if is_reliable
                    else "板块数据样本不足，暂不展示市场主线，避免误导。"
                ),
            )
            return payload

        snapshot = self.data_source_manager.get_a_share_snapshot() or []
        industry_map = self.data_source_manager.get_stock_industry_map() or {}
        snapshot_themes = self._rank_snapshot_themes(snapshot, industry_map, limit=max(1, min(int(limit or 12), 30)))
        is_reliable = len(snapshot) >= self.MIN_RELIABLE_MARKET_SAMPLE and len(snapshot_themes) >= self.MIN_RELIABLE_THEME_COUNT
        payload = self._build_payload(
            themes=snapshot_themes if is_reliable else [],
            status="ok" if is_reliable else "insufficient_data",
            source="a_share_snapshot" if snapshot else "empty_snapshot",
            market_sample_count=len(snapshot),
            raw_theme_count=len(snapshot_themes),
            message=(
                "市场主线来自全A快照聚合。"
                if is_reliable
                else "真实板块/全A样本不足，暂不展示市场主线。"
            ),
        )
        return payload

    def get_theme_stocks(self, theme_id: str, limit: int = 80) -> Dict[str, Any]:
        theme = self._resolve_theme(theme_id)
        if not theme:
            return {
                "status": "not_found",
                "theme": None,
                "stocks": [],
                "message": "主题不存在或缓存已过期，请刷新市场主线。",
            }

        fallback_rows = [
            {
                "symbol": item.get("symbol") or self._resolve_symbol_by_name(item.get("name")),
                "name": item.get("name"),
                "pct_change": item.get("pct_change"),
                "amount": self._safe_float(item.get("amount_yi"), 0) * 100000000,
                "turnover_rate": None,
            }
            for item in theme.get("top_symbols") or []
        ]
        rows = self.data_source_manager.get_theme_constituents(theme["theme_name"], theme.get("category") or "concept") or []
        source = "constituents"
        if not rows:
            rows = self._theme_rows_from_snapshot(theme, limit=max(1, min(int(limit or 80), 200)))
            source = "snapshot_match" if rows else "leader_fallback"
        if not rows:
            rows = fallback_rows
        normalized = []
        for item in rows[: max(1, min(int(limit or 80), 200))]:
            symbol = str(item.get("symbol") or "")
            normalized.append(
                {
                    "symbol": symbol,
                    "name": item.get("name") or symbol,
                    "price": self._safe_float(item.get("price"), 0),
                    "pct_change": round(self._safe_float(item.get("pct_change"), 0), 2),
                    "amount_yi": round(self._safe_float(item.get("amount"), 0) / 100000000, 2),
                    "turnover_rate": None if item.get("turnover_rate") is None else round(self._safe_float(item.get("turnover_rate"), 0), 2),
                    "money_flow_quality": "unavailable",
                    "selected": False,
                    "exclusion_reason": "主题成分股，尚未进入当前策略核心候选。",
                }
            )
        normalized.sort(key=lambda row: (row.get("pct_change") or 0, row.get("amount_yi") or 0), reverse=True)
        return {
            "status": "ok" if normalized and source == "constituents" else ("partial" if normalized else "empty"),
            "trade_date": self._current_trade_date(),
            "theme": theme,
            "stocks": normalized,
            "stock_count": len(normalized),
            "source": source,
            "message": (
                "主题成分股来自板块/概念接口；是否入选还要看风险、资金、趋势和流动性闸门。"
                if source == "constituents"
                else (
                    "成分股接口暂不可用，当前用全A快照按板块/行业名称匹配，排序仅作观察。"
                    if source == "snapshot_match"
                    else "成分股接口暂不可用，当前仅展示板块资金流返回的领涨代表股。"
                )
            ),
        }

    def _resolve_symbol_by_name(self, name: Optional[str]) -> Optional[str]:
        stock_name = str(name or "").strip()
        if not stock_name:
            return None
        try:
            basic_map = self.data_source_manager.get_stock_basic_map() or {}
        except Exception:
            basic_map = {}
        for symbol, row in basic_map.items():
            if str((row or {}).get("name") or "").strip() == stock_name:
                return str(symbol)
        return None

    def _theme_rows_from_snapshot(self, theme: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        theme_name = str((theme or {}).get("theme_name") or "").strip()
        if not theme_name:
            return []
        snapshot = []
        if self.store and hasattr(self.store, "get_latest_valid_market_snapshot"):
            try:
                persisted = self.store.get_latest_valid_market_snapshot(min_count=self.MIN_RELIABLE_MARKET_SAMPLE) or {}
                snapshot = persisted.get("items") or []
            except Exception:
                snapshot = []
        if not snapshot:
            try:
                snapshot = self.data_source_manager.get_a_share_snapshot() or []
            except Exception:
                snapshot = []
        try:
            industry_map = self.data_source_manager.get_stock_industry_map() or {}
        except Exception:
            industry_map = {}
        rows: List[Dict[str, Any]] = []
        for item in snapshot:
            symbol = str(item.get("symbol") or item.get("code") or "").strip()
            if len(symbol) != 6 or not symbol.isdigit():
                continue
            name = str(item.get("name") or symbol).strip()
            industry = str(item.get("industry") or industry_map.get(symbol) or "").strip()
            concept = str(item.get("concept") or item.get("theme") or "").strip()
            haystack = f"{industry} {concept} {name}"
            if theme_name not in haystack:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "price": self._safe_float(item.get("price") or item.get("current_price"), 0),
                    "pct_change": self._safe_float(item.get("pct_change") or item.get("change_percent"), 0),
                    "amount": self._safe_float(item.get("amount") or item.get("turnover"), 0),
                    "turnover_rate": item.get("turnover_rate"),
                }
            )
        rows.sort(key=lambda row: (row.get("pct_change") or 0, row.get("amount") or 0), reverse=True)
        return rows[:limit]

    def _build_payload(
        self,
        themes: List[Dict[str, Any]],
        status: str,
        source: str,
        market_sample_count: int,
        raw_theme_count: int,
        message: str,
    ) -> Dict[str, Any]:
        trade_date = self._current_trade_date()
        for theme in themes or []:
            for item in theme.get("top_symbols") or []:
                if not item.get("symbol"):
                    item["symbol"] = self._resolve_symbol_by_name(item.get("name"))
        self._theme_lookup = {item["theme_id"]: copy.deepcopy(item) for item in themes}
        if self.store and themes:
            try:
                self.store.upsert_theme_snapshots(
                    trade_date=trade_date,
                    themes=themes,
                    created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception:
                pass
        payload = {
            "status": status,
            "trade_date": trade_date,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "theme_rank": themes,
            "theme_count": len(themes),
            "market_sample_count": market_sample_count,
            "message": message,
            "data_quality": {
                "source": source,
                "market_sample_count": market_sample_count,
                "theme_count": len(themes),
                "raw_theme_count": raw_theme_count,
                "is_reliable": status == "ok",
            },
        }
        self._cache = {"expires_at": time.time() + self.cache_ttl_seconds, "data": copy.deepcopy(payload)}
        return payload

    def _resolve_theme(self, theme_id: str) -> Optional[Dict[str, Any]]:
        if theme_id in self._theme_lookup:
            return copy.deepcopy(self._theme_lookup[theme_id])
        cached = self.get_today_themes(force=False, limit=30)
        for item in cached.get("theme_rank") or []:
            if item.get("theme_id") == theme_id:
                return copy.deepcopy(item)
        return None

    def _rank_board_themes(self, boards: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        ranked = []
        for row in boards:
            theme_name = str(row.get("theme_name") or "").strip()
            if not theme_name:
                continue
            category = str(row.get("category") or "concept")
            pct_change = self._safe_float(row.get("pct_change"), 0)
            money_net = self._safe_float(row.get("money_net_inflow_yi"), 0)
            amount_yi = self._safe_float(row.get("amount_yi"), 0)
            stock_count = int(self._safe_float(row.get("stock_count"), 0))
            leader_pct = self._safe_float(row.get("leader_pct_change"), 0)
            breadth = max(0.0, min(1.0, 0.45 + pct_change / 12.0 + max(money_net, 0) / max(amount_yi, 1) * 0.18))
            money_flow_score = max(0.0, min(100.0, 50 + money_net * 1.8 + pct_change * 4 + min(amount_yi / 120, 12)))
            strength_score = max(0.0, min(100.0, 42 + pct_change * 8 + breadth * 20 + min(max(money_net, 0) * 1.2, 16) + min(leader_pct, 20) * 0.35))
            retreat_risk = max(0.0, min(100.0, max(pct_change - 5, 0) * 10 + max(leader_pct - 10, 0) * 2.5))
            theme_id = self._theme_id(category, theme_name)
            top_symbols = []
            if row.get("leader_name"):
                top_symbols.append(
                    {
                        "symbol": None,
                        "name": row.get("leader_name"),
                        "pct_change": round(leader_pct, 2),
                        "amount_yi": None,
                    }
                )
            ranked.append(
                {
                    "theme_id": theme_id,
                    "theme_name": theme_name,
                    "category": category,
                    "pct_change": round(pct_change, 2),
                    "strength_score": round(strength_score, 2),
                    "money_flow_score": round(money_flow_score, 2),
                    "money_net_inflow_yi": round(money_net, 2),
                    "breadth": round(breadth, 4),
                    "volume_ratio": round(max(0.2, min(amount_yi / max(stock_count, 1) / 8, 5.0)), 2),
                    "new_high_count": 1 if leader_pct >= 9.5 else 0,
                    "trend_days": 1 if pct_change > 0 else 0,
                    "retreat_risk": round(retreat_risk, 2),
                    "stock_count": stock_count,
                    "amount_yi": round(amount_yi, 2),
                    "top_symbols": top_symbols,
                }
            )
        ranked.sort(key=lambda item: (item["strength_score"], item["money_flow_score"], item["pct_change"]), reverse=True)
        return ranked[:limit]

    def _rank_snapshot_themes(
        self,
        entries: List[Dict[str, Any]],
        industry_map: Dict[str, str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in entries:
            symbol = str(row.get("symbol") or row.get("code") or "")
            if len(symbol) != 6 or not symbol.isdigit():
                continue
            name = str(row.get("name") or symbol)
            if "ST" in name.upper() or "退" in name:
                continue
            theme_name = str(row.get("concept") or row.get("theme") or row.get("industry") or industry_map.get(symbol) or self._infer_board_industry(symbol)).strip()
            if not theme_name or theme_name == "未知行业":
                continue
            grouped.setdefault(theme_name, []).append(
                {
                    "symbol": symbol,
                    "name": name,
                    "pct_change": self._safe_float(row.get("pct_change"), 0),
                    "amount": self._safe_float(row.get("amount"), 0),
                    "turnover_rate": self._safe_float(row.get("turnover_rate"), 0),
                }
            )

        ranked = []
        for theme_name, rows in grouped.items():
            if len(rows) < 3:
                continue
            pct_values = [self._safe_float(item.get("pct_change"), 0) for item in rows]
            amounts = [max(self._safe_float(item.get("amount"), 0), 0) for item in rows]
            avg_change = mean(pct_values) if pct_values else 0
            up_ratio = len([v for v in pct_values if v > 0]) / len(pct_values)
            amount_yi = sum(amounts) / 100000000
            top_symbols = sorted(rows, key=lambda item: (item.get("pct_change") or 0, item.get("amount") or 0), reverse=True)[:5]
            category = "industry"
            ranked.append(
                {
                    "theme_id": self._theme_id(category, theme_name),
                    "theme_name": theme_name,
                    "category": category,
                    "pct_change": round(avg_change, 2),
                    "strength_score": round(max(0.0, min(100.0, 38 + avg_change * 7.5 + up_ratio * 24 + min(amount_yi / 120, 18))), 2),
                    "money_flow_score": round(max(0.0, min(100.0, 45 + avg_change * 5 + min(amount_yi / 80, 20))), 2),
                    "money_net_inflow_yi": None,
                    "breadth": round(up_ratio, 4),
                    "volume_ratio": 1.0,
                    "new_high_count": len([v for v in pct_values if v >= 6]),
                    "trend_days": 1 if avg_change > 0 else 0,
                    "retreat_risk": round(max(0.0, min(100.0, max(avg_change - 5, 0) * 8)), 2),
                    "stock_count": len(rows),
                    "amount_yi": round(amount_yi, 2),
                    "top_symbols": [
                        {
                            "symbol": item["symbol"],
                            "name": item["name"],
                            "pct_change": round(self._safe_float(item.get("pct_change"), 0), 2),
                            "amount_yi": round(self._safe_float(item.get("amount"), 0) / 100000000, 2),
                        }
                        for item in top_symbols
                    ],
                }
            )
        ranked.sort(key=lambda item: (item["strength_score"], item["money_flow_score"], item["amount_yi"]), reverse=True)
        return ranked[:limit]
