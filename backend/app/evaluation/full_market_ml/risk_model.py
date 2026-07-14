"""Independent severe-downside model and fixed cross-ranker risk gate."""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from .baseline_model import _date_rank_matrix
from .features import assert_leak_free_schema
from .splits import SplitPlan


def run_risk_oof(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    feature_schema: Sequence[str],
) -> dict[str, Any]:
    schema = tuple(str(name) for name in feature_schema)
    if not schema:
        raise ValueError("risk feature schema cannot be empty")
    assert_leak_free_schema(schema)
    required = {"trade_date", "symbol", "severe_negative_10d", *schema}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("risk rows missing columns: " + ", ".join(missing))
    data = rows.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if (~data["trade_date"].isin(split_plan.development_dates)).any():
        raise PermissionError("risk OOF accepts development dates only")
    predictions = []
    c_symbols = set(split_plan.C_dev_unseen_symbols)
    for fold in split_plan.walk_forward:
        train = data.loc[
            data["trade_date"].isin(fold.training_dates)
            & data["symbol"].isin(fold.training_symbols)
        ].copy()
        validation_symbols = set(fold.training_symbols) | c_symbols
        validation = data.loc[
            data["trade_date"].isin(fold.validation_dates)
            & data["symbol"].isin(validation_symbols)
        ].copy()
        train_x = _date_rank_matrix(train, schema)
        valid_x = _date_rank_matrix(validation, schema)
        medians = train_x.median(axis=0).fillna(0.5)
        train_x = train_x.fillna(medians).astype("float32")
        valid_x = valid_x.fillna(medians).astype("float32")
        target = train["severe_negative_10d"].astype(bool).astype("int8")
        if target.nunique() < 2:
            raise ValueError(f"outer fold {fold.fold} risk training target has one class")
        date_counts = train.groupby("trade_date")["symbol"].transform("size")
        weights = (1.0 / date_counts).to_numpy(dtype="float64", copy=True)
        weights *= len(weights) / weights.sum()
        model = LogisticRegression(
            C=1.0,
            class_weight="balanced",
            max_iter=500,
            solver="lbfgs",
            random_state=17,
        )
        model.fit(train_x, target, sample_weight=weights)
        predicted = validation.copy()
        predicted["risk_probability"] = model.predict_proba(valid_x)[:, 1].astype("float32")
        predicted["fold"] = fold.fold
        predicted["quadrant"] = np.where(predicted["symbol"].isin(c_symbols), "C", "A")
        predictions.append(predicted)
    output = pd.concat(predictions, ignore_index=True)
    gated = apply_fixed_risk_gate(output, risk_score_col="risk_probability", keep_fraction=0.8)
    metrics = {
        str(quadrant): _risk_metrics(quadrant_rows)
        for quadrant, quadrant_rows in gated.groupby("quadrant", sort=True)
    }
    gate_passed = all(
        result["auc"] >= 0.65 and result["decile_monotonic"]
        for quadrant, result in metrics.items()
        if quadrant in {"A", "C"}
    ) and {"A", "C"}.issubset(metrics)
    probability_calibrated = {"A", "C"}.issubset(metrics) and all(
        metrics[quadrant]["ece"] <= 0.05 for quadrant in ("A", "C")
    )
    return {
        "predictions": gated,
        "metrics": metrics,
        "keep_fraction": 0.8,
        "gate_passed": bool(gate_passed),
        "probability_calibrated": bool(probability_calibrated),
    }


def apply_fixed_risk_gate(
    rows: pd.DataFrame,
    *,
    risk_score_col: str = "risk_probability",
    keep_fraction: float = 0.8,
) -> pd.DataFrame:
    if not 0 < float(keep_fraction) <= 1:
        raise ValueError("keep_fraction must be in (0, 1]")
    required = {"trade_date", "symbol", risk_score_col}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("risk gate rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    ordered = result.sort_values(
        ["trade_date", risk_score_col, "symbol"],
        ascending=[True, True, True],
        kind="stable",
    )
    position = ordered.groupby("trade_date", sort=False).cumcount() + 1
    keep = ordered.groupby("trade_date", sort=False)["symbol"].transform(
        lambda values: int(math.ceil(len(values) * keep_fraction))
    )
    eligible = position.le(keep)
    result["risk_eligible"] = eligible.reindex(result.index, fill_value=False)
    result["risk_gate_keep_fraction"] = float(keep_fraction)
    return result


def _risk_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    target = rows["severe_negative_10d"].astype(bool).astype(int)
    probability = pd.to_numeric(rows["risk_probability"], errors="coerce").clip(0, 1)
    valid = probability.notna()
    target, probability = target.loc[valid], probability.loc[valid]
    auc = float(roc_auc_score(target, probability)) if target.nunique() == 2 else 0.5
    average_precision = float(average_precision_score(target, probability)) if target.nunique() == 2 else float(target.mean())
    deciles = _risk_deciles(target, probability)
    rates = [item["severe_rate"] for item in deciles]
    monotonic_correlation = float(pd.Series(range(len(rates))).corr(pd.Series(rates), method="spearman")) if len(set(rates)) > 1 else 0.0
    monotonic = all(right + 0.01 >= left for left, right in zip(rates, rates[1:]))
    eligible = rows.loc[rows["risk_eligible"].eq(True)]
    mae_before = pd.to_numeric(rows.get("mae_10d"), errors="coerce").mean() if "mae_10d" in rows else np.nan
    mae_after = pd.to_numeric(eligible.get("mae_10d"), errors="coerce").mean() if "mae_10d" in eligible else np.nan
    return {
        "row_count": int(len(rows)),
        "positive_count": int(target.sum()),
        "auc": auc,
        "average_precision": average_precision,
        "brier": float(brier_score_loss(target, probability)),
        "ece": _ece(target, probability),
        "decile_monotonic_correlation": monotonic_correlation,
        "decile_monotonic": bool(monotonic),
        "deciles": deciles,
        "raw_severe_rate": float(rows["severe_negative_10d"].astype(bool).mean()),
        "gated_severe_rate": float(eligible["severe_negative_10d"].astype(bool).mean()),
        "raw_mae": float(mae_before) if pd.notna(mae_before) else None,
        "gated_mae": float(mae_after) if pd.notna(mae_after) else None,
    }


def _risk_deciles(target: pd.Series, probability: pd.Series) -> list[dict[str, float | int]]:
    ordered = pd.DataFrame({"target": target, "probability": probability}).sort_values("probability", kind="stable")
    chunks = np.array_split(np.arange(len(ordered)), min(10, len(ordered)))
    return [
        {
            "decile": index + 1,
            "count": int(len(chunk)),
            "mean_probability": float(ordered.iloc[chunk]["probability"].mean()),
            "severe_rate": float(ordered.iloc[chunk]["target"].mean()),
        }
        for index, chunk in enumerate(chunks)
        if len(chunk)
    ]


def _ece(target: pd.Series, probability: pd.Series) -> float:
    deciles = _risk_deciles(target, probability)
    total = max(1, sum(item["count"] for item in deciles))
    return float(sum(abs(item["mean_probability"] - item["severe_rate"]) * item["count"] / total for item in deciles))
