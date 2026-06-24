"""
Persistent market snapshot service.

This service is the stable data base for smart-pick recommendations.  It keeps
external data-source volatility out of request-time ranking code.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional


class MarketDataSnapshotService:
    MIN_RELIABLE_SNAPSHOT_COUNT = 500

    def __init__(self, data_source_manager, store, min_reliable_count: int = MIN_RELIABLE_SNAPSHOT_COUNT):
        self.data_source_manager = data_source_manager
        self.store = store
        self.min_reliable_count = max(1, int(min_reliable_count or self.MIN_RELIABLE_SNAPSHOT_COUNT))

    def get_latest_valid_snapshot(self, trade_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.store.get_latest_valid_market_snapshot(trade_date=trade_date, min_count=self.min_reliable_count)

    def refresh_today_snapshot(self, force: bool = False) -> Dict[str, Any]:
        try:
            items: List[Dict[str, Any]] = self.data_source_manager.get_a_share_snapshot(force=force) or []
        except TypeError:
            items = self.data_source_manager.get_a_share_snapshot() or []
        trade_date = self._infer_trade_date(items)
        cached = None if force else self.get_latest_valid_snapshot(trade_date)
        if cached and cached.get("trade_date") == trade_date:
            return cached

        source = self._infer_snapshot_source(items)
        count = len(items)
        status = "ok" if count >= self.min_reliable_count else "insufficient_data"
        meta = {
            "snapshot_count": count,
            "min_reliable_count": self.min_reliable_count,
            "source": source,
            "is_reliable": status == "ok",
            "created_by": "MarketDataSnapshotService",
        }
        saved = self.store.upsert_market_snapshot(
            trade_date=trade_date,
            source=source,
            items=items,
            quality_status=status,
            meta=meta,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        saved["meta"] = meta
        saved["items"] = items
        return saved

    def ensure_snapshot_for_recommendation(self, trade_date: Optional[str] = None) -> Dict[str, Any]:
        trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
        snapshot = self.get_latest_valid_snapshot(trade_date)
        snapshot_trade_date = str((snapshot or {}).get("trade_date") or "")
        if snapshot and snapshot_trade_date >= trade_date:
            return {**snapshot, "is_reliable": True}

        refreshed = self.refresh_today_snapshot(force=bool(snapshot))
        refreshed["is_reliable"] = int(refreshed.get("snapshot_count") or 0) >= self.min_reliable_count
        if not refreshed["is_reliable"] and snapshot:
            restored = {**snapshot, "is_reliable": True}
            restored["stale_snapshot"] = True
            restored["stale_reason"] = "最新全A快照重建失败，临时回退到最近有效快照。"
            return restored
        return refreshed

    @staticmethod
    def _infer_snapshot_source(items: List[Dict[str, Any]]) -> str:
        for item in items or []:
            source = item.get("source") or item.get("data_source")
            if source:
                return str(source)
        return "a_share_snapshot" if items else "empty"

    @staticmethod
    def _infer_trade_date(items: List[Dict[str, Any]]) -> str:
        fallback = datetime.now().strftime("%Y-%m-%d")
        dates: List[str] = []
        for item in (items or [])[: min(len(items or []), 300)]:
            raw = item.get("trade_date") or item.get("date") or item.get("update_time")
            text = str(raw or "").strip()
            if len(text) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", text):
                dates.append(text[:10])
            elif len(text) >= 8 and re.match(r"^\d{8}", text):
                dates.append(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
        return max(dates) if dates else fallback
