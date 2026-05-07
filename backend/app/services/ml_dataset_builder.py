"""
Historical training dataset construction for explainable stock scoring models.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from app.services.ml_feature_builder import MLFeatureBuilder


class MLDatasetBuilder:
    """Build panel data without using future information in feature columns."""

    FALLBACK_SYMBOLS = [
        "000001", "000333", "000338", "000651", "002594", "300059", "300750",
        "600036", "600519", "601318", "601398", "601899", "600276", "600309",
        "600900", "601012", "002415", "002475", "603288", "688981",
    ]

    def __init__(self, data_source_manager, feature_builder: Optional[MLFeatureBuilder] = None):
        self.data_source_manager = data_source_manager
        self.feature_builder = feature_builder or MLFeatureBuilder()

    @staticmethod
    def _parse_date(value: Any) -> Optional[datetime]:
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(value), fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def _is_excluded_name(name: str) -> bool:
        text = str(name or "").upper()
        return not text or "ST" in text or "退" in text

    def select_symbols(self, max_symbols: int = 120, explicit_symbols: Optional[List[str]] = None) -> List[Dict[str, str]]:
        if explicit_symbols:
            return [{"symbol": str(s).strip(), "name": str(s).strip()} for s in explicit_symbols if str(s).strip()]

        try:
            snapshot = self.data_source_manager.get_a_share_snapshot() or []
        except Exception:
            snapshot = []

        rows: List[Dict[str, Any]] = []
        for item in snapshot:
            symbol = str(item.get("symbol") or "")
            name = str(item.get("name") or symbol)
            if len(symbol) != 6 or not symbol.isdigit() or symbol[0] not in {"0", "3", "6"}:
                continue
            if self._is_excluded_name(name):
                continue
            amount = float(item.get("amount") or 0)
            price = float(item.get("price") or 0)
            if price <= 1:
                continue
            rows.append({"symbol": symbol, "name": name, "amount": amount})

        if not rows:
            return [{"symbol": s, "name": s} for s in self.FALLBACK_SYMBOLS[:max_symbols]]

        rows.sort(key=lambda x: x.get("amount", 0), reverse=True)
        return [{"symbol": row["symbol"], "name": row["name"]} for row in rows[:max_symbols]]

    def build_dataset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        horizon_days = max(5, min(60, int(payload.get("horizon_days") or 15)))
        target_return_pct = float(payload.get("target_return_pct") or 8.0)
        drawdown_pct = float(payload.get("drawdown_pct") or 6.0)
        max_symbols = max(5, min(300, int(payload.get("max_symbols") or 120)))
        sample_step = max(1, min(20, int(payload.get("sample_step") or 3)))
        end_dt = self._parse_date(payload.get("train_end")) or datetime.now()
        start_dt = self._parse_date(payload.get("train_start")) or (end_dt - timedelta(days=540))
        if start_dt >= end_dt:
            start_dt = end_dt - timedelta(days=360)
        fetch_days = max(260, min(1200, (end_dt - start_dt).days + 260))

        symbols = self.select_symbols(max_symbols=max_symbols, explicit_symbols=payload.get("symbols"))
        frames: List[pd.DataFrame] = []
        errors: List[Dict[str, str]] = []

        neutral_market = {"state_tag": "neutral", "state_score": 50.0}
        neutral_news = {"total_score": 50.0, "net_score": 0.0}
        start_text = start_dt.strftime("%Y-%m-%d")
        end_text = end_dt.strftime("%Y-%m-%d")

        for item in symbols:
            symbol = item.get("symbol")
            if not symbol:
                continue
            try:
                history = self.data_source_manager.get_history_data(symbol, days=fetch_days)
                if history is None or history.empty or len(history) < 100:
                    continue
                features = self.feature_builder.build_feature_frame(
                    history,
                    market_state=neutral_market,
                    news_factor=neutral_news,
                )
                labeled = self.feature_builder.add_forward_labels(
                    features,
                    horizon_days=horizon_days,
                    target_return_pct=target_return_pct,
                    drawdown_pct=drawdown_pct,
                )
                labeled = labeled[(labeled["date"] >= start_text) & (labeled["date"] <= end_text)].copy()
                labeled = labeled[labeled["future_return_pct"].notna() & labeled["future_max_drawdown_pct"].notna()]
                if sample_step > 1:
                    labeled = labeled.iloc[::sample_step].copy()
                if labeled.empty:
                    continue
                labeled["symbol"] = symbol
                labeled["name"] = item.get("name") or symbol
                frames.append(labeled)
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)[:160]})

        if not frames:
            return {
                "df": pd.DataFrame(),
                "samples": [],
                "meta": {
                    "symbol_count": len(symbols),
                    "valid_symbol_count": 0,
                    "sample_count": 0,
                    "errors": errors[:20],
                },
            }

        dataset = pd.concat(frames, ignore_index=True)
        dataset = dataset.sort_values(["date", "symbol"]).reset_index(drop=True)
        feature_names = self.feature_builder.FEATURE_NAMES
        keep_cols = [
            "date", "symbol", "name",
            *feature_names,
            "future_return_pct", "future_max_drawdown_pct",
            "label_up", "label_dd", "label_risk_adjusted_return",
        ]
        dataset = dataset[keep_cols].replace([float("inf"), float("-inf")], 0).fillna(0)
        samples = dataset.to_dict(orient="records")
        return {
            "df": dataset,
            "samples": samples,
            "meta": {
                "symbol_count": len(symbols),
                "valid_symbol_count": len(frames),
                "sample_count": len(dataset),
                "train_start": start_text,
                "train_end": end_text,
                "horizon_days": horizon_days,
                "target_return_pct": target_return_pct,
                "drawdown_pct": drawdown_pct,
                "sample_step": sample_step,
                "errors": errors[:20],
            },
        }
