from __future__ import annotations

import hashlib
from typing import Any, Dict, List


def sample_training_symbols(
    snapshot: List[Dict[str, Any]],
    target_count: int = 700,
    oversample_count: int = 760,
    seed: int = 20260704,
) -> List[Dict[str, Any]]:
    """Select a deterministic, broad local ML training universe."""
    cleaned = _clean_snapshot(snapshot)
    if not cleaned:
        return []

    _assign_liquidity_buckets(cleaned)
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in cleaned:
        key = (row["board"], row["liquidity_bucket"], row["industry"])
        groups.setdefault(key, []).append(row)

    for key, rows in groups.items():
        rows.sort(key=lambda item: _stable_hash(f"{seed}:{key}:{item['symbol']}"))

    group_keys = sorted(groups, key=lambda key: _stable_hash(f"{seed}:{key}"))
    limit = max(1, min(int(oversample_count or target_count or 700), len(cleaned)))
    selected: List[Dict[str, Any]] = []
    used = set()

    while len(selected) < limit:
        progressed = False
        for key in group_keys:
            rows = groups.get(key) or []
            while rows:
                candidate = rows.pop(0)
                symbol = candidate["symbol"]
                if symbol in used:
                    continue
                selected.append(candidate)
                used.add(symbol)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break

    return selected


def _clean_snapshot(snapshot: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for item in snapshot or []:
        symbol = _normalize_symbol(item.get("symbol"))
        if not symbol or symbol in seen:
            continue
        name = str(item.get("name") or symbol).strip()
        if _is_excluded_name(name):
            continue
        price = _safe_float(item.get("price"))
        amount = _safe_float(item.get("amount"))
        if price <= 1 or amount < 0:
            continue
        board = _board_for_symbol(symbol)
        if board == "other":
            continue
        seen.add(symbol)
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "industry": str(item.get("industry") or "unknown").strip() or "unknown",
                "amount": amount,
                "price": price,
                "board": board,
            }
        )
    return rows


def _assign_liquidity_buckets(rows: List[Dict[str, Any]]) -> None:
    ordered = sorted(rows, key=lambda row: row.get("amount", 0.0))
    total = max(1, len(ordered) - 1)
    buckets = {}
    for index, row in enumerate(ordered):
        rank = index / total if total else 0.0
        if rank >= 2 / 3:
            bucket = "high"
        elif rank >= 1 / 3:
            bucket = "medium"
        else:
            bucket = "low"
        buckets[row["symbol"]] = bucket
    for row in rows:
        row["liquidity_bucket"] = buckets.get(row["symbol"], "medium")


def _normalize_symbol(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".")[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) != 6:
        return ""
    return digits


def _is_excluded_name(name: str) -> bool:
    text = str(name or "").upper()
    return not text or "ST" in text or "退" in text


def _board_for_symbol(symbol: str) -> str:
    if symbol.startswith(("600", "601", "603", "605")):
        return "sh_main"
    if symbol.startswith(("000", "001", "002", "003")):
        return "sz_main"
    if symbol.startswith(("300", "301")):
        return "chinext"
    if symbol.startswith(("688", "689")):
        return "star"
    return "other"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
