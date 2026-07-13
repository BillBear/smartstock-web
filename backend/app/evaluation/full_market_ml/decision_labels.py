"""Decision-aligned labels derived from canonical ten-session execution outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


ACTIONABLE_COLUMN = "label_actionable_positive_10d"
SEVERE_COLUMN = "label_severe_negative_10d_v2"
CLIPPED_RETURN_COLUMN = "target_clipped_return_10d"
RELEVANCE_COLUMN = "return_relevance_grade_10d_v2"

_REQUIRED_COLUMNS = {
    "trade_date",
    "symbol",
    "eligible_for_training_10d",
    "entry_tradeable_10d",
    "net_return_after_cost_10d",
    "mae_10d",
    "sl_before_tp_10d",
    "path_ambiguous_10d",
    "future_limit_down_count_10d",
}
_STRATA_COLUMNS = ("board", "industry_l1", "size_bucket", "liquidity_bucket")


@dataclass(frozen=True)
class DecisionLabelContract:
    """Frozen absolute thresholds for the ten-session decision objective."""

    horizon: int = 10
    actionable_return_floor: float = 0.03
    actionable_mae_floor: float = -0.06
    severe_return_ceiling: float = -0.05
    severe_mae_ceiling: float = -0.08
    clipped_return_floor: float = -0.15
    clipped_return_ceiling: float = 0.20

    def validate(self) -> None:
        if self.horizon != 10:
            raise ValueError("decision label contract currently supports horizon=10 only")
        values = np.asarray(
            [
                self.actionable_return_floor,
                self.actionable_mae_floor,
                self.severe_return_ceiling,
                self.severe_mae_ceiling,
                self.clipped_return_floor,
                self.clipped_return_ceiling,
            ],
            dtype=float,
        )
        if not np.isfinite(values).all():
            raise ValueError("decision label thresholds must be finite")
        if self.severe_return_ceiling >= self.actionable_return_floor:
            raise ValueError("severe return ceiling must be below actionable return floor")
        if self.severe_mae_ceiling >= self.actionable_mae_floor:
            raise ValueError("severe MAE ceiling must be below actionable MAE floor")
        if self.clipped_return_floor >= self.clipped_return_ceiling:
            raise ValueError("clipped return floor must be below its ceiling")


def add_decision_labels(
    rows: pd.DataFrame, contract: DecisionLabelContract | None = None
) -> pd.DataFrame:
    """Add absolute labels without recomputing or reinterpreting execution outcomes."""
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    missing = sorted(_REQUIRED_COLUMNS - set(rows.columns))
    if missing:
        raise ValueError("decision labels missing canonical columns: " + ", ".join(missing))
    contract = contract or DecisionLabelContract()
    contract.validate()

    labeled = rows.copy()
    eligible = _true_mask(labeled["eligible_for_training_10d"])
    tradeable = _true_mask(labeled["entry_tradeable_10d"])
    sl_before_tp = _true_mask(labeled["sl_before_tp_10d"])
    ambiguous = _true_mask(labeled["path_ambiguous_10d"])
    returns = pd.to_numeric(labeled["net_return_after_cost_10d"], errors="coerce")
    mae = pd.to_numeric(labeled["mae_10d"], errors="coerce")
    limit_down = pd.to_numeric(labeled["future_limit_down_count_10d"], errors="coerce")
    complete = _outcome_complete(labeled, returns, mae, limit_down)

    actionable = (
        eligible
        & tradeable
        & complete
        & returns.ge(contract.actionable_return_floor)
        & mae.ge(contract.actionable_mae_floor)
        & ~sl_before_tp
        & ~ambiguous
        & limit_down.eq(0)
    )
    severe = (
        eligible
        & complete
        & (
            returns.le(contract.severe_return_ceiling)
            | mae.le(contract.severe_mae_ceiling)
            | sl_before_tp
            | limit_down.gt(0)
        )
    )
    overlap = actionable & severe
    if bool(overlap.any()):
        raise ValueError("actionable and severe decision labels overlap")

    labeled[ACTIONABLE_COLUMN] = actionable.astype(bool)
    labeled[SEVERE_COLUMN] = severe.astype(bool)
    labeled[CLIPPED_RETURN_COLUMN] = returns.clip(
        lower=contract.clipped_return_floor, upper=contract.clipped_return_ceiling
    )
    values = returns.to_numpy(dtype=float, na_value=np.nan)
    grades = np.select(
        [values <= 0.0, values < 0.03, values < 0.05, values < 0.08],
        [0, 1, 2, 3],
        default=4,
    )
    relevance = pd.Series(grades, index=labeled.index, dtype="Int64")
    relevance.loc[~np.isfinite(values)] = pd.NA
    labeled[RELEVANCE_COLUMN] = relevance
    labeled.attrs["decision_label_report"] = build_decision_label_report(labeled)
    return labeled


def build_decision_label_report(rows: pd.DataFrame) -> dict[str, Any]:
    """Summarize label availability, class absence, and available strata."""
    required = _REQUIRED_COLUMNS | {ACTIONABLE_COLUMN, SEVERE_COLUMN, RELEVANCE_COLUMN}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("decision label report missing columns: " + ", ".join(missing))

    frame = rows.reset_index(drop=True).copy()
    returns = pd.to_numeric(frame["net_return_after_cost_10d"], errors="coerce")
    mae = pd.to_numeric(frame["mae_10d"], errors="coerce")
    limits = pd.to_numeric(frame["future_limit_down_count_10d"], errors="coerce")
    complete = _outcome_complete(frame, returns, mae, limits)
    frame["_complete"] = complete
    frame["_eligible"] = _true_mask(frame["eligible_for_training_10d"])
    frame["_actionable"] = _true_mask(frame[ACTIONABLE_COLUMN])
    frame["_severe"] = _true_mask(frame[SEVERE_COLUMN])
    frame["_neutral"] = (
        complete & frame["_eligible"] & ~frame["_actionable"] & ~frame["_severe"]
    )
    frame["_entry_untradeable"] = ~_true_mask(frame["entry_tradeable_10d"])

    daily = [_distribution_record(str(date), group) for date, group in frame.groupby("trade_date", sort=True)]
    no_actionable = [item["trade_date"] for item in daily if item["actionable_count"] == 0]
    no_severe = [item["trade_date"] for item in daily if item["severe_count"] == 0]
    strata: dict[str, list[dict[str, Any]]] = {}
    for column in _STRATA_COLUMNS:
        if column not in frame:
            continue
        records = []
        values = frame[column].astype("string").fillna("unavailable")
        for stratum, indexes in values.groupby(values, sort=True).groups.items():
            record = _distribution_record(str(stratum), frame.loc[indexes])
            record["stratum"] = record.pop("trade_date")
            records.append(record)
        strata[column] = records

    return {
        "row_count": int(len(frame)),
        "actionable_count_10d": int(frame["_actionable"].sum()),
        "severe_count_10d": int(frame["_severe"].sum()),
        "neutral_count_10d": int(frame["_neutral"].sum()),
        "incomplete_count_10d": int((~frame["_complete"]).sum()),
        "entry_untradeable_count_10d": int(frame["_entry_untradeable"].sum()),
        "overlap_count_10d": int((frame["_actionable"] & frame["_severe"]).sum()),
        "dates_without_actionable_10d": no_actionable,
        "dates_without_severe_10d": no_severe,
        "daily_distribution_10d": daily,
        "strata_distribution_10d": strata,
    }


def _distribution_record(key: str, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "trade_date": key,
        "row_count": int(len(frame)),
        "actionable_count": int(frame["_actionable"].sum()),
        "severe_count": int(frame["_severe"].sum()),
        "neutral_count": int(frame["_neutral"].sum()),
        "incomplete_count": int((~frame["_complete"]).sum()),
        "entry_untradeable_count": int(frame["_entry_untradeable"].sum()),
    }


def _true_mask(values: pd.Series) -> pd.Series:
    return values.eq(True).fillna(False).astype(bool)  # noqa: E712


def _finite_mask(values: pd.Series) -> pd.Series:
    return pd.Series(np.isfinite(values.to_numpy(dtype=float, na_value=np.nan)), index=values.index)


def _outcome_complete(
    frame: pd.DataFrame, returns: pd.Series, mae: pd.Series, limit_down: pd.Series
) -> pd.Series:
    complete = (
        _finite_mask(returns)
        & _finite_mask(mae)
        & _finite_mask(limit_down)
        & frame[
            [
                "eligible_for_training_10d",
                "entry_tradeable_10d",
                "sl_before_tp_10d",
                "path_ambiguous_10d",
            ]
        ].notna().all(axis=1)
    )
    if "horizon_available_10d" in frame:
        complete &= _true_mask(frame["horizon_available_10d"])
    return complete
