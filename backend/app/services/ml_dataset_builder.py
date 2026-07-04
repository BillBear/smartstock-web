"""
Historical training dataset construction for explainable stock scoring models.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from app.evaluation.ml_splits import build_ml_split_plan
from app.services.ml_feature_builder import MLFeatureBuilder


class MLDatasetBuilder:
    """Build panel data without using future information in feature columns."""

    MAX_SYMBOLS = 5000

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
        max_symbols = max(5, min(self.MAX_SYMBOLS, int(payload.get("max_symbols") or 120)))
        sample_step = max(1, min(20, int(payload.get("sample_step") or 3)))
        end_dt = self._parse_date(payload.get("train_end")) or datetime.now()
        start_dt = self._parse_date(payload.get("train_start")) or (end_dt - timedelta(days=540))
        if start_dt >= end_dt:
            start_dt = end_dt - timedelta(days=360)
        fetch_days = max(260, min(1200, (end_dt - start_dt).days + 260))
        feature_warmup_days = max(30, min(730, int(payload.get("feature_warmup_calendar_days") or 365)))
        label_lookahead_days = max(7, min(365, int(payload.get("label_lookahead_calendar_days") or max(30, horizon_days * 4 + 20))))
        history_start_text = (start_dt - timedelta(days=feature_warmup_days)).strftime("%Y-%m-%d")
        history_end_text = (end_dt + timedelta(days=label_lookahead_days)).strftime("%Y-%m-%d")
        history_provider = payload.get("history_source") or self.data_source_manager
        history_source = (
            "injected_history_source"
            if payload.get("history_source") is not None
            else "explicit_history_range" if hasattr(self.data_source_manager, "get_history_data_range") else "rolling_days"
        )
        excluded_features = {str(item) for item in (payload.get("exclude_feature_names") or [])}
        feature_names = [name for name in self.feature_builder.FEATURE_NAMES if name not in excluded_features]
        include_samples = bool(payload.get("include_samples", True))
        include_raw_columns = bool(payload.get("include_raw_columns", False))

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
                history = self._fetch_history(history_provider, symbol, fetch_days, history_start_text, history_end_text)
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
                    "history_source": history_source,
                    "history_start": history_start_text,
                    "history_end": history_end_text,
                    "feature_warmup_calendar_days": feature_warmup_days,
                    "label_lookahead_calendar_days": label_lookahead_days,
                    "errors": errors[:20],
                    "feature_names": feature_names,
                },
                "feature_names": feature_names,
            }

        dataset = pd.concat(frames, ignore_index=True)
        dataset = dataset.sort_values(["date", "symbol"]).reset_index(drop=True)
        raw_cols = []
        if include_raw_columns:
            raw_cols = [
                column
                for column in ["open", "high", "low", "close", "volume", "amount", "pct_change"]
                if column in dataset.columns
            ]
        keep_cols = [
            "date", "symbol", "name",
            *raw_cols,
            *feature_names,
            "future_return_pct", "future_max_drawdown_pct",
            "label_up", "label_dd", "label_risk_adjusted_return",
        ]
        dataset = dataset[keep_cols].replace([float("inf"), float("-inf")], 0).fillna(0)
        samples = dataset.to_dict(orient="records") if include_samples else []
        meta = {
            "symbol_count": len(symbols),
            "valid_symbol_count": len(frames),
            "sample_count": len(dataset),
            "train_start": start_text,
            "train_end": end_text,
            "horizon_days": horizon_days,
            "target_return_pct": target_return_pct,
            "drawdown_pct": drawdown_pct,
            "sample_step": sample_step,
            "history_source": history_source,
            "history_start": history_start_text,
            "history_end": history_end_text,
            "feature_warmup_calendar_days": feature_warmup_days,
            "label_lookahead_calendar_days": label_lookahead_days,
            "feature_names": feature_names,
            "include_samples": include_samples,
            "include_raw_columns": include_raw_columns,
            "errors": errors[:20],
        }
        try:
            meta["split_plan"] = build_ml_split_plan(
                dataset,
                final_holdout_months=int(payload.get("final_time_holdout_months") or 3),
                stock_holdout_ratio=float(payload.get("stock_holdout_ratio") or 0.20),
                walk_forward_splits=int(payload.get("walk_forward_splits") or 5),
            )
        except Exception as exc:
            meta["split_plan_error"] = str(exc)[:240]
        return {
            "df": dataset,
            "samples": samples,
            "meta": meta,
            "feature_names": feature_names,
        }

    def _fetch_history(self, history_provider, symbol: str, fetch_days: int, start_date: str, end_date: str) -> pd.DataFrame:
        if hasattr(history_provider, "get_history_data_range"):
            return history_provider.get_history_data_range(
                symbol,
                start_date=start_date,
                end_date=end_date,
            )
        return history_provider.get_history_data(symbol, days=fetch_days)
