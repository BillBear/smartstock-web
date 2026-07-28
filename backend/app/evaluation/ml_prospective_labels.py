"""Pure forward-label semantics for a future prospective ML evaluation.

This module deliberately performs no filesystem, network, database, model, or
production-service work. A later, separately authorized task may pass a
normalized in-memory SH/SZ panel into these functions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd


_REQUIRED_PANEL_COLUMNS = {
    "trade_date",
    "next_open_date",
    "symbol",
    "industry_l1",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "eligible_signal_day",
    "entry_tradeable",
    "at_up_limit",
    "at_down_limit",
    "listing_age_trade_days",
    "valid_ohlc",
    "is_st",
    "is_suspended",
    "median_amount_20d",
}


@dataclass(frozen=True)
class ProspectiveLabelContract:
    """Frozen R1-compatible outcome, execution-cost, and alpha-label rules."""

    schema_version: int = 1
    universe_id: str = "shsz_a_share_v1"
    allowed_exchanges: tuple[str, ...] = ("SH", "SZ")
    horizons: tuple[int, ...] = (3, 5, 10, 20)
    take_profit: float = 0.08
    stop_loss: float = -0.06
    severe_drawdown: float = -0.08
    commission_per_side: float = 0.0003
    slippage_per_side: float = 0.001
    minimum_listing_sessions: int = 120
    minimum_industry_peers: int = 30

    def to_dict(self) -> dict[str, object]:
        """Return the stable serializable representation bound to a later run."""
        payload = asdict(self)
        payload["allowed_exchanges"] = list(self.allowed_exchanges)
        payload["horizons"] = list(self.horizons)
        return payload

    def sha256(self) -> str:
        """Return a deterministic identifier for this immutable semantic contract."""
        encoded = json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_prospective_forward_labels(panel: pd.DataFrame, contract: ProspectiveLabelContract) -> pd.DataFrame:
    """Compute R1-compatible forward outcomes from an in-memory normalized panel.

    The function never reads a lockbox, and each label traverses only the
    caller-declared ``next_open_date`` links. A broken chain therefore makes a
    horizon unavailable instead of substituting a later available bar.
    """
    rows = _normalize_panel(panel)
    if rows.empty:
        return rows
    outcomes: list[dict[str, Any]] = []
    for _, symbol_rows in rows.groupby("symbol", sort=False):
        ordered = symbol_rows.reset_index(drop=True)
        date_index = {str(value): index for index, value in enumerate(ordered["trade_date"])}
        for offset, row in ordered.iterrows():
            outcome: dict[str, Any] = {}
            for horizon in contract.horizons:
                outcome.update(_forward_outcome(ordered, date_index, offset, int(horizon), contract))
            outcome["eligible_for_training"] = bool(outcome["eligible_for_training_10d"])
            outcomes.append(outcome)
    return pd.concat([rows.reset_index(drop=True), pd.DataFrame(outcomes)], axis=1)


def _normalize_panel(panel: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel, pd.DataFrame):
        raise TypeError("prospective label panel must be a pandas DataFrame")
    missing = sorted(_REQUIRED_PANEL_COLUMNS - set(panel.columns))
    if missing:
        raise ValueError("prospective label panel misses columns: " + ", ".join(missing))
    rows = panel.copy()
    rows["trade_date"] = _normalize_date_series(rows["trade_date"], "trade_date", allow_null=False)
    rows["next_open_date"] = _normalize_date_series(rows["next_open_date"], "next_open_date", allow_null=True)
    rows["symbol"] = rows["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if rows["symbol"].eq("").any() or rows["symbol"].str.fullmatch(r"\d{6}").ne(True).any():
        raise ValueError("prospective label panel has an invalid symbol")
    if rows.duplicated(["symbol", "trade_date"]).any():
        raise ValueError("prospective label panel has duplicate symbol/trade_date keys")
    for column in ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "listing_age_trade_days", "median_amount_20d"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    for column in ("eligible_signal_day", "entry_tradeable", "at_up_limit", "at_down_limit", "valid_ohlc", "is_st", "is_suspended"):
        rows[column] = rows[column].eq(True)
    return rows.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _normalize_date_series(values: pd.Series, source: str, *, allow_null: bool) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if not allow_null and parsed.isna().any():
        raise ValueError(f"prospective label panel has an invalid {source}")
    normalized = parsed.dt.strftime("%Y-%m-%d").astype("string")
    return normalized.where(parsed.notna(), pd.NA)


def _forward_outcome(
    rows: pd.DataFrame,
    date_index: dict[str, int],
    offset: int,
    horizon: int,
    contract: ProspectiveLabelContract,
) -> dict[str, Any]:
    prefix = f"{horizon}d"
    indices = _exact_future_indices(rows, date_index, offset, horizon)
    available = indices is not None and _valid_future_prices(rows, indices)
    signal = rows.iloc[offset]
    entry_tradeable = bool(signal["entry_tradeable"])
    signal_eligible = _signal_eligible(signal, contract)
    base = {
        f"horizon_available_{prefix}": bool(available),
        f"entry_tradeable_{prefix}": entry_tradeable,
        f"eligible_for_training_{prefix}": bool(signal_eligible and entry_tradeable and available),
    }
    if not available:
        result = {
            **base,
            f"future_return_{prefix}": math.nan,
            f"gross_return_{prefix}": math.nan,
            f"net_return_after_cost_{prefix}": math.nan,
            f"entry_price_{prefix}": math.nan,
            f"exit_price_{prefix}": math.nan,
            f"exit_trade_date_{prefix}": pd.NA,
            f"mfe_{prefix}": math.nan,
            f"mae_{prefix}": math.nan,
            f"future_limit_up_count_{prefix}": pd.NA,
            f"future_limit_down_count_{prefix}": pd.NA,
            f"tp_before_sl_{prefix}": pd.NA,
            f"sl_before_tp_{prefix}": pd.NA,
            f"path_ambiguous_{prefix}": pd.NA,
        }
        return _add_ten_day_aliases(result, prefix)

    future = rows.iloc[indices]
    entry = float(future.iloc[0]["adjusted_open"])
    exit_price = float(future.iloc[-1]["adjusted_close"])
    gross_return = exit_price / entry - 1.0
    result = {
        **base,
        f"future_return_{prefix}": gross_return,
        f"gross_return_{prefix}": gross_return,
        f"net_return_after_cost_{prefix}": _net_execution_return(entry, exit_price, contract),
        f"entry_price_{prefix}": entry,
        f"exit_price_{prefix}": exit_price,
        f"exit_trade_date_{prefix}": str(future.iloc[-1]["trade_date"]),
        f"mfe_{prefix}": float(future["adjusted_high"].max()) / entry - 1.0,
        f"mae_{prefix}": float(future["adjusted_low"].min()) / entry - 1.0,
        f"future_limit_up_count_{prefix}": int(future["at_up_limit"].sum()),
        f"future_limit_down_count_{prefix}": int(future["at_down_limit"].sum()),
        **_path_flags(future, entry, prefix, contract),
    }
    return _add_ten_day_aliases(result, prefix)


def _exact_future_indices(rows: pd.DataFrame, date_index: dict[str, int], offset: int, horizon: int) -> list[int] | None:
    current = offset
    indices: list[int] = []
    for _ in range(horizon):
        next_date = rows.iloc[current]["next_open_date"]
        if pd.isna(next_date):
            return None
        next_index = date_index.get(str(next_date))
        if next_index is None or next_index != current + 1:
            return None
        indices.append(next_index)
        current = next_index
    return indices


def _valid_future_prices(rows: pd.DataFrame, indices: list[int]) -> bool:
    future = rows.iloc[indices]
    for column in ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"):
        values = pd.to_numeric(future[column], errors="coerce")
        if values.isna().any() or values.le(0).any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            return False
    return True


def _signal_eligible(row: pd.Series, contract: ProspectiveLabelContract) -> bool:
    return bool(
        row["eligible_signal_day"]
        and row["valid_ohlc"]
        and not row["is_st"]
        and not row["is_suspended"]
        and float(row["listing_age_trade_days"]) >= contract.minimum_listing_sessions
        and float(row["median_amount_20d"]) > 0.0
    )


def _net_execution_return(entry: float, exit_price: float, contract: ProspectiveLabelContract) -> float:
    return (
        (exit_price * (1.0 - contract.slippage_per_side))
        / (entry * (1.0 + contract.slippage_per_side))
        * (1.0 - contract.commission_per_side) ** 2
        - 1.0
    )


def _path_flags(future: pd.DataFrame, entry: float, prefix: str, contract: ProspectiveLabelContract) -> dict[str, bool]:
    take_profit_price = entry * (1.0 + contract.take_profit)
    stop_loss_price = entry * (1.0 + contract.stop_loss)
    for _, row in future.iterrows():
        hit_tp = float(row["adjusted_high"]) + 1e-12 >= take_profit_price
        hit_sl = float(row["adjusted_low"]) <= stop_loss_price + 1e-12
        if hit_tp and hit_sl:
            return {
                f"tp_before_sl_{prefix}": False,
                f"sl_before_tp_{prefix}": False,
                f"path_ambiguous_{prefix}": True,
            }
        if hit_tp:
            return {
                f"tp_before_sl_{prefix}": True,
                f"sl_before_tp_{prefix}": False,
                f"path_ambiguous_{prefix}": False,
            }
        if hit_sl:
            return {
                f"tp_before_sl_{prefix}": False,
                f"sl_before_tp_{prefix}": True,
                f"path_ambiguous_{prefix}": False,
            }
    return {
        f"tp_before_sl_{prefix}": False,
        f"sl_before_tp_{prefix}": False,
        f"path_ambiguous_{prefix}": False,
    }


def _add_ten_day_aliases(result: dict[str, Any], prefix: str) -> dict[str, Any]:
    if prefix == "10d":
        for field in ("entry_price", "exit_price", "exit_trade_date", "gross_return", "net_return_after_cost", "mfe", "mae"):
            result[field] = result[f"{field}_{prefix}"]
    return result
