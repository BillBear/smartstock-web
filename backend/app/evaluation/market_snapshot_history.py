"""History adapter backed by persisted full-market snapshots.

This read-only adapter lets ranking labels use local `market_snapshot_items`
before falling back to live history providers. It does not generate picks,
refresh snapshots, or change production strategy decisions.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import text


class MarketSnapshotHistoryProvider:
    def __init__(self, store, fallback=None, min_count: int = 500):
        self.store = store
        self.fallback = fallback
        self.min_count = max(1, int(min_count or 1))
        self._cache: Dict[str, pd.DataFrame] = {}

    def get_history_data_range(self, symbol: Any, start_date: str, end_date: str) -> pd.DataFrame:
        normalized_symbol = str(symbol or "").strip()
        normalized_start = _normalize_date(start_date) or str(start_date)
        normalized_end = _normalize_date(end_date) or str(end_date)
        cache_key = f"{normalized_symbol}:{normalized_start}:{normalized_end}"
        if cache_key not in self._cache:
            history = self._load_snapshot_history(normalized_symbol, normalized_start, normalized_end)
            if history.empty and self.fallback and hasattr(self.fallback, "get_history_data_range"):
                history = self.fallback.get_history_data_range(
                    normalized_symbol,
                    start_date=normalized_start,
                    end_date=normalized_end,
                )
            self._cache[cache_key] = _normalize_history(history)
        return self._cache[cache_key].copy()

    def _load_snapshot_history(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        if not self.store or not hasattr(self.store, "engine"):
            return pd.DataFrame()
        sql = text(
            """
            SELECT msi.trade_date, msi.symbol, msi.name, msi.industry, msi.item_json
            FROM market_snapshot_items msi
            JOIN market_snapshots ms ON ms.snapshot_id = msi.snapshot_id
            WHERE msi.symbol = :symbol
              AND msi.trade_date >= :start_date
              AND msi.trade_date <= :end_date
              AND ms.snapshot_count >= :min_count
            ORDER BY msi.trade_date ASC, msi.created_at DESC
            """
        )
        with self.store.engine.connect() as conn:
            rows = conn.execute(
                sql,
                {
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "min_count": self.min_count,
                },
            ).fetchall()
        by_date: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            record = dict(row._mapping)
            trade_date = _normalize_date(record.get("trade_date"))
            if not trade_date or trade_date in by_date:
                continue
            payload = _decode_payload(record.get("item_json"))
            by_date[trade_date] = _snapshot_item_to_history_row(
                trade_date=trade_date,
                symbol=symbol,
                name=record.get("name"),
                industry=record.get("industry"),
                payload=payload,
            )
        return pd.DataFrame(list(by_date.values()))


def _snapshot_item_to_history_row(
    trade_date: str,
    symbol: str,
    name: Optional[str],
    industry: Optional[str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    close = _safe_float(payload.get("close"), _safe_float(payload.get("price"), 0.0))
    open_price = _safe_float(payload.get("open"), close)
    high = _safe_float(payload.get("high"), max(open_price, close))
    low = _safe_float(payload.get("low"), min(open_price, close))
    volume = _safe_float(payload.get("volume"), 0.0)
    amount = _safe_float(payload.get("amount"), 0.0)
    pct_change = _safe_float(
        payload.get("pct_change"),
        _safe_float(payload.get("pct_chg"), _safe_float(payload.get("change_percent"), 0.0)),
    )
    return {
        "date": trade_date,
        "symbol": symbol,
        "name": payload.get("name") or name or symbol,
        "industry": payload.get("industry") or industry or "未知行业",
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "pct_change": pct_change,
    }


def _normalize_history(history: Any) -> pd.DataFrame:
    if history is None:
        return pd.DataFrame()
    rows = history.copy() if hasattr(history, "copy") else pd.DataFrame(history)
    if rows.empty:
        return pd.DataFrame()
    if "date" in rows.columns:
        rows["date"] = rows["date"].map(_normalize_date)
        rows = rows.dropna(subset=["date"])
    for column in ("open", "high", "low", "close", "volume", "amount", "pct_change"):
        if column not in rows.columns:
            rows[column] = 0.0
        rows[column] = pd.to_numeric(rows[column], errors="coerce").fillna(0.0)
    return rows.sort_values("date").reset_index(drop=True)


def _decode_payload(raw: Any) -> Dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value).strip()
    if not text_value:
        return None
    for fmt, width in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(text_value[:width], fmt).date().isoformat()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(text_value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(parsed):
        return default
    return parsed
