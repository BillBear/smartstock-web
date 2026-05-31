"""
Centralized data-quality semantics for recommendation and money-flow outputs.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional


class DataQualityService:
    MIN_RELIABLE_SNAPSHOT_COUNT = 500

    def __init__(self, data_source_manager=None, store=None, min_snapshot_count: int = MIN_RELIABLE_SNAPSHOT_COUNT):
        self.data_source_manager = data_source_manager
        self.store = store
        self.min_snapshot_count = max(1, int(min_snapshot_count or self.MIN_RELIABLE_SNAPSHOT_COUNT))

    def build_recommendation_quality(
        self,
        picks: List[Dict[str, Any]],
        universe_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        universe_meta = universe_meta or {}
        picks = picks or []
        snapshot_count = int(float(universe_meta.get("snapshot_count") or 0))
        source = str(universe_meta.get("source") or "")
        fallback_reason = universe_meta.get("fallback_reason")
        is_fallback = source.startswith("fallback_")
        snapshot_status = "ok"
        if is_fallback:
            snapshot_status = "fallback"
        if snapshot_count < self.min_snapshot_count:
            snapshot_status = "insufficient_data"

        real_count = len([p for p in picks if p.get("money_flow_quality") == "real"])
        proxy_count = len([p for p in picks if p.get("money_flow_quality") == "proxy"])
        unavailable_count = len([p for p in picks if p.get("money_flow_quality") == "unavailable"])
        total = len(picks)
        money_flow_quality = {
            "real": real_count,
            "proxy": proxy_count,
            "unavailable": unavailable_count,
            "total": total,
        }
        payload = {
            "snapshot_status": snapshot_status,
            "snapshot_count": snapshot_count,
            "min_reliable_snapshot_count": self.min_snapshot_count,
            "fallback_reason": fallback_reason,
            "is_reliable": snapshot_status == "ok",
            "money_flow_quality": money_flow_quality,
            "money_flow_coverage": round(real_count / total, 4) if total else 0,
            "diagnostic_mode": "hidden",
        }
        self._persist("recommendation", payload["snapshot_status"], payload)
        return payload

    def current_trade_date(self, fallback: Optional[str] = None) -> str:
        """Return the latest reliable market trading date instead of wall-clock date."""
        fallback_date = fallback or datetime.now().strftime("%Y-%m-%d")
        if not self.store:
            return fallback_date
        try:
            snapshot = self.store.get_latest_valid_market_snapshot(min_count=self.min_snapshot_count)
        except Exception:
            snapshot = None
        if not snapshot:
            return fallback_date
        return self._infer_snapshot_trade_date(snapshot, fallback=fallback_date)

    def build_money_flow_coverage(self, trade_date: Optional[str] = None) -> Dict[str, Any]:
        if not self.data_source_manager:
            return {
                "status": "degraded",
                "coverage_label": "资金流数据源未初始化",
                "cached_symbol_count": 0,
                "sources": [],
                "quality_levels": self.quality_levels(),
            }
        effective_trade_date = self.current_trade_date(trade_date)
        payload = self.data_source_manager.get_money_flow_coverage_status()
        payload["trade_date"] = effective_trade_date
        persisted_counts = {}
        if self.store:
            try:
                persisted_counts = self.store.get_money_flow_snapshot_quality_counts(effective_trade_date)
            except Exception:
                persisted_counts = {}
        if persisted_counts:
            payload["persisted_quality_counts"] = persisted_counts
            payload["real_persisted_symbol_count"] = int(persisted_counts.get("real") or 0)
            payload["proxy_persisted_symbol_count"] = int(persisted_counts.get("proxy") or 0)
            payload["unavailable_persisted_symbol_count"] = int(persisted_counts.get("unavailable") or 0)
        self._persist("money_flow", payload.get("status") or "unknown", payload, trade_date=effective_trade_date)
        return payload

    @staticmethod
    def quality_levels() -> List[Dict[str, str]]:
        return [
            {"key": "real", "label": "真实资金流", "description": "来自具备个股资金流能力的数据源。"},
            {"key": "proxy", "label": "代理资金强度", "description": "真实接口不可用时由成交额、涨跌幅和换手率构造。"},
            {"key": "unavailable", "label": "暂不可用", "description": "不参与资金评分，不显示为 0 分。"},
        ]

    def _persist(
        self,
        scope: str,
        status: str,
        payload: Dict[str, Any],
        trade_date: Optional[str] = None,
    ) -> None:
        if not self.store:
            return
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.store.upsert_data_quality_snapshot(
                trade_date=trade_date or self.current_trade_date(),
                scope=scope,
                status=status,
                payload=payload,
                created_at=now,
            )
        except Exception:
            return

    @staticmethod
    def _infer_snapshot_trade_date(snapshot: Dict[str, Any], fallback: str) -> str:
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
        trade_date = str((snapshot or {}).get("trade_date") or "").strip()
        return trade_date or fallback
