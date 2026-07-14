"""Reproducible error samples for controlled ranking comparisons."""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd


_OUTPUT_COLUMNS = (
    "sample_type",
    "baseline",
    "quadrant",
    "fold",
    "trade_date",
    "symbol",
    "industry_l1",
    "market_state",
    "rank_no",
    "alpha_target_10d",
    "alpha_relevance_grade_10d",
    "net_return_after_cost_10d",
    "mae_10d",
    "severe_negative_10d",
)


def build_failure_samples(
    predictions: pd.DataFrame,
    *,
    baselines: Iterable[str],
    maximum_per_type: int = 100,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extract worst Top-5 losses and future leaders ranked below 100."""
    required = {
        "trade_date", "symbol", "fold", "quadrant", "industry_l1", "market_state",
        "alpha_target_10d", "alpha_relevance_grade_10d", "alpha_top10_10d",
        "net_return_after_cost_10d", "mae_10d", "severe_negative_10d",
    }
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError("failure analysis missing columns: " + ", ".join(missing))
    limit = max(1, int(maximum_per_type))
    output = []
    concentration: dict[str, dict[str, Any]] = {}
    for quadrant, quadrant_rows in predictions.groupby("quadrant", sort=True):
        quadrant_name = str(quadrant)
        concentration[quadrant_name] = {}
        for baseline in baselines:
            score = f"score__{baseline}"
            if score not in quadrant_rows:
                raise ValueError(f"failure analysis missing score column: {score}")
            rows = quadrant_rows.copy()
            rows["rank_no"] = rows.groupby("trade_date", sort=False)[score].rank(
                method="first", ascending=False
            )
            losses = rows.loc[
                rows["rank_no"].le(5) & rows["net_return_after_cost_10d"].lt(0)
            ].nsmallest(limit, "net_return_after_cost_10d").copy()
            losses["sample_type"] = "high_ranked_loss"
            losses["baseline"] = baseline
            missed = rows.loc[
                rows["alpha_top10_10d"].eq(True) & rows["rank_no"].gt(100)
            ].nlargest(limit, "alpha_target_10d").copy()
            missed["sample_type"] = "missed_future_leader"
            missed["baseline"] = baseline
            output.extend((losses[list(_OUTPUT_COLUMNS)], missed[list(_OUTPUT_COLUMNS)]))
            top = rows.loc[rows["rank_no"].le(5)]
            counts = top["industry_l1"].fillna("UNKNOWN").astype(str).value_counts()
            concentration[quadrant_name][baseline] = {
                "top_industry": str(counts.index[0]) if not counts.empty else None,
                "top_industry_count": int(counts.iloc[0]) if not counts.empty else 0,
                "top_industry_share": float(counts.iloc[0] / len(top)) if len(top) else 0.0,
                "selected_rows": int(len(top)),
            }
    samples = pd.concat(output, ignore_index=True) if output else pd.DataFrame(columns=_OUTPUT_COLUMNS)
    samples = samples.sort_values(
        ["sample_type", "baseline", "quadrant", "trade_date", "rank_no"], kind="stable"
    ).reset_index(drop=True)
    return samples, {
        "sample_row_count": int(len(samples)),
        "sample_type_counts": {
            str(key): int(value) for key, value in samples["sample_type"].value_counts().items()
        },
        "industry_concentration": concentration,
    }
