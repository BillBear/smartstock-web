"""Development-only ranking policy selection for the three-head decision model."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DecisionPolicySpec:
    score_mode: Literal["success", "return", "combined"]
    risk_quantile_gate: float = 0.70
    confidence_threshold: float | None = None

    def __post_init__(self) -> None:
        if self.score_mode not in {"success", "return", "combined"}:
            raise ValueError("score_mode must be success, return, or combined")
        if not 0.0 < float(self.risk_quantile_gate) <= 1.0:
            raise ValueError("risk_quantile_gate must be in (0, 1]")
        if self.confidence_threshold is not None and not math.isfinite(float(self.confidence_threshold)):
            raise ValueError("confidence_threshold must be finite or None")


def apply_decision_policy(predictions: pd.DataFrame, spec: DecisionPolicySpec) -> pd.DataFrame:
    """Apply one pre-registered score and reject the highest predicted-risk rows."""
    required = {
        "trade_date",
        "symbol",
        "success_probability",
        "severe_probability",
        "return_prediction",
    }
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError("decision predictions missing columns: " + ", ".join(missing))
    result = predictions.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in ("success_probability", "severe_probability", "return_prediction"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if spec.score_mode == "success":
        result["policy_score"] = result["success_probability"]
    elif spec.score_mode == "return":
        result["policy_score"] = result["return_prediction"]
    else:
        return_rank = result.groupby("trade_date", sort=False)["return_prediction"].rank(pct=True)
        success_rank = result.groupby("trade_date", sort=False)["success_probability"].rank(pct=True)
        severe_rank = result.groupby("trade_date", sort=False)["severe_probability"].rank(pct=True)
        result["policy_score"] = 0.5 * return_rank + 0.5 * success_rank - severe_rank
    risk_order = result.sort_values(
        ["trade_date", "severe_probability", "symbol"],
        ascending=[True, True, True],
        kind="stable",
    )
    risk_position = risk_order.groupby("trade_date", sort=False).cumcount() + 1
    keep_count = risk_order.groupby("trade_date", sort=False)["symbol"].transform(
        lambda values: int(math.ceil(len(values) * spec.risk_quantile_gate))
    )
    eligible = risk_position.le(keep_count)
    result["risk_eligible"] = eligible.reindex(result.index, fill_value=False) & result["policy_score"].notna()
    if spec.confidence_threshold is None:
        result["confidence_eligible"] = True
    else:
        result["confidence_eligible"] = result["policy_score"].ge(float(spec.confidence_threshold))
    result["policy_eligible"] = result["risk_eligible"] & result["confidence_eligible"]
    result["policy_mode"] = spec.score_mode
    return result


def select_inner_policy(
    inner_predictions: pd.DataFrame,
    policy_specs: tuple[DecisionPolicySpec, ...],
) -> tuple[DecisionPolicySpec, dict[str, float], list[dict[str, float | str | bool]]]:
    """Choose a policy only from inner OOF rows using the fixed lexicographic rule."""
    if not policy_specs:
        raise ValueError("policy_specs must not be empty")
    baseline = _topk_metrics(inner_predictions, score_col="amount_log", eligible_col=None)
    reports = []
    for spec in policy_specs:
        applied = apply_decision_policy(inner_predictions, spec)
        metrics = _topk_metrics(applied, score_col="policy_score", eligible_col="policy_eligible")
        risk_ok = metrics["severe_rate"] <= baseline["severe_rate"]
        median_ok = metrics["top5_median_return"] > 0.0
        reports.append(
            {
                "score_mode": spec.score_mode,
                **metrics,
                "baseline_severe_rate": baseline["severe_rate"],
                "risk_ok": risk_ok,
                "median_ok": median_ok,
            }
        )
    best_index = max(
        range(len(reports)),
        key=lambda index: (
            bool(reports[index]["risk_ok"]),
            bool(reports[index]["median_ok"]),
            float(reports[index]["ndcg_at_10"]),
            float(reports[index]["precision_at_5"]),
            -index,
        ),
    )
    return policy_specs[best_index], dict(reports[best_index]), reports


def evaluate_policy_metrics(
    rows: pd.DataFrame,
    *,
    score_col: str,
    eligible_col: str | None = None,
) -> dict[str, float]:
    """Expose the fixed daily Top-5 metrics for model and gate reporting."""
    return _topk_metrics(rows, score_col=score_col, eligible_col=eligible_col)


def derive_confidence_threshold(
    prior_oof: pd.DataFrame,
    *,
    score_col: str = "policy_score",
) -> float | None:
    """Freeze a selective threshold only from earlier OOF evidence."""
    required = {
        "trade_date",
        score_col,
        "label_actionable_positive_10d",
        "label_severe_negative_10d_v2",
    }
    if not required.issubset(prior_oof.columns) or prior_oof.empty:
        return None
    scores = pd.to_numeric(prior_oof[score_col], errors="coerce").dropna()
    if scores.empty:
        return None
    candidates = sorted({float(scores.quantile(value)) for value in (0.50, 0.60, 0.70, 0.80, 0.90)})
    qualifying = []
    total_dates = max(1, prior_oof["trade_date"].nunique())
    for threshold in candidates:
        selected = _daily_topk(prior_oof.loc[pd.to_numeric(prior_oof[score_col], errors="coerce").ge(threshold)], score_col)
        if selected.empty:
            continue
        precision = float(selected["label_actionable_positive_10d"].eq(True).mean())
        severe_rate = float(selected["label_severe_negative_10d_v2"].eq(True).mean())
        coverage = float(selected["trade_date"].nunique() / total_dates)
        lower = _wilson_lower_bound(int(selected["label_actionable_positive_10d"].eq(True).sum()), len(selected))
        if precision >= 0.60 and lower >= 0.50 and severe_rate <= 0.15 and coverage >= 0.15:
            qualifying.append((threshold, precision, lower, coverage))
    if not qualifying:
        return None
    return max(qualifying, key=lambda row: (row[2], row[1], row[3], row[0]))[0]


def _topk_metrics(rows: pd.DataFrame, *, score_col: str, eligible_col: str | None) -> dict[str, float]:
    selected_rows = rows if eligible_col is None else rows.loc[rows[eligible_col].eq(True)]
    selected = _daily_topk(selected_rows, score_col)
    if selected.empty:
        return {
            "precision_at_5": 0.0,
            "ndcg_at_10": 0.0,
            "top5_mean_return": 0.0,
            "top5_median_return": 0.0,
            "severe_rate": 1.0,
        }
    ndcgs = []
    for trade_date, current in rows.groupby("trade_date", sort=True):
        eligible = selected_rows.loc[selected_rows["trade_date"].eq(trade_date)].sort_values(
            [score_col, "symbol"], ascending=[False, True], kind="stable"
        )
        if eligible.empty:
            continue
        grades = pd.to_numeric(eligible["return_relevance_grade_10d_v2"], errors="coerce").fillna(0).to_numpy()[:10]
        ideal = np.sort(
            pd.to_numeric(current["return_relevance_grade_10d_v2"], errors="coerce").fillna(0).to_numpy()
        )[::-1][: len(grades)]
        discounts = np.log2(np.arange(len(grades)) + 2.0)
        dcg = float(np.sum((2**grades - 1) / discounts))
        idcg = float(np.sum((2**ideal - 1) / discounts))
        ndcgs.append(dcg / idcg if idcg else 0.0)
    selected_returns = pd.to_numeric(selected["target_clipped_return_10d"], errors="coerce")
    return {
        "precision_at_5": float(selected["label_actionable_positive_10d"].eq(True).mean()),
        "ndcg_at_10": float(np.mean(ndcgs)) if ndcgs else 0.0,
        "top5_mean_return": float(selected_returns.mean()),
        "top5_median_return": float(selected_returns.median()),
        "severe_rate": float(selected["label_severe_negative_10d_v2"].eq(True).mean()),
    }


def _daily_topk(rows: pd.DataFrame, score_col: str, top_k: int = 5) -> pd.DataFrame:
    selected = []
    for _, current in rows.groupby("trade_date", sort=True):
        ranked = current.dropna(subset=[score_col]).sort_values(
            [score_col, "symbol"], ascending=[False, True], kind="stable"
        )
        if not ranked.empty:
            selected.append(ranked.head(top_k))
    return pd.concat(selected, ignore_index=True) if selected else rows.iloc[0:0].copy()


def _wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = proportion + z * z / (2.0 * total)
    margin = z * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
    return float((centre - margin) / denominator)
