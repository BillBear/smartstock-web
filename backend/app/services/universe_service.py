"""Candidate-universe service for the smart-pick pipeline."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from threading import RLock
from typing import Any, Dict, List, Optional


class UniverseService:
    """Build the tradable universe from validated market snapshots."""

    MIN_RELIABLE_SNAPSHOT_COUNT = 500

    def __init__(
        self,
        data_source_manager,
        market_snapshot_service=None,
        universe_refresh_seconds: int = 1200,
        universe_intraday_refresh_seconds: int = 90,
        universe_min_amount_yi: float = 2.0,
        universe_max_analyze_count: int = 120,
        universe_industry_cap: int = 4,
        universe_min_price: float = 2.0,
    ):
        self.data_source_manager = data_source_manager
        self.market_snapshot_service = market_snapshot_service
        self.universe_refresh_seconds = max(60, int(universe_refresh_seconds or 1200))
        self.universe_intraday_refresh_seconds = max(15, int(universe_intraday_refresh_seconds or 90))
        self.universe_min_amount_yi = max(0.1, float(universe_min_amount_yi or 2.0))
        self.universe_max_analyze_count = max(20, min(int(universe_max_analyze_count or 120), 220))
        self.universe_industry_cap = max(1, min(int(universe_industry_cap or 4), 10))
        self.universe_min_price = max(0.1, float(universe_min_price or 2.0))
        self._lock = RLock()
        self._state: Dict[str, Any] = {
            "entries": [],
            "entry_map": {},
            "last_full_refresh_ts": 0.0,
            "last_full_refresh_at": None,
            "last_refresh_attempt_ts": 0.0,
            "last_incremental_refresh_ts": 0.0,
            "last_incremental_refresh_at": None,
            "last_snapshot_payload": {},
            "last_meta": {},
        }

    @staticmethod
    def _now_ts() -> float:
        return datetime.now().timestamp()

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

    @staticmethod
    def _is_excluded_name(name: str) -> bool:
        if not name:
            return True
        upper = str(name).upper()
        return ("ST" in upper) or ("退" in str(name))

    @staticmethod
    def _infer_board_industry(symbol: str) -> str:
        symbol = str(symbol or "")
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

    def build_dynamic_candidates(
        self,
        risk_level: str,
        target_size: Optional[int] = None,
        strategy_code: str = "trend_breakout",
    ) -> Dict[str, Any]:
        entries = self._get_universe_snapshot(force=False)
        industry_map = self._get_industry_map()
        source_status = self._get_source_status()
        if len(entries) < self.MIN_RELIABLE_SNAPSHOT_COUNT:
            return self._build_insufficient_result(entries, industry_map, source_status)

        rules = self._get_universe_rules(risk_level)
        target_candidate_size = max(30, min(int(target_size or rules["max_analyze_count"]), 220))
        strategy = str(strategy_code or "trend_breakout")
        filtered: List[Dict[str, Any]] = []
        industries = set()

        for item in entries:
            row = self._prefilter_row(item, industry_map, rules, strategy)
            if not row:
                continue
            industries.add(row.get("industry") or "未知行业")
            filtered.append(row)

        diversified = self._diversify_by_industry(filtered, rules, target_candidate_size)
        candidates = diversified[:target_candidate_size]
        self._refresh_intraday_candidates([row["symbol"] for row in candidates])
        refreshed_candidates, full_refresh_at, incremental_refresh_at, snapshot_payload = self._merge_refreshed_quotes(candidates)

        if not refreshed_candidates:
            meta = self._build_meta(
                source="insufficient_after_prefilter",
                snapshot_count=len(entries),
                fallback_reason="全A快照可用但预筛/增量刷新后无有效候选，今日不生成正常核心候选。",
                source_status=source_status,
                total_universe_count=len(entries),
                after_prefilter_count=len(filtered),
                candidate_count=0,
                theme_watch_count=0,
                industry_count=len(industries),
                industry_map_count=len(industry_map),
                rules={**rules, "strategy_target_size": target_candidate_size},
                full_refresh_at=full_refresh_at,
                incremental_refresh_at=incremental_refresh_at,
                pipeline_counts={"snapshot": len(entries), "prefilter": len(filtered), "candidate": 0},
                trade_date=snapshot_payload.get("trade_date"),
                stale_snapshot=snapshot_payload.get("stale_snapshot"),
                stale_reason=snapshot_payload.get("stale_reason"),
            )
            return {"candidates": [], "theme_watchlist": [], "meta": meta}

        meta = self._build_meta(
            source="a_share_snapshot",
            snapshot_count=len(entries),
            fallback_reason=None,
            source_status=source_status,
            total_universe_count=len(entries),
            after_prefilter_count=len(filtered),
            candidate_count=len(refreshed_candidates),
            theme_watch_count=0,
            industry_count=len(industries),
            industry_map_count=len(industry_map),
            rules={**rules, "strategy_target_size": target_candidate_size},
            full_refresh_at=full_refresh_at,
            incremental_refresh_at=incremental_refresh_at,
            pipeline_counts={"snapshot": len(entries), "prefilter": len(filtered), "candidate": len(refreshed_candidates)},
            trade_date=snapshot_payload.get("trade_date"),
            stale_snapshot=snapshot_payload.get("stale_snapshot"),
            stale_reason=snapshot_payload.get("stale_reason"),
        )
        return {"candidates": refreshed_candidates, "theme_watchlist": [], "meta": meta}

    def _get_universe_snapshot(self, force: bool = False) -> List[Dict[str, Any]]:
        now_ts = self._now_ts()
        with self._lock:
            cache_ok = (
                not force
                and self._state["entries"]
                and (now_ts - float(self._state.get("last_full_refresh_ts") or 0) < self.universe_refresh_seconds)
            )
            if cache_ok:
                return copy.deepcopy(self._state["entries"])
            recent_attempt = now_ts - float(self._state.get("last_refresh_attempt_ts") or 0) < 120
            if recent_attempt and self._state["entries"]:
                return copy.deepcopy(self._state["entries"])
            if recent_attempt and not force:
                return []
            self._state["last_refresh_attempt_ts"] = now_ts

        items: List[Dict[str, Any]] = []
        snapshot_payload: Dict[str, Any] = {}
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._load_snapshot_payload)
        try:
            completed, _ = wait([future], timeout=8)
            if future in completed:
                result = future.result() or {}
                if isinstance(result, dict):
                    snapshot_payload = result
                    items = list((result or {}).get("items") or [])
                else:
                    items = list(result or [])
            else:
                future.cancel()
        except Exception:
            items = []
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if not items:
            with self._lock:
                return copy.deepcopy(self._state["entries"])

        entry_map = {str(item.get("symbol")): item for item in items if item.get("symbol")}
        refresh_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._state["entries"] = items
            self._state["entry_map"] = entry_map
            self._state["last_full_refresh_ts"] = now_ts
            self._state["last_full_refresh_at"] = refresh_at
            self._state["last_snapshot_payload"] = copy.deepcopy(snapshot_payload)
        return copy.deepcopy(items)

    def _load_snapshot_payload(self):
        if self.market_snapshot_service:
            return self.market_snapshot_service.ensure_snapshot_for_recommendation()
        return self.data_source_manager.get_a_share_snapshot() or []

    def _get_industry_map(self) -> Dict[str, str]:
        try:
            return self.data_source_manager.get_stock_industry_map() or {}
        except Exception:
            return {}

    def _get_source_status(self) -> Dict[str, Any]:
        try:
            return self.data_source_manager.get_health_status()
        except Exception:
            return {}

    def _get_universe_rules(self, risk_level: str) -> Dict[str, Any]:
        if risk_level == "low":
            return {
                "min_amount_yi": max(self.universe_min_amount_yi, 4.0),
                "min_turnover_rate": 0.8,
                "max_turnover_rate": 12.0,
                "max_abs_pct_change": 8.0,
                "max_analyze_count": min(max(self.universe_max_analyze_count, 90), 120),
                "industry_cap": self.universe_industry_cap,
                "min_price": self.universe_min_price,
            }
        if risk_level == "high":
            return {
                "min_amount_yi": max(self.universe_min_amount_yi * 0.5, 1.0),
                "min_turnover_rate": 0.5,
                "max_turnover_rate": 35.0,
                "max_abs_pct_change": 15.0,
                "max_analyze_count": min(max(self.universe_max_analyze_count + 60, 140), 200),
                "industry_cap": min(self.universe_industry_cap + 1, 10),
                "min_price": max(self.universe_min_price * 0.8, 1.0),
            }
        return {
            "min_amount_yi": self.universe_min_amount_yi,
            "min_turnover_rate": 0.8,
            "max_turnover_rate": 20.0,
            "max_abs_pct_change": 12.0,
            "max_analyze_count": max(self.universe_max_analyze_count, 120),
            "industry_cap": self.universe_industry_cap,
            "min_price": self.universe_min_price,
        }

    def _prefilter_row(
        self,
        item: Dict[str, Any],
        industry_map: Dict[str, str],
        rules: Dict[str, Any],
        strategy: str,
    ) -> Optional[Dict[str, Any]]:
        symbol = str(item.get("symbol") or "")
        if len(symbol) != 6 or not symbol.isdigit() or symbol[0] not in {"0", "3", "6"}:
            return None
        name = str(item.get("name") or symbol)
        if self._is_excluded_name(name):
            return None
        price = self._safe_float(item.get("price"), 0)
        if price < rules["min_price"]:
            return None
        amount_yi = self._safe_float(item.get("amount"), 0) / 100000000
        if amount_yi < rules["min_amount_yi"]:
            return None
        turnover_rate = self._safe_float(item.get("turnover_rate"), 0)
        if turnover_rate <= 0:
            circ_mv = self._safe_float(item.get("circ_mv"), 0)
            turnover_rate = self._clamp((self._safe_float(item.get("amount"), 0) / circ_mv) * 100, 0, 60) if circ_mv > 0 else self._clamp(amount_yi * 0.35, 0.2, 25)
        if turnover_rate < rules["min_turnover_rate"] or turnover_rate > rules["max_turnover_rate"]:
            return None
        pct_change = self._safe_float(item.get("pct_change"), 0)
        if abs(pct_change) > rules["max_abs_pct_change"]:
            return None

        turnover_score = self._turnover_score(turnover_rate)
        liquidity_score = self._clamp(amount_yi * 6, 0, 100)
        intraday_position = 0.5
        day_range = self._safe_float(item.get("high"), 0) - self._safe_float(item.get("low"), 0)
        if day_range > 0 and price > 0:
            intraday_position = self._clamp((price - self._safe_float(item.get("low"), 0)) / day_range, 0, 1)
        if strategy == "pullback_rebound":
            momentum_score = self._clamp(12 - abs(pct_change + 1.8), 0, 12)
            intraday_score = self._clamp((1 - abs(intraday_position - 0.45)) * 100, 0, 100)
            pre_score = 0.34 * liquidity_score + 0.24 * turnover_score + 0.22 * intraday_score + 0.20 * (momentum_score * 8.2)
        else:
            momentum_score = self._clamp(50 + pct_change * 7.5 - max(pct_change - 7.5, 0) * 8.0, 0, 100)
            intraday_score = self._clamp((0.25 + intraday_position) * 80, 0, 100)
            pre_score = 0.34 * liquidity_score + 0.22 * turnover_score + 0.18 * intraday_score + 0.26 * momentum_score

        industry = str(industry_map.get(symbol) or item.get("industry") or self._infer_board_industry(symbol)).strip()
        row = copy.deepcopy(item)
        row["turnover_rate"] = turnover_rate
        row["industry"] = industry
        row["pre_score"] = round(pre_score, 4)
        return row

    @staticmethod
    def _turnover_score(turnover_rate: float) -> float:
        if turnover_rate <= 2:
            score = 45 + turnover_rate * 6
        elif turnover_rate <= 10:
            score = 57 + (turnover_rate - 2) * 3.5
        elif turnover_rate <= 20:
            score = 85 - (turnover_rate - 10) * 2
        else:
            score = 65 - (turnover_rate - 20) * 2
        return max(0.0, min(100.0, score))

    def _diversify_by_industry(
        self,
        filtered: List[Dict[str, Any]],
        rules: Dict[str, Any],
        target_candidate_size: int,
    ) -> List[Dict[str, Any]]:
        by_industry: Dict[str, List[Dict[str, Any]]] = {}
        for row in filtered:
            by_industry.setdefault(row.get("industry", "未知行业"), []).append(row)
        diversified: List[Dict[str, Any]] = []
        industry_cap = max(int(rules["industry_cap"]), min(10, max(2, target_candidate_size // 28)))
        for industry_rows in by_industry.values():
            industry_rows.sort(key=lambda x: x.get("pre_score", 0), reverse=True)
            diversified.extend(industry_rows[:industry_cap])
        diversified.sort(key=lambda x: x.get("pre_score", 0), reverse=True)
        return diversified

    def _refresh_intraday_candidates(self, symbols: List[str]) -> None:
        now_ts = self._now_ts()
        with self._lock:
            if now_ts - float(self._state.get("last_incremental_refresh_ts") or 0) < self.universe_intraday_refresh_seconds:
                return
            entry_map = copy.deepcopy(self._state.get("entry_map") or {})

        quotes_map = self.data_source_manager.get_realtime_quotes_batch(symbols[: min(80, len(symbols))])
        changed = 0
        for symbol, quote in (quotes_map or {}).items():
            prev = entry_map.get(symbol, {})
            prev.update(
                {
                    "symbol": symbol,
                    "name": quote.get("name", prev.get("name", symbol)),
                    "price": self._safe_float(quote.get("price"), prev.get("price") or 0),
                    "change": self._safe_float(quote.get("change"), prev.get("change") or 0),
                    "pct_change": self._safe_float(quote.get("pct_change"), prev.get("pct_change") or 0),
                    "open": self._safe_float(quote.get("open"), prev.get("open") or 0),
                    "high": self._safe_float(quote.get("high"), prev.get("high") or 0),
                    "low": self._safe_float(quote.get("low"), prev.get("low") or 0),
                    "volume": self._safe_float(quote.get("volume"), prev.get("volume") or 0),
                    "amount": self._safe_float(quote.get("amount"), prev.get("amount") or 0),
                    "turnover_rate": self._safe_float(quote.get("turnover_rate"), prev.get("turnover_rate") or 0),
                    "update_time": quote.get("update_time"),
                    "industry": prev.get("industry", "未知行业"),
                }
            )
            entry_map[symbol] = prev
            changed += 1

        if changed <= 0:
            return
        with self._lock:
            self._state["entry_map"] = entry_map
            self._state["entries"] = list(entry_map.values())
            self._state["last_incremental_refresh_ts"] = now_ts
            self._state["last_incremental_refresh_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _merge_refreshed_quotes(self, candidates: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Optional[str], Optional[str], Dict[str, Any]]:
        with self._lock:
            entry_map = copy.deepcopy(self._state.get("entry_map") or {})
            full_refresh_at = self._state.get("last_full_refresh_at")
            incremental_refresh_at = self._state.get("last_incremental_refresh_at")
            snapshot_payload = copy.deepcopy(self._state.get("last_snapshot_payload") or {})
        rows = []
        for row in candidates:
            merged = copy.deepcopy(row)
            latest = entry_map.get(row["symbol"])
            if latest:
                merged.update(latest)
            rows.append(merged)
        return rows, full_refresh_at, incremental_refresh_at, snapshot_payload

    def _build_insufficient_result(
        self,
        entries: List[Dict[str, Any]],
        industry_map: Dict[str, str],
        source_status: Dict[str, Any],
    ) -> Dict[str, Any]:
        meta = self._build_meta(
            source="insufficient_snapshot",
            snapshot_count=len(entries),
            fallback_reason=f"全A快照样本量不足（{len(entries)} < {self.MIN_RELIABLE_SNAPSHOT_COUNT}），不生成正常核心候选。",
            source_status=source_status,
            total_universe_count=len(entries),
            after_prefilter_count=0,
            candidate_count=0,
            theme_watch_count=0,
            industry_count=0,
            industry_map_count=len(industry_map),
            rules={},
            full_refresh_at=self._state.get("last_full_refresh_at"),
            incremental_refresh_at=self._state.get("last_incremental_refresh_at"),
            pipeline_counts={"snapshot": len(entries), "prefilter": 0, "candidate": 0},
            trade_date=(self._state.get("last_snapshot_payload") or {}).get("trade_date"),
            stale_snapshot=(self._state.get("last_snapshot_payload") or {}).get("stale_snapshot"),
            stale_reason=(self._state.get("last_snapshot_payload") or {}).get("stale_reason"),
        )
        return {"candidates": [], "theme_watchlist": [], "meta": meta}

    def _build_meta(self, **kwargs) -> Dict[str, Any]:
        meta = {
            "source": kwargs["source"],
            "trade_date": kwargs.get("trade_date"),
            "stale_snapshot": bool(kwargs.get("stale_snapshot")),
            "stale_reason": kwargs.get("stale_reason"),
            "snapshot_count": kwargs["snapshot_count"],
            "fallback_reason": kwargs["fallback_reason"],
            "data_source_status": kwargs["source_status"],
            "total_universe_count": kwargs["total_universe_count"],
            "after_prefilter_count": kwargs["after_prefilter_count"],
            "candidate_count": kwargs["candidate_count"],
            "theme_watch_count": kwargs["theme_watch_count"],
            "industry_count": kwargs["industry_count"],
            "industry_map_count": kwargs["industry_map_count"],
            "rules": kwargs["rules"],
            "full_refresh_at": kwargs["full_refresh_at"],
            "incremental_refresh_at": kwargs["incremental_refresh_at"],
            "pipeline_counts": kwargs["pipeline_counts"],
        }
        with self._lock:
            self._state["last_meta"] = copy.deepcopy(meta)
        return meta
