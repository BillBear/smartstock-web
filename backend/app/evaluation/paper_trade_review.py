"""Read-only attribution of saved paper transactions, not an execution engine."""
from collections import defaultdict
import math


def summarize_paper_trades(trades, commission=0.0003, slippage=0.001):
    """Reconcile all recorded buys/sells with weighted cost; never invent fills."""
    positions = defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "buy_fees": 0.0})
    sales, unmatched = [], []
    completed = 0
    ids = [item["id"] for item in trades]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_paper_trade_ids")
    for row in sorted(trades, key=lambda item: (str(item["created_at"]), int(item["id"]))):
        qty, price, fee = float(row["qty"]), float(row["price"]), float(row.get("fee") or 0)
        if not all(math.isfinite(value) for value in (qty, price, fee)) or qty <= 0 or price <= 0 or fee < 0:
            raise ValueError("invalid_paper_trade_values")
        position = positions[row["symbol"]]
        if row["side"] == "buy":
            position["qty"] += qty
            position["cost"] += qty * price
            position["buy_fees"] += fee
            continue
        if row["side"] != "sell":
            raise ValueError("invalid_paper_trade_side")
        matched = min(qty, position["qty"])
        if matched < qty:
            unmatched.append({"trade_id": row["id"], "symbol": row["symbol"], "qty": qty - matched})
        if matched <= 0:
            continue
        cost_price = position["cost"] / position["qty"]
        entry_fee = position["buy_fees"] * matched / position["qty"]
        sell_fee = fee * matched / qty
        basis, proceeds = cost_price * matched, price * matched
        gross = proceeds - basis
        overlay = (basis + proceeds) * (commission + slippage)
        sales.append({"trade_id": row["id"], "symbol": row["symbol"], "created_at": str(row["created_at"]),
                      "qty": matched, "cost_price": cost_price, "sale_price": price, "gross_pnl": gross,
                      "recorded_fee_net_pnl": gross - entry_fee - sell_fee,
                      "estimated_cost_overlay_pnl": gross - overlay,
                      "gross_return_pct": (price / cost_price - 1) * 100})
        position["qty"] -= matched
        position["cost"] -= basis
        position["buy_fees"] -= entry_fee
        if position["qty"] == 0:
            completed += 1
    return {"trade_count": len(trades), "buy_count": sum(row["side"] == "buy" for row in trades),
            "sell_count": sum(row["side"] == "sell" for row in trades),
            "matched_sale_event_count": len(sales), "completed_position_episode_count": completed,
            "recorded_gross_realized_pnl": round(sum(row["gross_pnl"] for row in sales), 6) if sales else None,
            "estimated_cost_overlay_pnl": round(sum(row["estimated_cost_overlay_pnl"] for row in sales), 6) if sales else None,
            "recorded_fees_all_zero": bool(trades) and all(not row.get("fee") for row in trades),
            "sale_events": sales, "unmatched_sales": unmatched,
            "open_positions_at_cost": {symbol: value for symbol, value in positions.items() if value["qty"] > 0},
            "limitations": ["manual_selection_not_system_strategy_performance", "saved_prices_not_verified_market_fills",
                            "cost_overlay_is_estimate_not_recorded_cost", "open_positions_not_marked_to_market",
                            "no_minimum_commission_or_tax_model"]}
