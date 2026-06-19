"""Forward-performance labels for candidate-pool ranking diagnostics.

This module is deliberately read-only: it labels already-produced candidate
rows with future OHLCV outcomes and does not import production strategy code.
"""
from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd


DEFAULT_STRONG_LABEL_CONFIG: Dict[str, Any] = {
    "entry_price": "next_open",
    "horizons": [3, 5, 10, 20],
    "strong_return_threshold_pct": {3: 5.0, 5: 8.0, 10: 12.0, 20: 18.0},
    "take_profit_pct": 15.0,
    "stop_loss_pct": 8.0,
    "max_drawdown_pct": 10.0,
    "min_amount_yuan": 100000000.0,
    "min_volume": 1.0,
    "limit_threshold_pct_main_board": 9.8,
    "limit_threshold_pct_chinext_star": 19.5,
    "same_day_tp_sl_policy": "stop_loss_first",
}


def label_forward_performance(history: pd.DataFrame, config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Label future performance for a single candidate.

    `history` must start at the configured entry bar, typically the next
    tradable day after a candidate was generated.
    """
    cfg = _merge_config(config)
    rows = _normalize_history(history)
    if rows.empty:
        return _empty_labels(cfg, "missing_history")

    entry = rows.iloc[0]
    entry_price = _safe_float(entry.get("open"), 0.0)
    volume = _safe_float(entry.get("volume"), 0.0)
    amount = _safe_float(entry.get("amount"), 0.0)
    volume_pass = volume >= float(cfg["min_volume"]) and amount >= float(cfg["min_amount_yuan"])
    limit_status = _entry_limit_status(entry, cfg)
    limit_pass = limit_status == "tradable"

    if entry_price <= 0:
        tradability_status = "no_entry_price"
    elif not volume_pass:
        tradability_status = "volume_or_amount_blocked"
    elif not limit_pass:
        tradability_status = limit_status
    else:
        tradability_status = "tradable"

    labels = _base_labels(cfg, tradability_status, volume_pass, limit_pass)
    labels["entry_price"] = round(entry_price, 6)
    labels["max_floating_profit_pct"] = _return_pct(rows["high"].max(), entry_price)
    labels["max_adverse_excursion_pct"] = _return_pct(rows["low"].min(), entry_price)
    labels["path_max_drawdown_pct"] = _path_max_drawdown_pct(rows)
    labels.update(_tp_sl_path(rows, entry_price, cfg))
    labels["incomplete_horizons"] = []

    for horizon in cfg["horizons"]:
        h = int(horizon)
        if len(rows) < h:
            labels[f"return_{h}d_pct"] = 0.0
            labels[f"strong_{h}d"] = False
            labels["incomplete_horizons"].append(h)
            continue
        window = rows.head(h)
        close = _safe_float(window.iloc[-1].get("close"), 0.0) if not window.empty else 0.0
        ret = _return_pct(close, entry_price)
        labels[f"return_{h}d_pct"] = ret
        labels[f"strong_{h}d"] = (
            tradability_status == "tradable"
            and ret >= float(cfg["strong_return_threshold_pct"][h])
            and labels["max_adverse_excursion_pct"] >= -float(cfg["max_drawdown_pct"])
        )
    return labels


def _merge_config(config: Dict[str, Any] | None) -> Dict[str, Any]:
    cfg = dict(DEFAULT_STRONG_LABEL_CONFIG)
    for key, value in (config or {}).items():
        if key == "strong_return_threshold_pct":
            thresholds = dict(DEFAULT_STRONG_LABEL_CONFIG["strong_return_threshold_pct"])
            thresholds.update({int(k): float(v) for k, v in (value or {}).items()})
            cfg[key] = thresholds
        else:
            cfg[key] = value
    cfg["horizons"] = [int(item) for item in cfg.get("horizons") or [3, 5, 10, 20]]
    thresholds = dict(cfg["strong_return_threshold_pct"])
    for horizon in cfg["horizons"]:
        thresholds.setdefault(int(horizon), float(DEFAULT_STRONG_LABEL_CONFIG["strong_return_threshold_pct"].get(int(horizon), 0.0)))
    cfg["strong_return_threshold_pct"] = thresholds
    return cfg


def _normalize_history(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    rows = history.copy()
    if "date" in rows.columns:
        rows = rows.sort_values("date")
    for column in ("open", "high", "low", "close", "volume", "amount", "pct_change"):
        if column not in rows.columns:
            rows[column] = 0.0
        rows[column] = pd.to_numeric(rows[column], errors="coerce").fillna(0.0)
    return rows.reset_index(drop=True)


def _empty_labels(cfg: Dict[str, Any], status: str) -> Dict[str, Any]:
    labels = _base_labels(cfg, status, False, False)
    labels["entry_price"] = 0.0
    labels["max_floating_profit_pct"] = 0.0
    labels["max_adverse_excursion_pct"] = 0.0
    labels["path_max_drawdown_pct"] = 0.0
    labels.update(
        {
            "tp_before_sl": False,
            "sl_before_tp": False,
            "both_same_day": False,
            "tp_sl_path": "no_trigger",
            "tp_trigger_day": None,
            "sl_trigger_day": None,
            "incomplete_horizons": list(cfg["horizons"]),
        }
    )
    for horizon in cfg["horizons"]:
        h = int(horizon)
        labels[f"return_{h}d_pct"] = 0.0
        labels[f"strong_{h}d"] = False
    return labels


def _base_labels(cfg: Dict[str, Any], status: str, volume_pass: bool, limit_pass: bool) -> Dict[str, Any]:
    return {
        "label_config": {
            "horizons": list(cfg["horizons"]),
            "strong_return_threshold_pct": dict(cfg["strong_return_threshold_pct"]),
            "take_profit_pct": cfg["take_profit_pct"],
            "stop_loss_pct": cfg["stop_loss_pct"],
            "max_drawdown_pct": cfg["max_drawdown_pct"],
            "min_amount_yuan": cfg["min_amount_yuan"],
            "min_volume": cfg["min_volume"],
        },
        "tradability_status": status,
        "volume_constraint_pass": bool(volume_pass),
        "limit_constraint_pass": bool(limit_pass),
    }


def _entry_limit_status(entry: pd.Series, cfg: Dict[str, Any]) -> str:
    pct_change = _safe_float(entry.get("pct_change"), 0.0)
    if pct_change <= 0:
        return "tradable"
    symbol = str(entry.get("symbol") or "")
    threshold = float(cfg["limit_threshold_pct_chinext_star"] if symbol.startswith(("300", "301", "688")) else cfg["limit_threshold_pct_main_board"])
    high = _safe_float(entry.get("high"), 0.0)
    low = _safe_float(entry.get("low"), 0.0)
    open_price = _safe_float(entry.get("open"), 0.0)
    close = _safe_float(entry.get("close"), 0.0)
    if pct_change >= threshold and high > 0 and abs(high - low) <= 0.000001 and open_price >= high and close >= high:
        return "limit_up_entry_blocked"
    if pct_change >= threshold and open_price > 0 and high > 0 and open_price >= high:
        return "limit_up_entry_blocked"
    return "tradable"


def _tp_sl_path(rows: pd.DataFrame, entry_price: float, cfg: Dict[str, Any]) -> Dict[str, Any]:
    take_price = entry_price * (1 + float(cfg["take_profit_pct"]) / 100.0)
    stop_price = entry_price * (1 - float(cfg["stop_loss_pct"]) / 100.0)
    if entry_price <= 0:
        return {
            "tp_before_sl": False,
            "sl_before_tp": False,
            "both_same_day": False,
            "tp_sl_path": "no_trigger",
            "tp_trigger_day": None,
            "sl_trigger_day": None,
        }

    for idx, row in rows.iterrows():
        high = _safe_float(row.get("high"), 0.0)
        low = _safe_float(row.get("low"), 0.0)
        date_value = row.get("date")
        hit_tp = high >= take_price
        hit_sl = low <= stop_price
        if hit_tp and hit_sl:
            if cfg.get("same_day_tp_sl_policy") == "take_profit_first":
                return _trigger_payload("both_same_day_take_profit_first", idx, idx, date_value, date_value, True, False, True)
            return _trigger_payload("both_same_day_stop_loss_first", idx, idx, date_value, date_value, False, True, True)
        if hit_tp:
            return _trigger_payload("tp_before_sl", idx, None, date_value, None, True, False, False)
        if hit_sl:
            return _trigger_payload("sl_before_tp", None, idx, None, date_value, False, True, False)

    return {
        "tp_before_sl": False,
        "sl_before_tp": False,
        "both_same_day": False,
        "tp_sl_path": "no_trigger",
        "tp_trigger_day": None,
        "sl_trigger_day": None,
    }


def _trigger_payload(path: str, tp_idx, sl_idx, tp_day, sl_day, tp_before, sl_before, same_day) -> Dict[str, Any]:
    return {
        "tp_before_sl": bool(tp_before),
        "sl_before_tp": bool(sl_before),
        "both_same_day": bool(same_day),
        "tp_sl_path": path,
        "tp_trigger_day": None if tp_day is None else str(tp_day),
        "sl_trigger_day": None if sl_day is None else str(sl_day),
        "tp_trigger_index": tp_idx,
        "sl_trigger_index": sl_idx,
    }


def _path_max_drawdown_pct(rows: pd.DataFrame) -> float:
    peak = None
    max_drawdown = 0.0
    for _, row in rows.iterrows():
        high = _safe_float(row.get("high"), 0.0)
        low = _safe_float(row.get("low"), 0.0)
        if high <= 0 or low <= 0:
            continue
        peak = high if peak is None else max(peak, high)
        if peak and peak > 0:
            drawdown = (low / peak - 1.0) * 100.0
            max_drawdown = min(max_drawdown, drawdown)
    return round(max_drawdown, 6)


def _return_pct(price: Any, entry_price: float) -> float:
    price_float = _safe_float(price, 0.0)
    if entry_price <= 0 or price_float <= 0:
        return 0.0
    return round((price_float / entry_price - 1.0) * 100.0, 6)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result
