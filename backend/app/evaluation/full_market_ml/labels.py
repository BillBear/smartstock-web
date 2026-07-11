"""Read-only, next-open forward labels for full-market ML research."""
from __future__ import annotations

import math
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
    """Attach adjusted, T+1-entry outcomes without changing source panel rows."""
    del config  # The current immutable config has no label section; constants are fixed research contract values.
    panel = _normalize_panel(panel_shard)
    if panel.empty:
        panel.attrs["label_report"] = build_label_report(panel)
        return panel

    labeled = panel.copy()
    for horizon in HORIZONS:
        values: list[dict[str, Any]] = []
        for _, rows in labeled.groupby("symbol", sort=False):
            values.extend(_forward_outcome(rows.reset_index(drop=True), offset, horizon) for offset in range(len(rows)))
        outcome_frame = pd.DataFrame(values, index=labeled.index)
        for column in outcome_frame:
            labeled[column] = outcome_frame[column]

    labeled = _attach_cross_section_labels(labeled)
    report = build_label_report(labeled)
    assert_label_distribution_invariants(labeled, require_full_development_period=False)
    labeled.attrs["label_report"] = report
    return labeled


def daily_relevance_distribution(labeled_shard: pd.DataFrame) -> pd.DataFrame:
    """Return per-date eligible counts, grades, path ambiguity, and market state."""
    if labeled_shard is None or labeled_shard.empty or "trade_date" not in labeled_shard:
        return pd.DataFrame(
            columns=[
                "trade_date", "eligible_count", "grade_4_count", "grade_3_or_higher_count",
                "strong_label_count", "path_ambiguity_count", "market_state",
            ]
        )
    rows = []
    for trade_date, group in labeled_shard.groupby("trade_date", sort=True):
        eligible = group[group.get("eligible_for_training", pd.Series(False, index=group.index)).eq(True)]
        grades = pd.to_numeric(eligible.get("relevance_grade_10d"), errors="coerce")
        strong = eligible.get("label_strong_path_10d", pd.Series(pd.NA, index=eligible.index, dtype="boolean")).eq(True)
        ambiguous = eligible.get("path_ambiguous_10d", pd.Series(pd.NA, index=eligible.index, dtype="boolean")).eq(True)
        states = eligible.get("market_state_10d", pd.Series("unavailable", index=eligible.index)).dropna()
        rows.append(
            {
                "trade_date": str(trade_date),
                "eligible_count": int(len(eligible)),
                "grade_4_count": int(grades.eq(4).sum()),
                "grade_3_or_higher_count": int(grades.ge(3).sum()),
                "strong_label_count": int(strong.sum()),
                "path_ambiguity_count": int(ambiguous.sum()),
                "market_state": str(states.iloc[0]) if not states.empty else "unavailable",
            }
        )
    return pd.DataFrame(rows)


def build_label_report(labeled_shard: pd.DataFrame) -> dict[str, Any]:
    """Summarise target availability and daily relevance without performing I/O."""
    distribution = daily_relevance_distribution(labeled_shard)
    eligible_count = int(distribution["eligible_count"].sum()) if not distribution.empty else 0
    strong_count = int(distribution["strong_label_count"].sum()) if not distribution.empty else 0
    ambiguity_count = int(distribution["path_ambiguity_count"].sum()) if not distribution.empty else 0
    weak_without_strong = distribution[
        distribution["market_state"].eq("weak") & distribution["strong_label_count"].eq(0)
    ] if not distribution.empty else distribution
    return {
        "row_count": int(len(labeled_shard)) if labeled_shard is not None else 0,
        "eligible_count_10d": eligible_count,
        "strong_label_count_10d": strong_count,
        "strong_label_rate_10d": (strong_count / eligible_count) if eligible_count else None,
        "path_ambiguity_count_10d": ambiguity_count,
        "weak_market_zero_strong_date_count_10d": int(len(weak_without_strong)),
        "weak_market_zero_strong_dates_10d": weak_without_strong["trade_date"].tolist() if not weak_without_strong.empty else [],
        "daily_relevance_distribution_10d": distribution.to_dict("records"),
    }


def assert_label_distribution_invariants(
    labeled_shard: pd.DataFrame, *, require_full_development_period: bool = False
) -> None:
    """Enforce daily grade caps and, only for a complete period, target prevalence."""
    distribution = daily_relevance_distribution(labeled_shard)
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
    required = {"trade_date", "symbol", "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"}
    missing = sorted(required - set(panel_shard.columns))
    if missing:
        raise ValueError("panel_shard missing columns: " + ", ".join(missing))
    panel = panel_shard.copy()
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    panel["symbol"] = panel["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    panel = panel.dropna(subset=["trade_date"])
    for column in ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"):
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    for column in ("eligible_signal_day", "entry_tradeable"):
        panel[column] = panel.get(column, pd.Series(False, index=panel.index)).eq(True)
    if "industry_l1" not in panel:
        panel["industry_l1"] = pd.NA
    return panel.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _forward_outcome(rows: pd.DataFrame, offset: int, horizon: int) -> dict[str, Any]:
    prefix = f"{horizon}d"
    current = rows.iloc[offset]
    window = rows.iloc[offset + 1 : offset + horizon + 1]
    available = len(window) == horizon and _valid_adjusted_window(window)
    eligible = bool(current["eligible_signal_day"] and current["entry_tradeable"] and available)
    base = {
        f"horizon_available_{prefix}": bool(available),
        f"eligible_for_training_{prefix}": bool(eligible),
    }
    if not available:
        return {
            **base,
            f"future_return_{prefix}": math.nan,
            f"mfe_{prefix}": math.nan,
            f"mae_{prefix}": math.nan,
            f"tp_before_sl_{prefix}": pd.NA,
            f"sl_before_tp_{prefix}": pd.NA,
            f"path_ambiguous_{prefix}": pd.NA,
        }
    entry = float(window.iloc[0]["adjusted_open"])
    exit_price = float(window.iloc[-1]["adjusted_close"])
    return {
        **base,
        f"future_return_{prefix}": exit_price / entry - 1.0,
        f"mfe_{prefix}": float(window["adjusted_high"].max()) / entry - 1.0,
        f"mae_{prefix}": float(window["adjusted_low"].min()) / entry - 1.0,
        **_path_flags(window, entry, prefix),
    }


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


def _attach_cross_section_labels(labeled: pd.DataFrame) -> pd.DataFrame:
    result = labeled.copy()
    result["eligible_for_training"] = result["eligible_for_training_10d"].eq(True)
    for column in (
        "market_median_future_return_10d", "industry_median_future_return_10d", "relevance_grade_10d",
        "label_strong_path_10d", "label_severe_negative_10d", "market_state_10d",
    ):
        result[column] = pd.NA
    for _, rows in result.groupby("trade_date", sort=False):
        eligible = rows[rows["eligible_for_training"] & rows["future_return_10d"].notna()]
        if eligible.empty:
            continue
        market_median = float(eligible["future_return_10d"].median())
        market_state = "weak" if market_median <= 0.0 else "normal"
        result.loc[eligible.index, "market_median_future_return_10d"] = market_median
        result.loc[eligible.index, "market_state_10d"] = market_state
        industry_medians = eligible.groupby("industry_l1", dropna=True)["future_return_10d"].median()
        for index, row in eligible.iterrows():
            if pd.notna(row["industry_l1"]):
                result.at[index, "industry_median_future_return_10d"] = float(industry_medians.loc[row["industry_l1"]])
        _assign_relevance_grades(result, eligible, market_median, market_state)
    result["relevance_grade_10d"] = pd.array(result["relevance_grade_10d"], dtype="Int64")
    for column in ("label_strong_path_10d", "label_severe_negative_10d"):
        result[column] = pd.array(result[column], dtype="boolean")
    return result


def _assign_relevance_grades(result: pd.DataFrame, eligible: pd.DataFrame, market_median: float, market_state: str) -> None:
    severe = eligible["mae_10d"].le(SEVERE_DRAWDOWN)
    result.loc[eligible.index, "label_severe_negative_10d"] = severe
    grades = pd.Series(1, index=eligible.index, dtype="int64")
    grades.loc[eligible["future_return_10d"].gt(market_median)] = 2
    grades.loc[severe] = 0
    clean_path = eligible["tp_before_sl_10d"].eq(True) & ~eligible["path_ambiguous_10d"].eq(True) & ~severe
    if market_state == "normal":
        ordered = eligible.loc[clean_path].sort_values(["future_return_10d", "symbol"], ascending=[False, True], kind="stable")
        grade_four_count = math.floor(len(eligible) * 0.05)
        grade_three_count = math.floor(len(eligible) * 0.10)
        grades.loc[ordered.index[:grade_three_count]] = 3
        grades.loc[ordered.index[:grade_four_count]] = 4
    result.loc[eligible.index, "relevance_grade_10d"] = grades
    result.loc[eligible.index, "label_strong_path_10d"] = grades.ge(3)
