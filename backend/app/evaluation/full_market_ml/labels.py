"""Read-only, next-open forward labels for full-market ML research."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

from .config import FullMarketMLConfig


HORIZONS = (3, 5, 10, 20)
TAKE_PROFIT = 0.08
STOP_LOSS = -0.06
SEVERE_DRAWDOWN = -0.08
MIN_DAILY_INVARIANT_ELIGIBLE = 1000


class LabelDistributionError(ValueError):
    """Raised when a full-market label distribution violates its fixed bounds."""


def build_forward_labels(config: FullMarketMLConfig, panel_shard: pd.DataFrame) -> pd.DataFrame:
    """Build shard-local outcomes; call ``aggregate_full_market_labels`` for grades.

    ``next_open_date`` is an immutable panel calendar contract. Following that
    chain prevents an absent session from being silently replaced by a later bar.
    """
    del config
    panel = _normalize_panel(panel_shard)
    if panel.empty:
        return panel
    labeled = panel.copy()
    for horizon in HORIZONS:
        values: list[dict[str, Any]] = []
        for _, rows in labeled.groupby("symbol", sort=False):
            symbol_rows = rows.reset_index(drop=True)
            date_index = {str(row.trade_date): row for row in symbol_rows.itertuples(index=False)}
            values.extend(_forward_outcome(symbol_rows, offset, horizon, date_index) for offset in range(len(symbol_rows)))
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


def _forward_outcome(rows: pd.DataFrame, offset: int, horizon: int, date_index: dict[str, Any]) -> dict[str, Any]:
    prefix = f"{horizon}d"
    window = _calendar_exact_window(rows, offset, horizon, date_index)
    available = window is not None and _valid_adjusted_window(window)
    current = rows.iloc[offset]
    eligible = bool(current["eligible_signal_day"] and current["entry_tradeable"] and available)
    base = {f"horizon_available_{prefix}": bool(available), f"eligible_for_training_{prefix}": bool(eligible)}
    if not available:
        return {
            **base,
            f"future_return_{prefix}": math.nan,
            f"mfe_{prefix}": math.nan,
            f"mae_{prefix}": math.nan,
            f"future_limit_up_count_{prefix}": pd.NA,
            f"future_limit_down_count_{prefix}": pd.NA,
            f"tp_before_sl_{prefix}": pd.NA,
            f"sl_before_tp_{prefix}": pd.NA,
            f"path_ambiguous_{prefix}": pd.NA,
        }
    entry = float(window.iloc[0]["adjusted_open"])
    return {
        **base,
        f"future_return_{prefix}": float(window.iloc[-1]["adjusted_close"]) / entry - 1.0,
        f"mfe_{prefix}": float(window["adjusted_high"].max()) / entry - 1.0,
        f"mae_{prefix}": float(window["adjusted_low"].min()) / entry - 1.0,
        f"future_limit_up_count_{prefix}": int(window["at_up_limit"].sum()),
        f"future_limit_down_count_{prefix}": int(window["at_down_limit"].sum()),
        **_path_flags(window, entry, prefix),
    }


def _calendar_exact_window(rows: pd.DataFrame, offset: int, horizon: int, date_index: dict[str, Any]) -> pd.DataFrame | None:
    expected_date = rows.iloc[offset]["next_open_date"]
    window = []
    for step in range(horizon):
        if pd.isna(expected_date) or not expected_date:
            return None
        row = date_index.get(str(expected_date))
        if row is None:
            return None
        window.append(row._asdict())
        if step < horizon - 1:
            expected_date = row.next_open_date
    return pd.DataFrame(window)


def _valid_adjusted_window(window: pd.DataFrame) -> bool:
    values = window[["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"]]
    return bool(values.notna().all().all() and values.gt(0).all().all())


def _path_flags(window: pd.DataFrame, entry: float, prefix: str) -> dict[str, Any]:
    take_profit_price = entry * (1.0 + TAKE_PROFIT)
    stop_loss_price = entry * (1.0 + STOP_LOSS)
    for row in window.itertuples(index=False):
        hit_tp = float(row.adjusted_high) >= take_profit_price
        hit_sl = float(row.adjusted_low) <= stop_loss_price
        if hit_tp and hit_sl:
            return {f"tp_before_sl_{prefix}": False, f"sl_before_tp_{prefix}": False, f"path_ambiguous_{prefix}": True}
        if hit_tp:
            return {f"tp_before_sl_{prefix}": True, f"sl_before_tp_{prefix}": False, f"path_ambiguous_{prefix}": False}
        if hit_sl:
            return {f"tp_before_sl_{prefix}": False, f"sl_before_tp_{prefix}": True, f"path_ambiguous_{prefix}": False}
    return {f"tp_before_sl_{prefix}": False, f"sl_before_tp_{prefix}": False, f"path_ambiguous_{prefix}": False}


def _prepare_for_aggregation(shard: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "symbol", "eligible_for_training", "future_return_10d", "mae_10d", "tp_before_sl_10d", "sl_before_tp_10d", "path_ambiguous_10d", "future_limit_down_count_10d"}
    missing = sorted(required - set(shard.columns))
    if missing:
        raise ValueError("labeled shard missing columns: " + ", ".join(missing))
    result = shard.copy()
    for column in ("market_median_future_return_10d", "industry_median_future_return_10d", "future_return_percent_rank_10d", "future_return_bottom_percent_rank_10d", "relevance_grade_10d", "label_strong_path_10d", "label_severe_negative_10d", "market_state_10d"):
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
    returns = pd.to_numeric(eligible["future_return_10d"], errors="coerce")
    top_rank = returns.rank(ascending=False, method="max", pct=True)
    bottom_rank = returns.rank(ascending=True, method="max", pct=True)
    market_median = float(returns.median())
    market_state = "weak" if market_median <= 0.0 else "normal"
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
    industry_medians = eligible.groupby("industry_l1", dropna=True)["future_return_10d"].median()
    for row_index, row in eligible.iterrows():
        shard = shards[str(row["_shard_key"])]
        index = row["_source_index"]
        shard.at[index, "market_median_future_return_10d"] = market_median
        shard.at[index, "future_return_percent_rank_10d"] = float(top_rank.loc[row_index])
        shard.at[index, "future_return_bottom_percent_rank_10d"] = float(bottom_rank.loc[row_index])
        shard.at[index, "relevance_grade_10d"] = int(grades.loc[row_index])
        shard.at[index, "label_strong_path_10d"] = bool(strong.loc[row_index])
        shard.at[index, "label_severe_negative_10d"] = bool(severe.loc[row_index])
        shard.at[index, "market_state_10d"] = market_state
        if pd.notna(row.get("industry_l1")):
            shard.at[index, "industry_median_future_return_10d"] = float(industry_medians.loc[row["industry_l1"]])


def _combined_labeled_rows(labeled: pd.DataFrame | Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    if isinstance(labeled, Mapping):
        frames = list(labeled.values())
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return labeled.copy() if isinstance(labeled, pd.DataFrame) else pd.DataFrame()
