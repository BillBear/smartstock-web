"""Read-only, next-open forward labels for full-market ML research."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from .config import FullMarketMLConfig


HORIZONS = (3, 5, 10, 20)
TAKE_PROFIT = 0.08
STOP_LOSS = -0.06
SEVERE_DRAWDOWN = -0.08
MIN_DAILY_INVARIANT_ELIGIBLE = 1000
DEFAULT_COMMISSION = 0.0003
DEFAULT_SLIPPAGE = 0.001


class LabelDistributionError(ValueError):
    """Raised when a full-market label distribution violates its fixed bounds."""


def build_forward_labels(
    config: FullMarketMLConfig,
    panel_shard: pd.DataFrame,
    *,
    commission: float = DEFAULT_COMMISSION,
    slippage: float = DEFAULT_SLIPPAGE,
) -> pd.DataFrame:
    """Build shard-local outcomes; call ``aggregate_full_market_labels`` for grades.

    ``next_open_date`` is an immutable panel calendar contract. Following that
    chain prevents an absent session from being silently replaced by a later bar.
    """
    del config
    commission, slippage = _validate_execution_costs(commission, slippage)
    panel = _normalize_panel(panel_shard)
    if panel.empty:
        return panel
    labeled = panel.copy()
    for horizon in HORIZONS:
        values: list[dict[str, Any]] = []
        for _, rows in labeled.groupby("symbol", sort=False):
            symbol_rows = rows.reset_index(drop=True)
            data = _symbol_arrays(symbol_rows)
            values.extend(
                _forward_outcome(data, offset, horizon, commission=commission, slippage=slippage)
                for offset in range(len(symbol_rows))
            )
        outcomes = pd.DataFrame(values, index=labeled.index)
        for column in outcomes:
            labeled[column] = outcomes[column]
    labeled["eligible_for_training"] = labeled["eligible_for_training_10d"].eq(True)
    return labeled


def aggregate_full_market_labels(
    config: FullMarketMLConfig, labeled_shards: Mapping[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """Apply cross-sectional labels over every shard for each signal date.

    The input must contain all symbol shards for the development universe. The
    return mapping preserves shard keys and rows, while every report and daily
    invariant is calculated from the full per-date cross-section.
    """
    del config
    if not isinstance(labeled_shards, Mapping):
        raise TypeError("labeled_shards must be a mapping of shard key to DataFrame")
    result = {str(key): _prepare_for_aggregation(value) for key, value in labeled_shards.items()}
    if not result:
        return result

    for trade_date in _all_trade_dates(result):
        eligible = _eligible_rows_for_date(result, trade_date)
        if eligible.empty:
            continue
        _assign_full_market_date_labels(result, eligible, trade_date)

    for shard in result.values():
        shard["relevance_grade_10d"] = pd.array(shard["relevance_grade_10d"], dtype="Int64")
        for column in ("label_strong_path_10d", "label_severe_negative_10d"):
            shard[column] = pd.array(shard[column], dtype="boolean")
    report = build_label_report(result)
    assert_label_distribution_invariants(result, require_full_development_period=False)
    for shard in result.values():
        shard.attrs["label_report"] = report
    return result


def daily_relevance_distribution(labeled: pd.DataFrame | Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Return full-market per-date eligible counts, grades, paths, and state."""
    combined = _combined_labeled_rows(labeled)
    if combined.empty or "trade_date" not in combined:
        return pd.DataFrame(columns=["trade_date", "eligible_count", "grade_4_count", "grade_3_or_higher_count", "strong_label_count", "path_ambiguity_count", "market_state"])
    rows = []
    for trade_date, group in combined.groupby("trade_date", sort=True):
        eligible = group[group["eligible_for_training"].eq(True)]
        grades = pd.to_numeric(eligible["relevance_grade_10d"], errors="coerce")
        states = eligible["market_state_10d"].dropna()
        rows.append(
            {
                "trade_date": str(trade_date),
                "eligible_count": int(len(eligible)),
                "grade_4_count": int(grades.eq(4).sum()),
                "grade_3_or_higher_count": int(grades.ge(3).sum()),
                "strong_label_count": int(eligible["label_strong_path_10d"].eq(True).sum()),
                "path_ambiguity_count": int(eligible.get("path_ambiguous_10d", pd.Series(False, index=eligible.index)).eq(True).sum()),
                "market_state": str(states.iloc[0]) if not states.empty else "unavailable",
            }
        )
    return pd.DataFrame(rows)


def build_label_report(labeled: pd.DataFrame | Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    """Summarise globally aggregated label availability without writing artifacts."""
    distribution = daily_relevance_distribution(labeled)
    eligible_count = int(distribution["eligible_count"].sum()) if not distribution.empty else 0
    strong_count = int(distribution["strong_label_count"].sum()) if not distribution.empty else 0
    ambiguity_count = int(distribution["path_ambiguity_count"].sum()) if not distribution.empty else 0
    weak = distribution[distribution["market_state"].eq("weak")] if not distribution.empty else distribution
    return {
        "row_count": int(len(_combined_labeled_rows(labeled))),
        "eligible_count_10d": eligible_count,
        "strong_label_count_10d": strong_count,
        "strong_label_rate_10d": strong_count / eligible_count if eligible_count else None,
        "path_ambiguity_count_10d": ambiguity_count,
        "weak_market_zero_strong_date_count_10d": int(weak["strong_label_count"].eq(0).sum()) if not weak.empty else 0,
        "weak_market_zero_strong_dates_10d": weak.loc[weak["strong_label_count"].eq(0), "trade_date"].tolist() if not weak.empty else [],
        "daily_relevance_distribution_10d": distribution.to_dict("records"),
    }


def assert_label_distribution_invariants(
    labeled: pd.DataFrame | Mapping[str, pd.DataFrame], *, require_full_development_period: bool = False
) -> None:
    """Assert daily grade caps using global, never shard-local, denominators."""
    distribution = daily_relevance_distribution(labeled)
    violations = []
    for row in distribution.itertuples(index=False):
        if row.eligible_count < MIN_DAILY_INVARIANT_ELIGIBLE:
            continue
        if row.grade_4_count / row.eligible_count > 0.05:
            violations.append(f"grade_4_rate_exceeds_5pct:{row.trade_date}")
        if row.grade_3_or_higher_count / row.eligible_count > 0.10:
            violations.append(f"grade_3_or_higher_rate_exceeds_10pct:{row.trade_date}")
    if require_full_development_period:
        eligible_count = int(distribution["eligible_count"].sum()) if not distribution.empty else 0
        strong_count = int(distribution["strong_label_count"].sum()) if not distribution.empty else 0
        rate = strong_count / eligible_count if eligible_count else 0.0
        if not 0.02 <= rate <= 0.10:
            violations.append("strong_label_rate_outside_2_to_10pct")
    if violations:
        raise LabelDistributionError(", ".join(violations))


def _normalize_panel(panel_shard: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel_shard, pd.DataFrame):
        raise TypeError("panel_shard must be a pandas DataFrame")
    required = {"trade_date", "symbol", "next_open_date", "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"}
    missing = sorted(required - set(panel_shard.columns))
    if missing:
        raise ValueError("panel_shard missing columns: " + ", ".join(missing))
    panel = panel_shard.copy()
    for column in ("trade_date", "next_open_date"):
        panel[column] = pd.to_datetime(panel[column], errors="coerce").dt.strftime("%Y-%m-%d")
    panel["symbol"] = panel["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    panel = panel.dropna(subset=["trade_date"])
    for column in ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"):
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    for column in ("eligible_signal_day", "entry_tradeable", "at_up_limit", "at_down_limit"):
        panel[column] = panel.get(column, pd.Series(False, index=panel.index)).eq(True)
    if "industry_l1" not in panel:
        panel["industry_l1"] = pd.NA
    return panel.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _symbol_arrays(rows: pd.DataFrame) -> dict[str, Any]:
    dates = rows["trade_date"].astype(str).tolist()
    date_index = {value: index for index, value in enumerate(dates)}
    return {
        "dates": dates,
        "next_index": np.asarray([date_index.get(str(value), -1) for value in rows["next_open_date"]], dtype=np.int64),
        "open": rows["adjusted_open"].to_numpy(dtype=float),
        "high": rows["adjusted_high"].to_numpy(dtype=float),
        "low": rows["adjusted_low"].to_numpy(dtype=float),
        "close": rows["adjusted_close"].to_numpy(dtype=float),
        "up": rows["at_up_limit"].to_numpy(dtype=bool),
        "down": rows["at_down_limit"].to_numpy(dtype=bool),
        "eligible": rows["eligible_signal_day"].to_numpy(dtype=bool),
        "tradeable": rows["entry_tradeable"].to_numpy(dtype=bool),
    }


def _forward_outcome(
    data: dict[str, Any], offset: int, horizon: int, *, commission: float, slippage: float
) -> dict[str, Any]:
    prefix = f"{horizon}d"
    indices = _calendar_exact_indices(data["next_index"], offset, horizon)
    available = indices is not None and _valid_adjusted_indices(data, indices)
    eligible = bool(data["eligible"][offset] and data["tradeable"][offset] and available)
    base = {
        f"horizon_available_{prefix}": bool(available),
        f"eligible_for_training_{prefix}": bool(eligible),
        f"entry_tradeable_{prefix}": bool(data["tradeable"][offset]),
    }
    if not available:
        outcome = {
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
        return _add_canonical_ten_day_aliases(outcome, prefix)
    entry = float(data["open"][indices[0]])
    exit_price = float(data["close"][indices[-1]])
    gross_return = exit_price / entry - 1.0
    net_return = _net_execution_return(entry, exit_price, commission, slippage)
    outcome = {
        **base,
        f"future_return_{prefix}": gross_return,
        f"gross_return_{prefix}": gross_return,
        f"net_return_after_cost_{prefix}": net_return,
        f"entry_price_{prefix}": entry,
        f"exit_price_{prefix}": exit_price,
        f"exit_trade_date_{prefix}": str(data["dates"][indices[-1]]),
        f"mfe_{prefix}": float(data["high"][indices].max()) / entry - 1.0,
        f"mae_{prefix}": float(data["low"][indices].min()) / entry - 1.0,
        f"future_limit_up_count_{prefix}": int(data["up"][indices].sum()),
        f"future_limit_down_count_{prefix}": int(data["down"][indices].sum()),
        **_path_flags(data, indices, entry, prefix),
    }
    return _add_canonical_ten_day_aliases(outcome, prefix)


def _calendar_exact_indices(next_index: np.ndarray, offset: int, horizon: int) -> np.ndarray | None:
    expected = int(next_index[offset])
    indices: list[int] = []
    for step in range(horizon):
        if expected < 0 or expected != offset + step + 1:
            return None
        indices.append(expected)
        if step < horizon - 1:
            expected = int(next_index[expected])
    return np.asarray(indices, dtype=np.int64)


def _valid_adjusted_indices(data: dict[str, Any], indices: np.ndarray) -> bool:
    return bool(all(np.isfinite(data[name][indices]).all() and (data[name][indices] > 0).all() for name in ("open", "high", "low", "close")))


def _path_flags(data: dict[str, Any], indices: np.ndarray, entry: float, prefix: str) -> dict[str, Any]:
    take_profit_price = entry * (1.0 + TAKE_PROFIT)
    stop_loss_price = entry * (1.0 + STOP_LOSS)
    for index in indices:
        hit_tp = float(data["high"][index]) >= take_profit_price
        hit_sl = float(data["low"][index]) <= stop_loss_price
        if hit_tp and hit_sl:
            return {f"tp_before_sl_{prefix}": False, f"sl_before_tp_{prefix}": False, f"path_ambiguous_{prefix}": True}
        if hit_tp:
            return {f"tp_before_sl_{prefix}": True, f"sl_before_tp_{prefix}": False, f"path_ambiguous_{prefix}": False}
        if hit_sl:
            return {f"tp_before_sl_{prefix}": False, f"sl_before_tp_{prefix}": True, f"path_ambiguous_{prefix}": False}
    return {f"tp_before_sl_{prefix}": False, f"sl_before_tp_{prefix}": False, f"path_ambiguous_{prefix}": False}


def _prepare_for_aggregation(shard: pd.DataFrame) -> pd.DataFrame:
    required = {
        "trade_date", "symbol", "eligible_for_training", "future_return_10d", "net_return_after_cost_10d",
        "entry_price", "exit_price", "exit_trade_date", "mae_10d", "tp_before_sl_10d",
        "sl_before_tp_10d", "path_ambiguous_10d", "future_limit_down_count_10d",
    }
    missing = sorted(required - set(shard.columns))
    if missing:
        raise ValueError("labeled shard missing columns: " + ", ".join(missing))
    result = shard.copy()
    for column in (
        "market_median_future_return_10d", "market_median_net_return_10d", "industry_median_future_return_10d",
        "industry_median_net_return_10d", "future_return_percent_rank_10d", "net_return_percent_rank_10d",
        "future_return_bottom_percent_rank_10d", "relevance_grade_10d", "label_strong_path_10d",
        "label_severe_negative_10d", "market_state_10d",
    ):
        result[column] = pd.NA
    return result


def _all_trade_dates(shards: Mapping[str, pd.DataFrame]) -> list[str]:
    return sorted({str(date) for shard in shards.values() for date in shard["trade_date"].dropna().unique()})


def _eligible_rows_for_date(shards: Mapping[str, pd.DataFrame], trade_date: str) -> pd.DataFrame:
    rows = []
    for shard_key, shard in shards.items():
        eligible = shard[(shard["trade_date"] == trade_date) & shard["eligible_for_training"].eq(True) & shard["future_return_10d"].notna()].copy()
        if eligible.empty:
            continue
        eligible["_shard_key"] = shard_key
        eligible["_source_index"] = eligible.index
        rows.append(eligible)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _assign_full_market_date_labels(shards: Mapping[str, pd.DataFrame], eligible: pd.DataFrame, trade_date: str) -> None:
    gross_returns = pd.to_numeric(eligible["future_return_10d"], errors="coerce")
    returns = pd.to_numeric(eligible["net_return_after_cost_10d"], errors="coerce")
    top_rank = returns.rank(ascending=False, method="max", pct=True)
    bottom_rank = returns.rank(ascending=True, method="max", pct=True)
    market_median = float(gross_returns.median())
    market_net_median = float(returns.median())
    market_state = "weak" if market_net_median <= 0.0 else "normal"
    mae = pd.to_numeric(eligible["mae_10d"], errors="coerce")
    mfe = pd.to_numeric(eligible["mfe_10d"], errors="coerce")
    severe = (
        bottom_rank.le(0.10)
        | eligible["sl_before_tp_10d"].eq(True)
        | pd.to_numeric(eligible["future_limit_down_count_10d"], errors="coerce").gt(0)
        | mae.le(SEVERE_DRAWDOWN + 1e-12)
    )
    grades = pd.Series(0, index=eligible.index, dtype="int64")
    grades.loc[top_rank.le(0.50)] = 1
    grades.loc[top_rank.le(0.20) & returns.gt(0)] = 2
    grades.loc[top_rank.le(0.10) & mfe.ge(0.06 - 1e-12) & mae.gt(SEVERE_DRAWDOWN + 1e-12)] = 3
    # The contract is strict: an exact -6% MAE is not grade 4 despite binary-float noise.
    grades.loc[top_rank.le(0.05) & mfe.ge(0.08 - 1e-12) & mae.gt(STOP_LOSS + 1e-12)] = 4
    grades.loc[severe] = 0
    strong = grades.ge(3)
    industry_medians = eligible.assign(_gross_return=gross_returns).groupby("industry_l1", dropna=True)["_gross_return"].median()
    industry_net_medians = eligible.assign(_net_return=returns).groupby("industry_l1", dropna=True)["_net_return"].median()
    for row_index, row in eligible.iterrows():
        shard = shards[str(row["_shard_key"])]
        index = row["_source_index"]
        shard.at[index, "market_median_future_return_10d"] = market_median
        shard.at[index, "market_median_net_return_10d"] = market_net_median
        shard.at[index, "future_return_percent_rank_10d"] = float(top_rank.loc[row_index])
        shard.at[index, "net_return_percent_rank_10d"] = float(top_rank.loc[row_index])
        shard.at[index, "future_return_bottom_percent_rank_10d"] = float(bottom_rank.loc[row_index])
        shard.at[index, "relevance_grade_10d"] = int(grades.loc[row_index])
        shard.at[index, "label_strong_path_10d"] = bool(strong.loc[row_index])
        shard.at[index, "label_severe_negative_10d"] = bool(severe.loc[row_index])
        shard.at[index, "market_state_10d"] = market_state
        if pd.notna(row.get("industry_l1")):
            shard.at[index, "industry_median_future_return_10d"] = float(industry_medians.loc[row["industry_l1"]])
            shard.at[index, "industry_median_net_return_10d"] = float(industry_net_medians.loc[row["industry_l1"]])


def _combined_labeled_rows(labeled: pd.DataFrame | Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    if isinstance(labeled, Mapping):
        frames = list(labeled.values())
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return labeled.copy() if isinstance(labeled, pd.DataFrame) else pd.DataFrame()


def _add_canonical_ten_day_aliases(outcome: dict[str, Any], prefix: str) -> dict[str, Any]:
    if prefix == "10d":
        for name in ("entry_price", "exit_price", "exit_trade_date", "gross_return", "net_return_after_cost", "mfe", "mae"):
            outcome[name] = outcome[f"{name}_{prefix}"]
    return outcome


def _net_execution_return(entry: float, exit_price: float, commission: float, slippage: float) -> float:
    return ((exit_price * (1.0 - slippage)) / (entry * (1.0 + slippage))) * (1.0 - commission) ** 2 - 1.0


def _validate_execution_costs(commission: float, slippage: float) -> tuple[float, float]:
    commission = float(commission)
    slippage = float(slippage)
    if not math.isfinite(commission) or not math.isfinite(slippage) or commission < 0.0 or slippage < 0.0:
        raise ValueError("commission and slippage must be finite and non-negative")
    return commission, slippage
