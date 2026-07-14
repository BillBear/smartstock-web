"""Daily cross-sectional alpha labels for ranking research."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


MIN_INDUSTRY_PEERS = 30
MIN_OBJECTIVE_AUDIT_ELIGIBLE = 1000
MIN_OBJECTIVE_AUDIT_DATES = 30


def add_cross_sectional_alpha_labels(rows: pd.DataFrame) -> pd.DataFrame:
    """Add alpha ordering and separate risk outcomes without mutating input rows."""
    required = {
        "trade_date",
        "symbol",
        "industry_l1",
        "eligible_for_training",
        "net_return_after_cost_10d",
        "mae_10d",
        "sl_before_tp_10d",
        "future_limit_down_count_10d",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("ranking label rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype(str).str.split(".", regex=False).str[0].str.zfill(6)
    for column in (
        "market_median_net_return_10d",
        "industry_median_net_return_10d",
        "market_excess_10d",
        "industry_excess_10d",
        "alpha_target_10d",
        "alpha_percentile_10d",
    ):
        result[column] = np.nan
    result["industry_fallback_to_market_10d"] = pd.array([pd.NA] * len(result), dtype="boolean")
    result["alpha_top10_10d"] = False
    result["positive_net_return_10d"] = pd.array([pd.NA] * len(result), dtype="boolean")
    result["severe_negative_10d"] = pd.array([pd.NA] * len(result), dtype="boolean")
    result["alpha_relevance_grade_10d"] = pd.array([pd.NA] * len(result), dtype="Int64")

    eligible = (
        result["eligible_for_training"].eq(True)
        & pd.to_numeric(result["net_return_after_cost_10d"], errors="coerce").notna()
    )
    for _, date_index in result.loc[eligible].groupby("trade_date", sort=True).groups.items():
        _label_one_date(result, pd.Index(date_index))
    return result


def audit_label_objective(rows: pd.DataFrame) -> dict[str, Any]:
    """Check that the primary prevalence is stable and decoupled from market direction."""
    required = {
        "trade_date",
        "eligible_for_training",
        "alpha_top10_10d",
        "positive_net_return_10d",
        "market_median_net_return_10d",
        "alpha_relevance_grade_10d",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("objective audit rows missing columns: " + ", ".join(missing))
    daily: list[dict[str, Any]] = []
    failed: list[str] = []
    for trade_date, group in rows.groupby("trade_date", sort=True):
        eligible = group[group["eligible_for_training"].eq(True) & group["alpha_relevance_grade_10d"].notna()]
        if eligible.empty:
            continue
        count = len(eligible)
        top10_rate = float(eligible["alpha_top10_10d"].eq(True).mean())
        positive_rate = float(eligible["positive_net_return_10d"].eq(True).mean())
        grades = pd.to_numeric(eligible["alpha_relevance_grade_10d"], errors="coerce")
        market_values = pd.to_numeric(eligible["market_median_net_return_10d"], errors="coerce").dropna()
        daily.append(
            {
                "trade_date": str(trade_date),
                "eligible_count": int(count),
                "alpha_top10_prevalence": top10_rate,
                "positive_net_return_rate": positive_rate,
                "market_median_net_return_10d": float(market_values.iloc[0]) if not market_values.empty else None,
                "grade_4_rate": float(grades.eq(4).mean()),
                "grade_3_or_higher_rate": float(grades.ge(3).mean()),
            }
        )
        if count < MIN_OBJECTIVE_AUDIT_ELIGIBLE:
            failed.append(f"eligible_cross_section_below_1000:{trade_date}")
        else:
            if not 0.08 <= top10_rate <= 0.105:
                failed.append(f"alpha_top10_prevalence_outside_8_to_10_5pct:{trade_date}")
            if float(grades.eq(4).mean()) > 0.05:
                failed.append(f"grade_4_rate_exceeds_5pct:{trade_date}")
            if float(grades.ge(3).mean()) > 0.10:
                failed.append(f"grade_3_or_higher_rate_exceeds_10pct:{trade_date}")

    audited = pd.DataFrame(daily)
    if len(audited) < MIN_OBJECTIVE_AUDIT_DATES:
        failed.append(f"audited_date_count_below_{MIN_OBJECTIVE_AUDIT_DATES}")
    prevalence_std = float(audited["alpha_top10_prevalence"].std(ddof=0)) if not audited.empty else None
    correlation: float | None = None
    if len(audited) >= 2 and prevalence_std is not None and prevalence_std > 1e-12:
        correlation = float(
            audited["alpha_top10_prevalence"].corr(audited["market_median_net_return_10d"])
        )
    if prevalence_std is None or prevalence_std > 0.01:
        failed.append("alpha_top10_prevalence_std_exceeds_0_01")
    if correlation is not None and np.isfinite(correlation) and abs(correlation) >= 0.20:
        failed.append("alpha_top10_prevalence_correlates_with_market_return")
    return {
        "passed": not failed,
        "failed_gates": sorted(set(failed)),
        "audited_date_count": int(len(audited)),
        "eligible_row_count": int(audited["eligible_count"].sum()) if not audited.empty else 0,
        "alpha_top10_prevalence_std": prevalence_std,
        "alpha_top10_market_return_correlation": correlation,
        "daily": daily,
    }


def _label_one_date(result: pd.DataFrame, index: pd.Index) -> None:
    cross_section = result.loc[index].copy()
    returns = pd.to_numeric(cross_section["net_return_after_cost_10d"], errors="coerce")
    market_median = float(returns.median())
    industry = cross_section["industry_l1"].fillna("").astype(str)
    peer_counts = industry.groupby(industry).transform("size")
    industry_medians = returns.groupby(industry).transform("median")
    use_industry = industry.ne("") & peer_counts.ge(MIN_INDUSTRY_PEERS)
    reference = industry_medians.where(use_industry, market_median)
    market_excess = returns - market_median
    industry_excess = returns - reference
    alpha = 0.5 * market_excess + 0.5 * industry_excess

    ordered = pd.DataFrame(
        {"index": index, "alpha": alpha.to_numpy(), "symbol": cross_section["symbol"].to_numpy()}
    ).sort_values(["alpha", "symbol"], kind="stable")
    denominator = max(len(ordered) - 1, 1)
    ordered["percentile"] = np.arange(len(ordered), dtype=float) / denominator
    if len(ordered) == 1:
        ordered["percentile"] = 1.0
    percentiles = ordered.set_index("index")["percentile"].reindex(index)
    grades = pd.Series(0, index=index, dtype="int64")
    ordered_indexes = ordered["index"].tolist()
    band_counts = {
        1: int(np.floor(len(ordered) * 0.50)),
        2: int(np.floor(len(ordered) * 0.20)),
        3: int(np.floor(len(ordered) * 0.10)),
        4: int(np.floor(len(ordered) * 0.05)),
    }
    for grade, count in band_counts.items():
        if count:
            grades.loc[ordered_indexes[-count:]] = grade
    top10 = pd.Series(False, index=index)
    if band_counts[3]:
        top10.loc[ordered_indexes[-band_counts[3]:]] = True
    severe = (
        returns.le(-0.05)
        | pd.to_numeric(cross_section["mae_10d"], errors="coerce").le(-0.08)
        | cross_section["sl_before_tp_10d"].eq(True)
        | pd.to_numeric(cross_section["future_limit_down_count_10d"], errors="coerce").gt(0)
    )

    result.loc[index, "market_median_net_return_10d"] = market_median
    result.loc[index, "industry_median_net_return_10d"] = reference.to_numpy()
    result.loc[index, "market_excess_10d"] = market_excess.to_numpy()
    result.loc[index, "industry_excess_10d"] = industry_excess.to_numpy()
    result.loc[index, "alpha_target_10d"] = alpha.to_numpy()
    result.loc[index, "alpha_percentile_10d"] = percentiles.to_numpy()
    result.loc[index, "industry_fallback_to_market_10d"] = pd.array((~use_industry).to_numpy(), dtype="boolean")
    result.loc[index, "alpha_top10_10d"] = top10.to_numpy()
    result.loc[index, "positive_net_return_10d"] = pd.array(returns.gt(0).to_numpy(), dtype="boolean")
    result.loc[index, "severe_negative_10d"] = pd.array(severe.to_numpy(), dtype="boolean")
    result.loc[index, "alpha_relevance_grade_10d"] = pd.array(grades.to_numpy(), dtype="Int64")
