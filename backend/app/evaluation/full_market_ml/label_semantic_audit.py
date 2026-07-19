"""Read-only semantic audit for competing ten-session research labels."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .decision_labels import (
    ACTIONABLE_COLUMN,
    SEVERE_COLUMN,
    DecisionLabelContract,
    add_decision_labels,
)


_REQUIRED_COLUMNS = {
    "trade_date",
    "symbol",
    "eligible_for_training_10d",
    "entry_tradeable_10d",
    "horizon_available_10d",
    "net_return_after_cost_10d",
    "mfe_10d",
    "mae_10d",
    "sl_before_tp_10d",
    "path_ambiguous_10d",
    "future_limit_down_count_10d",
    "label_strong_path_10d",
    "label_severe_negative_10d",
    "alpha_top10_10d",
    "severe_negative_10d",
}


class LabelSemanticAuditError(ValueError):
    """Raised when label-audit input cannot preserve the registered data scope."""


def audit_label_semantics(rows: pd.DataFrame, *, development_dates: tuple[str, ...]) -> dict[str, Any]:
    """Compare stored ranking labels with reconstructable path and decision views.

    This function intentionally reads future outcome fields only to audit label
    semantics. Its output must never be used as a signal-time feature or for
    selecting a production model.
    """
    data = _normalize_rows(rows, development_dates)
    legacy = _reconstruct_legacy_labels(data)
    decision = add_decision_labels(data, DecisionLabelContract())
    for column in legacy:
        decision[column] = legacy[column]

    stored_old = _truth(decision["label_strong_path_10d"])
    stored_old_severe = _truth(decision["label_severe_negative_10d"])
    alpha_top10 = _truth(decision["alpha_top10_10d"])
    alpha_severe = _truth(decision["severe_negative_10d"])
    decision_actionable = _truth(decision[ACTIONABLE_COLUMN])
    decision_severe = _truth(decision[SEVERE_COLUMN])
    reconstructed_old = _truth(decision["legacy_strong_reconstructed"])
    reconstructed_old_severe = _truth(decision["legacy_severe_reconstructed"])

    daily = _daily_distribution(
        decision,
        {
            "old_strong": stored_old,
            "alpha_top10": alpha_top10,
            "decision_actionable": decision_actionable,
            "old_severe": stored_old_severe,
            "alpha_severe": alpha_severe,
            "decision_severe": decision_severe,
        },
    )
    mismatch = stored_old.ne(reconstructed_old) | stored_old_severe.ne(reconstructed_old_severe)
    overlap = {
        "old_strong_vs_alpha_top10": _overlap(stored_old, alpha_top10),
        "old_strong_vs_decision_actionable": _overlap(stored_old, decision_actionable),
        "old_severe_vs_alpha_severe": _overlap(stored_old_severe, alpha_severe),
        "old_severe_vs_decision_severe": _overlap(stored_old_severe, decision_severe),
        "alpha_severe_vs_decision_severe": _overlap(alpha_severe, decision_severe),
        "decision_actionable_vs_decision_severe": _overlap(decision_actionable, decision_severe),
    }
    return {
        "status": "complete",
        "research_only": True,
        "production_integration_allowed": False,
        "row_count": int(len(decision)),
        "date_count": int(decision["trade_date"].nunique()),
        "symbol_count": int(decision["symbol"].nunique()),
        "old_label_reconstruction_mismatch_count": int(mismatch.sum()),
        "old_label_reconstruction_matches_stored": not bool(mismatch.any()),
        "label_rates": {
            "old_strong": _rate(stored_old),
            "alpha_top10": _rate(alpha_top10),
            "decision_actionable": _rate(decision_actionable),
            "old_severe": _rate(stored_old_severe),
            "alpha_severe": _rate(alpha_severe),
            "decision_severe": _rate(decision_severe),
        },
        "overlap": overlap,
        "disagreement_reasons": _disagreement_reasons(decision, stored_old, alpha_top10),
        "outcome_summary": _outcome_summary(decision, stored_old, alpha_top10, decision_actionable),
        "daily_distribution": daily,
    }


def _normalize_rows(rows: pd.DataFrame, development_dates: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("label semantic audit rows must be a pandas DataFrame")
    dates = tuple(sorted({str(value) for value in development_dates}))
    if not dates:
        raise LabelSemanticAuditError("registered development dates are required")
    missing = sorted(_REQUIRED_COLUMNS - set(rows.columns))
    if missing:
        raise LabelSemanticAuditError("label semantic audit rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if result["trade_date"].isna().any() or result["symbol"].eq("").any():
        raise LabelSemanticAuditError("label semantic audit rows contain invalid trade_date or symbol")
    outside = sorted(set(result["trade_date"]) - set(dates))
    if outside:
        raise LabelSemanticAuditError("rows outside the registered development dates: " + ", ".join(outside[:3]))
    if result.duplicated(["trade_date", "symbol"]).any():
        raise LabelSemanticAuditError("label semantic audit rows contain duplicate trade_date and symbol keys")
    result = result.loc[result["eligible_for_training_10d"].eq(True)].copy()
    if result.empty:
        raise LabelSemanticAuditError("label semantic audit has no eligible ten-session rows")
    required_finite = ("net_return_after_cost_10d", "mfe_10d", "mae_10d", "future_limit_down_count_10d")
    for column in required_finite:
        values = pd.to_numeric(result[column], errors="coerce")
        if not np.isfinite(values).all():
            raise LabelSemanticAuditError(f"label semantic audit has incomplete eligible outcomes: {column}")
        result[column] = values
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _reconstruct_legacy_labels(rows: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=rows.index)
    result["legacy_top10_return_reconstructed"] = False
    result["legacy_severe_reconstructed"] = False
    result["legacy_strong_reconstructed"] = False
    for _, index in rows.groupby("trade_date", sort=True).groups.items():
        current = rows.loc[index]
        returns = pd.to_numeric(current["net_return_after_cost_10d"], errors="coerce")
        top_rank = returns.rank(ascending=False, method="max", pct=True)
        bottom_rank = returns.rank(ascending=True, method="max", pct=True)
        severe = (
            bottom_rank.le(0.10)
            | _truth(current["sl_before_tp_10d"])
            | pd.to_numeric(current["future_limit_down_count_10d"], errors="coerce").gt(0)
            | pd.to_numeric(current["mae_10d"], errors="coerce").le(-0.08 + 1e-12)
        )
        pre_severe_strong = (
            top_rank.le(0.10)
            & pd.to_numeric(current["mfe_10d"], errors="coerce").ge(0.06 - 1e-12)
            & pd.to_numeric(current["mae_10d"], errors="coerce").gt(-0.08 + 1e-12)
        )
        result.loc[index, "legacy_top10_return_reconstructed"] = top_rank.le(0.10).to_numpy()
        result.loc[index, "legacy_severe_reconstructed"] = severe.to_numpy()
        result.loc[index, "legacy_strong_reconstructed"] = (pre_severe_strong & ~severe).to_numpy()
    return result


def _daily_distribution(rows: pd.DataFrame, labels: dict[str, pd.Series]) -> pd.DataFrame:
    result = rows[["trade_date"]].copy()
    for name, values in labels.items():
        result[name] = values.to_numpy(dtype=bool)
    daily = result.groupby("trade_date", sort=True).agg(eligible_count=("trade_date", "size"))
    for name in labels:
        daily[f"{name}_count"] = result.groupby("trade_date", sort=True)[name].sum()
        daily[f"{name}_rate"] = daily[f"{name}_count"] / daily["eligible_count"]
    return daily.reset_index()


def _disagreement_reasons(rows: pd.DataFrame, old_strong: pd.Series, alpha_top10: pd.Series) -> dict[str, Any]:
    alpha_not_old = alpha_top10 & ~old_strong
    relevant = rows.loc[alpha_not_old]
    if relevant.empty:
        return {"alpha_top10_not_old": {"count": 0, "exclusive_reason_counts": {}}}
    severe = _truth(relevant["legacy_severe_reconstructed"])
    not_old_top10 = ~_truth(relevant["legacy_top10_return_reconstructed"])
    mfe_low = pd.to_numeric(relevant["mfe_10d"], errors="coerce").lt(0.06 - 1e-12)
    reasons = pd.Series("unclassified", index=relevant.index, dtype="string")
    reasons.loc[mfe_low & ~severe & ~not_old_top10] = "mfe_below_6pct"
    reasons.loc[not_old_top10 & ~severe] = "not_old_net_return_top10"
    reasons.loc[severe] = "severe_override"
    counts = reasons.value_counts().to_dict()
    return {
        "alpha_top10_not_old": {
            "count": int(len(relevant)),
            "exclusive_reason_counts": {str(name): int(count) for name, count in sorted(counts.items())},
            "severe_component_rates": {
                "sl_before_tp": _rate(_truth(relevant["sl_before_tp_10d"])),
                "limit_down": _rate(pd.to_numeric(relevant["future_limit_down_count_10d"], errors="coerce").gt(0)),
                "mae_at_or_below_8pct": _rate(pd.to_numeric(relevant["mae_10d"], errors="coerce").le(-0.08 + 1e-12)),
            },
        }
    }


def _outcome_summary(
    rows: pd.DataFrame,
    old_strong: pd.Series,
    alpha_top10: pd.Series,
    decision_actionable: pd.Series,
) -> dict[str, dict[str, float | int]]:
    groups = {
        "all_eligible": pd.Series(True, index=rows.index),
        "old_strong": old_strong,
        "alpha_top10": alpha_top10,
        "decision_actionable": decision_actionable,
    }
    return {
        name: {
            "count": int(mask.sum()),
            "mean_net_return_after_cost_10d": float(pd.to_numeric(rows.loc[mask, "net_return_after_cost_10d"], errors="coerce").mean()),
            "mean_mfe_10d": float(pd.to_numeric(rows.loc[mask, "mfe_10d"], errors="coerce").mean()),
            "mean_mae_10d": float(pd.to_numeric(rows.loc[mask, "mae_10d"], errors="coerce").mean()),
        }
        for name, mask in groups.items()
    }


def _overlap(left: pd.Series, right: pd.Series) -> dict[str, float | int]:
    both = left & right
    union = left | right
    return {
        "left_count": int(left.sum()),
        "right_count": int(right.sum()),
        "intersection_count": int(both.sum()),
        "left_only_count": int((left & ~right).sum()),
        "right_only_count": int((right & ~left).sum()),
        "union_count": int(union.sum()),
        "jaccard": float(both.sum() / union.sum()) if bool(union.any()) else 1.0,
    }


def _rate(values: pd.Series) -> float:
    return float(values.mean()) if len(values) else 0.0


def _truth(values: pd.Series) -> pd.Series:
    return values.eq(True).fillna(False).astype(bool)
