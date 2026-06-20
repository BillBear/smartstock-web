"""Historical candidate-pool replay adapters for ranking evaluation."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from sqlalchemy import text

from app.evaluation.ranking_labels import DEFAULT_STRONG_LABEL_CONFIG, label_forward_performance


BUY_ACTION_TYPES = {"paper_buy", "buy", "simulated_buy"}


def normalize_candidate_row(
    trade_date: str,
    pick: Dict[str, Any],
    market_state: Optional[Dict[str, Any]],
    action: Optional[Dict[str, Any]],
    source: str,
) -> Dict[str, Any]:
    """Flatten one pick/candidate snapshot into an evaluation row."""
    pick = dict(pick or {})
    breakdown = dict(pick.get("score_breakdown") or {})
    diagnostics = dict(pick.get("ranking_diagnostics") or {})
    signal_features = dict(diagnostics.get("signal_features") or {})
    action = action if action is not None else pick.get("user_action")
    evidence_summary = dict(pick.get("evidence_summary") or {})
    market_state = market_state or pick.get("market_state") or evidence_summary or {}
    action_type = str((action or {}).get("action_type") or "")
    was_bought = bool((action or {}).get("was_bought")) or action_type in BUY_ACTION_TYPES
    buy_action_time = (action or {}).get("buy_action_time")
    if not buy_action_time and action_type in BUY_ACTION_TYPES:
        buy_action_time = (action or {}).get("created_at")

    return {
        "trade_date": _normalize_date_value(trade_date) or str(trade_date),
        "pick_id": str(pick.get("pick_id") or ""),
        "symbol": str(pick.get("symbol") or ""),
        "name": pick.get("name") or pick.get("symbol") or "",
        "rank_no": _safe_int(pick.get("rank_no"), 999999),
        "score": _safe_float(pick.get("score"), _safe_float(breakdown.get("total"), 0.0)),
        "source": source,
        "market_state_tag": str(market_state.get("state_tag") or evidence_summary.get("state_tag") or "unknown"),
        "market_state_score": _safe_float(market_state.get("state_score"), 0.0),
        "was_bought": was_bought,
        "buy_action_time": buy_action_time if was_bought else None,
        "action_type": action_type or None,
        "factor_ranking_score": _safe_float(pick.get("ranking_score"), _safe_float(breakdown.get("ranking_score"), 0.0)),
        "factor_swing_score": _safe_float(pick.get("swing_score"), _safe_float(breakdown.get("swing_score"), 0.0)),
        "factor_continuation_score": _safe_float(pick.get("continuation_score"), _safe_float(breakdown.get("continuation_score"), 0.0)),
        "factor_risk_control_score": _safe_float(pick.get("risk_control_score"), _safe_float(breakdown.get("risk_control_score"), 0.0)),
        "factor_leader_score": _safe_float(pick.get("leader_score"), 0.0),
        "factor_theme_rank_score": _safe_float(pick.get("theme_rank_score"), _safe_float(breakdown.get("theme"), 0.0)),
        "factor_up_prob": _safe_float(pick.get("up_prob"), 0.0),
        "factor_dd_prob": _safe_float(pick.get("dd_prob"), 0.0),
        "factor_expected_edge_pct": _safe_float(pick.get("expected_edge_pct"), 0.0),
        "factor_profit_factor_proxy": _safe_float(pick.get("profit_factor_proxy"), 0.0),
        "factor_total_score": _safe_float(breakdown.get("total"), _safe_float(pick.get("score"), 0.0)),
        "factor_trend": _safe_float(breakdown.get("trend"), 0.0),
        "factor_money_flow": _safe_float(breakdown.get("money_flow"), 0.0),
        "factor_turnover_liquidity": _safe_float(breakdown.get("turnover_liquidity"), 0.0),
        "factor_volume_ratio_20": _safe_float(signal_features.get("volume_ratio_20"), 0.0),
        "factor_rsi": _safe_float(signal_features.get("rsi"), 0.0),
        "factor_ma20_gap_pct": _safe_float(signal_features.get("ma20_gap_pct"), 0.0),
    }


def replay_coverage_summary(requested_dates: List[str], available_dates: List[str]) -> Dict[str, Any]:
    requested = [str(item) for item in requested_dates or []]
    available = sorted(set(str(item) for item in available_dates or []))
    missing = [item for item in requested if item not in set(available)]
    if not requested or not available:
        status = "blocked"
    elif len(available) >= len(requested) and not missing:
        status = "complete"
    else:
        status = "partial"
    return {
        "coverage_status": status,
        "requested_date_count": len(requested),
        "covered_date_count": len(available),
        "requested_dates": requested,
        "available_dates": available,
        "missing_dates": missing,
    }


def attach_forward_labels(
    rows: List[Dict[str, Any]],
    data_source_manager,
    label_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Join candidate rows with future OHLCV labels using historical data."""
    labeled_rows = []
    cfg = _merge_label_config(label_config)
    for row in rows or []:
        output = dict(row)
        try:
            start_date, end_date = _label_history_window(row.get("trade_date"), cfg)
            history = _fetch_explicit_history_range(
                data_source_manager,
                symbol=row.get("symbol"),
                start_date=start_date,
                end_date=end_date,
            )
            future = _future_history(history, start_date, end_date=end_date)
            output.update(label_forward_performance(future, cfg))
        except Exception as exc:  # pragma: no cover - defensive boundary
            output.update(label_forward_performance(pd.DataFrame(), cfg))
            output["label_error"] = str(exc)
        labeled_rows.append(output)
    return labeled_rows


class RankingReplayService:
    """Read-only historical candidate replay service."""

    def __init__(self, store, data_source_manager, coach_service=None, user_id: str = "default"):
        self.store = store
        self.data_source_manager = data_source_manager
        self.coach_service = coach_service
        self.user_id = str(user_id or "default")

    def replay(
        self,
        strategy_code: str,
        risk_level: str,
        start_date: str,
        end_date: str,
        attach_labels: bool = False,
        label_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        dates = _date_range(start_date, end_date)
        rows: List[Dict[str, Any]] = []
        available_dates: List[str] = []
        for trade_date in dates:
            daily = self._load_daily_candidates(strategy_code, risk_level, trade_date)
            if not daily:
                continue
            available_dates.append(trade_date)
            rows.extend(daily)

        if attach_labels:
            rows = attach_forward_labels(rows, self.data_source_manager, label_config=label_config)

        return {
            "rows": rows,
            "coverage": replay_coverage_summary(dates, available_dates),
        }

    def _load_daily_candidates(self, strategy_code: str, risk_level: str, trade_date: str) -> List[Dict[str, Any]]:
        snapshots = self._store_snapshots(strategy_code, risk_level, trade_date)
        action_map = self._pick_action_map()
        rows = []
        for pick in snapshots:
            action = pick.get("user_action") or self._action_for_pick(pick, action_map)
            rows.append(
                normalize_candidate_row(
                    trade_date=trade_date,
                    pick=pick,
                    market_state=pick.get("market_state"),
                    action=action,
                    source="pick_snapshot",
                )
            )
        return rows

    def _store_snapshots(self, strategy_code: str, risk_level: str, trade_date: str) -> List[Dict[str, Any]]:
        if not self.store:
            return []
        if hasattr(self.store, "list_pick_snapshots"):
            try:
                snapshots = self.store.list_pick_snapshots(
                    strategy_code=strategy_code,
                    risk_level=risk_level,
                    trade_date=trade_date,
                    user_id=self.user_id,
                )
            except TypeError:
                snapshots = self.store.list_pick_snapshots(
                    strategy_code=strategy_code,
                    risk_level=risk_level,
                    trade_date=trade_date,
                )
            return list(snapshots or [])
        if hasattr(self.store, "list_pick_history"):
            return list(self.store.list_pick_history(strategy_code=strategy_code, risk_level=risk_level, trade_date=trade_date) or [])
        if hasattr(self.store, "engine"):
            return self._query_pick_snapshots(strategy_code=strategy_code, risk_level=risk_level, trade_date=trade_date)
        return []

    def _query_pick_snapshots(self, strategy_code: str, risk_level: str, trade_date: str) -> List[Dict[str, Any]]:
        sql = text(
            """
            SELECT pick_id, user_id, trade_date, symbol, name, strategy_code, risk_level, snapshot_json, created_at
            FROM pick_snapshots
            WHERE user_id = :user_id
              AND trade_date = :trade_date
              AND (:strategy_code = '' OR strategy_code = :strategy_code)
              AND (:risk_level = '' OR risk_level = :risk_level)
            ORDER BY created_at ASC, pick_id ASC
            """
        )
        with self.store.engine.connect() as conn:
            rows = conn.execute(
                sql,
                {
                    "user_id": self.user_id,
                    "trade_date": str(trade_date),
                    "strategy_code": str(strategy_code or ""),
                    "risk_level": str(risk_level or ""),
                },
            ).fetchall()
        snapshots = []
        for row in rows:
            data = dict(row._mapping)
            try:
                snapshot = json.loads(data.get("snapshot_json") or "{}")
            except Exception:
                snapshot = {}
            snapshot.setdefault("pick_id", data.get("pick_id"))
            snapshot.setdefault("user_id", data.get("user_id"))
            snapshot.setdefault("trade_date", data.get("trade_date"))
            snapshot.setdefault("symbol", data.get("symbol"))
            snapshot.setdefault("name", data.get("name") or data.get("symbol"))
            snapshot.setdefault("strategy_code", data.get("strategy_code"))
            snapshot.setdefault("risk_level", data.get("risk_level"))
            snapshot.setdefault("created_at", data.get("created_at"))
            snapshots.append(snapshot)
        return snapshots

    def _pick_action_map(self) -> Dict[str, Dict[str, Any]]:
        if not self.store:
            return {}
        if hasattr(self.store, "get_pick_action_history"):
            history = dict(self.store.get_pick_action_history(user_id=self.user_id) or {})
            return {
                pick_id: self._summarize_action_history(actions)
                for pick_id, actions in history.items()
            }
        if hasattr(self.store, "get_latest_pick_actions"):
            return dict(self.store.get_latest_pick_actions(user_id=self.user_id) or {})
        return {}

    @staticmethod
    def _action_for_pick(pick: Dict[str, Any], action_map: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        pick_id = str(pick.get("pick_id") or "")
        if pick_id and pick_id in action_map:
            return action_map[pick_id]
        symbol = str(pick.get("symbol") or "")
        for action in action_map.values():
            if symbol and str(action.get("symbol") or "") == symbol:
                return action
        return None

    @staticmethod
    def _summarize_action_history(actions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        ordered = [dict(item or {}) for item in actions or []]
        if not ordered:
            return {}
        buy_actions = [item for item in ordered if str(item.get("action_type") or "") in BUY_ACTION_TYPES]
        latest = dict(ordered[-1])
        if buy_actions:
            latest["was_bought"] = True
            latest["buy_action_time"] = buy_actions[0].get("created_at")
            latest.setdefault("symbol", buy_actions[0].get("symbol"))
        else:
            latest["was_bought"] = False
        return latest


def _future_history(history: pd.DataFrame, trade_date: Any, end_date: Any = None) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    rows = history.copy()
    if "date" not in rows.columns:
        return pd.DataFrame()
    normalized_trade_date = _normalize_date_value(trade_date)
    if not normalized_trade_date:
        return pd.DataFrame()
    rows["date"] = rows["date"].map(_normalize_date_value)
    rows = rows.dropna(subset=["date"])
    mask = rows["date"] > normalized_trade_date
    normalized_end_date = _normalize_date_value(end_date)
    if normalized_end_date:
        mask = mask & (rows["date"] <= normalized_end_date)
    return rows[mask].sort_values("date").reset_index(drop=True)


def _label_history_window(trade_date: Any, cfg: Dict[str, Any]) -> tuple[str, str]:
    start_date = _parse_date(str(trade_date))
    horizons = [int(item) for item in cfg.get("horizons") or DEFAULT_STRONG_LABEL_CONFIG["horizons"]]
    max_horizon = max(horizons or [20])
    calendar_days = int(cfg.get("history_window_calendar_days") or max(14, max_horizon * 5 + 10))
    end_date = start_date + timedelta(days=calendar_days)
    return start_date.isoformat(), end_date.isoformat()


def _fetch_explicit_history_range(data_source_manager, symbol: Any, start_date: str, end_date: str) -> pd.DataFrame:
    if not hasattr(data_source_manager, "get_history_data_range"):
        raise RuntimeError("explicit_history_range_unavailable")
    return data_source_manager.get_history_data_range(str(symbol or ""), start_date=start_date, end_date=end_date)


def _merge_label_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_STRONG_LABEL_CONFIG)
    for key, value in (config or {}).items():
        if key == "strong_return_threshold_pct":
            thresholds = dict(DEFAULT_STRONG_LABEL_CONFIG["strong_return_threshold_pct"])
            thresholds.update({int(k): float(v) for k, v in (value or {}).items()})
            cfg[key] = thresholds
        else:
            cfg[key] = value
    return cfg


def _date_range(start_date: str, end_date: str) -> List[str]:
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start > end:
        return []
    dates = []
    cursor = start
    while cursor <= end:
        dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return dates


def _parse_date(value: str) -> date:
    normalized = _normalize_date_value(value)
    if not normalized:
        raise ValueError(f"invalid date: {value}")
    return datetime.strptime(normalized, "%Y-%m-%d").date()


def _normalize_date_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value).strip()
    if not text_value:
        return None
    formats = ["%Y-%m-%d", "%Y%m%d"]
    for fmt in formats:
        try:
            return datetime.strptime(text_value[:10] if fmt == "%Y-%m-%d" else text_value[:8], fmt).date().isoformat()
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
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
