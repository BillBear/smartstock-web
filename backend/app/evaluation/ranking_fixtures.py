"""Deterministic fixtures for ranking evaluation smoke tests."""
from __future__ import annotations

from typing import Any, Dict, List


def smoke_fixture_rows(horizons: List[int]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return a stable two-day candidate sample with known ranking outcomes."""
    rows = []
    trade_dates = ["2026-01-02", "2026-01-05"]
    template = [
        ("000001", 1, -3.0, True, "sl_before_tp", "neutral", 86.0),
        ("000002", 2, 9.0, False, "tp_before_sl", "neutral", 74.0),
        ("000003", 8, 4.0, False, "no_trigger", "neutral", 69.0),
        ("000004", 14, 22.0, False, "tp_before_sl", "neutral", 58.0),
    ]
    for trade_date in trade_dates:
        for symbol, rank_no, ret5, bought, path, state, score in template:
            row: Dict[str, Any] = {
                "trade_date": trade_date,
                "symbol": symbol,
                "name": symbol,
                "rank_no": rank_no,
                "tradability_status": "tradable",
                "was_bought": bought,
                "tp_sl_path": path,
                "market_state_tag": state,
                "factor_ranking_score": score,
                "factor_total_score": score - 2,
                "max_floating_profit_pct": max(ret5, 0.0) + 2,
                "max_adverse_excursion_pct": -4.0,
            }
            for horizon in horizons:
                h = int(horizon)
                multiplier = {3: 0.6, 5: 1.0, 10: 1.35, 20: 1.8}.get(h, 1.0)
                ret = round(ret5 * multiplier, 6)
                row[f"return_{h}d_pct"] = ret
                row[f"strong_{h}d"] = ret >= {3: 5.0, 5: 8.0, 10: 12.0, 20: 18.0}.get(h, 8.0)
            rows.append(row)
    coverage = {
        "coverage_status": "complete",
        "requested_date_count": len(trade_dates),
        "covered_date_count": len(trade_dates),
        "requested_dates": trade_dates,
        "available_dates": trade_dates,
        "missing_dates": [],
        "fixture": "smoke",
    }
    return rows, coverage
