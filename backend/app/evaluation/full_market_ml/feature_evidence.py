"""Fold-local, point-in-time evidence for cross-sectional ranking features."""
from __future__ import annotations

import json
import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from .features import assert_leak_free_schema
from .splits import FinalHoldoutAccessError, SplitPlan


REQUIRED_COLUMNS = {
    "trade_date",
    "symbol",
    "alpha_target_10d",
    "net_return_after_cost_10d",
    "severe_negative_10d",
}
PSI_BINS = np.linspace(0.0, 1.0, 11)


def evaluate_feature_evidence(
    rows: pd.DataFrame,
    feature_names: Sequence[str],
    split_plan: SplitPlan,
) -> pd.DataFrame:
    """Evaluate registered features on outer validation dates only.

    The returned table contains one row per feature/fold plus one summary row.
    Descriptive evidence can reject a feature, but cannot admit it to a model;
    actual nested-OOF block admission is a separate downstream gate.
    """
    features = tuple(dict.fromkeys(str(name) for name in feature_names))
    if not features:
        raise ValueError("feature_names cannot be empty")
    assert_leak_free_schema(features)
    data = _normalise_rows(rows, features, split_plan)
    _enforce_signal_timestamps(data, features)

    output: list[dict[str, object]] = []
    fold_rank_values: dict[str, np.ndarray] = {}
    for fold in split_plan.walk_forward:
        validation = data.loc[
            data["trade_date"].isin(fold.validation_dates)
            & data["symbol"].isin(fold.training_symbols)
        ].copy()
        if validation.empty:
            raise ValueError(f"outer fold {fold.fold} has no validation rows")
        for feature in features:
            evidence, rank_values = _fold_evidence(validation, feature, fold.fold)
            prior = fold_rank_values.get(feature)
            evidence["psi"] = _psi(prior, rank_values)
            fold_rank_values[feature] = rank_values
            output.append(evidence)

    folds = pd.DataFrame(output)
    summaries = [_summarise_feature(data, folds.loc[folds["feature"].eq(feature)], feature) for feature in features]
    return pd.concat([folds, pd.DataFrame(summaries)], ignore_index=True, sort=False)


def _normalise_rows(rows: pd.DataFrame, features: tuple[str, ...], split_plan: SplitPlan) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    missing = sorted((REQUIRED_COLUMNS | set(features)) - set(rows.columns))
    if missing:
        raise ValueError("feature evidence rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if result["trade_date"].isin(split_plan.final_dates).any():
        raise FinalHoldoutAccessError("feature evidence cannot read sealed final holdout dates")
    outside = ~result["trade_date"].isin(split_plan.development_dates)
    if outside.any():
        raise ValueError("feature evidence accepts only registered development dates")
    if "eligible_for_training" in result:
        result = result.loc[result["eligible_for_training"].eq(True)].copy()
    for column in (*features, "alpha_target_10d", "net_return_after_cost_10d"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["severe_negative_10d"] = result["severe_negative_10d"].astype("boolean")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _enforce_signal_timestamps(rows: pd.DataFrame, features: tuple[str, ...]) -> None:
    signal_dates = pd.to_datetime(rows["trade_date"], errors="coerce")
    for feature in features:
        candidates = [f"{feature}_available_at", f"{feature}_announcement_date"]
        if feature.startswith("fundamental_"):
            candidates.append("fundamental_announcement_date")
        elif feature.startswith("forecast_"):
            candidates.append("forecast_announcement_date")
        elif feature.startswith("express_"):
            candidates.append("express_announcement_date")
        for column in candidates:
            if column not in rows:
                continue
            available = pd.to_datetime(rows[column], errors="coerce")
            invalid = available.notna() & signal_dates.notna() & available.gt(signal_dates)
            if invalid.any():
                raise ValueError(f"feature {feature} is available after signal time")


def _fold_evidence(rows: pd.DataFrame, feature: str, fold: int) -> tuple[dict[str, object], np.ndarray]:
    values = pd.to_numeric(rows[feature], errors="coerce")
    valid = rows.loc[values.notna()].copy()
    valid[feature] = values.loc[values.notna()]
    rank_values = _date_sectional_rank(valid, feature).to_numpy(dtype="float64")
    daily_ic = _daily_rank_ic(valid, feature, "alpha_target_10d")
    daily_risk_ic = _daily_rank_ic(valid, feature, "severe_negative_10d")
    median_ic = _median(daily_ic)
    direction = 1.0 if not math.isfinite(median_ic) or median_ic >= 0 else -1.0
    top5 = _daily_top_k(valid, feature, direction, 5)
    block_values = _non_overlapping_block_means(daily_ic, block_size=10)
    return (
        {
            "record_type": "fold",
            "feature": feature,
            "fold": int(fold),
            "sample_count": int(len(rows)),
            "non_null_count": int(values.notna().sum()),
            "coverage": _ratio(values.notna().sum(), len(rows)),
            "missing_mechanism": _missing_mechanism(rows, values),
            "daily_rank_ic": median_ic,
            "ic_t_stat": _t_stat(block_values),
            "monotonic_decile_score": _monotonic_decile_score(valid, feature, direction),
            "top5_mean_net_return": float(top5["net_return"].mean()) if not top5.empty else np.nan,
            "top5_median_net_return": float(top5["net_return"].median()) if not top5.empty else np.nan,
            "top5_mean_alpha": float(top5["alpha"].mean()) if not top5.empty else np.nan,
            "top5_severe_rate": float(top5["severe"].mean()) if not top5.empty else np.nan,
            "risk_rank_ic": _median(daily_risk_ic),
            "market_state_evidence": _stratified_json(valid, feature, direction, "market_state"),
            "industry_evidence": _stratified_json(valid, feature, direction, "industry_l1"),
            "size_evidence": _stratified_json(valid, feature, direction, "size_bucket"),
            "liquidity_evidence": _stratified_json(valid, feature, direction, "liquidity_bucket"),
            "direction": "positive" if direction > 0 else "negative",
            "psi": np.nan,
            "role": "fold_evidence",
            "stable_sign_folds": np.nan,
            "state_sign_consistent": np.nan,
        },
        rank_values,
    )


def _summarise_feature(rows: pd.DataFrame, folds: pd.DataFrame, feature: str) -> dict[str, object]:
    ic = pd.to_numeric(folds["daily_rank_ic"], errors="coerce").dropna()
    positive = int(ic.gt(0).sum())
    negative = int(ic.lt(0).sum())
    stable_sign_folds = max(positive, negative)
    state_ics = _state_ics(rows, feature)
    nonzero_state_signs = {int(np.sign(value)) for value in state_ics.values() if math.isfinite(value) and value != 0}
    state_consistent = len(state_ics) >= 2 and len(nonzero_state_signs) <= 1
    mean_alpha = float(pd.to_numeric(folds["top5_mean_alpha"], errors="coerce").mean())
    risk_ic = pd.to_numeric(folds["risk_rank_ic"], errors="coerce").dropna()
    stable_risk_folds = max(int(risk_ic.gt(0).sum()), int(risk_ic.lt(0).sum()))
    median_risk_ic = float(risk_ic.median()) if not risk_ic.empty else np.nan
    alpha_ic = float(ic.median()) if not ic.empty else np.nan
    predominantly_risk = (
        stable_risk_folds >= 4
        and abs(median_risk_ic) >= 0.80
        and (not math.isfinite(alpha_ic) or abs(alpha_ic) < 0.20)
    )
    if predominantly_risk:
        role = "risk_only"
    elif stable_sign_folds >= 4 and mean_alpha > 0 and state_consistent:
        role = "alpha_candidate"
    elif stable_risk_folds >= 4 and abs(median_risk_ic) >= 0.20:
        role = "risk_only"
    elif len(state_ics) >= 2 and not state_consistent:
        role = "rejected_regime_dependent"
    else:
        role = "rejected_weak"
    return {
        "record_type": "summary",
        "feature": feature,
        "fold": 0,
        "sample_count": int(folds["sample_count"].sum()),
        "non_null_count": int(folds["non_null_count"].sum()),
        "coverage": float(folds["coverage"].mean()),
        "missing_mechanism": ";".join(sorted(set(folds["missing_mechanism"].astype(str)))),
        "daily_rank_ic": float(ic.median()) if not ic.empty else np.nan,
        "ic_t_stat": float(pd.to_numeric(folds["ic_t_stat"], errors="coerce").median()),
        "monotonic_decile_score": float(pd.to_numeric(folds["monotonic_decile_score"], errors="coerce").median()),
        "top5_mean_net_return": float(pd.to_numeric(folds["top5_mean_net_return"], errors="coerce").mean()),
        "top5_median_net_return": float(pd.to_numeric(folds["top5_median_net_return"], errors="coerce").median()),
        "top5_mean_alpha": mean_alpha,
        "top5_severe_rate": float(pd.to_numeric(folds["top5_severe_rate"], errors="coerce").mean()),
        "risk_rank_ic": median_risk_ic,
        "market_state_evidence": json.dumps(state_ics, ensure_ascii=True, sort_keys=True),
        "industry_evidence": "{}",
        "size_evidence": "{}",
        "liquidity_evidence": "{}",
        "direction": "positive" if positive >= negative else "negative",
        "psi": float(pd.to_numeric(folds["psi"], errors="coerce").dropna().max()) if pd.to_numeric(folds["psi"], errors="coerce").notna().any() else np.nan,
        "role": role,
        "stable_sign_folds": int(stable_sign_folds),
        "state_sign_consistent": bool(state_consistent),
    }


def _date_sectional_rank(rows: pd.DataFrame, feature: str) -> pd.Series:
    return rows.groupby("trade_date", sort=False)[feature].rank(method="first", pct=True)


def _daily_rank_ic(rows: pd.DataFrame, feature: str, target: str) -> list[float]:
    result = []
    for _, daily in rows.groupby("trade_date", sort=True):
        pair = daily[[feature, target]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(pair) < 5 or pair[feature].nunique() < 2 or pair[target].nunique() < 2:
            continue
        result.append(float(pair[feature].rank(method="average").corr(pair[target].rank(method="average"))))
    return result


def _daily_top_k(rows: pd.DataFrame, feature: str, direction: float, k: int) -> pd.DataFrame:
    records = []
    for trade_date, daily in rows.groupby("trade_date", sort=True):
        selected = daily.assign(_score=daily[feature] * direction).sort_values(
            ["_score", "symbol"], ascending=[False, True], kind="stable"
        ).head(k)
        records.extend(
            {
                "trade_date": trade_date,
                "net_return": float(row.net_return_after_cost_10d),
                "alpha": float(row.alpha_target_10d),
                "severe": float(bool(row.severe_negative_10d)),
            }
            for row in selected.itertuples()
        )
    return pd.DataFrame(records)


def _monotonic_decile_score(rows: pd.DataFrame, feature: str, direction: float) -> float:
    values = []
    for _, daily in rows.groupby("trade_date", sort=True):
        if len(daily) < 10:
            continue
        ranked = (daily[feature] * direction).rank(method="first", pct=True)
        buckets = np.minimum(9, np.floor(ranked * 10).astype(int))
        means = daily.assign(_bucket=buckets).groupby("_bucket")["alpha_target_10d"].mean()
        if len(means) >= 5:
            values.append(float(pd.Series(means.index, index=means.index).corr(means)))
    return _median(values)


def _stratified_json(rows: pd.DataFrame, feature: str, direction: float, column: str) -> str:
    if column not in rows:
        return "{}"
    result = {}
    for group, subset in rows.groupby(column, dropna=False, sort=True):
        top = _daily_top_k(subset, feature, direction, 5)
        result[str(group)] = {
            "rows": int(len(subset)),
            "top5_mean_alpha": float(top["alpha"].mean()) if not top.empty else None,
        }
    return json.dumps(result, ensure_ascii=True, sort_keys=True)


def _state_ics(rows: pd.DataFrame, feature: str) -> dict[str, float]:
    if "market_state" not in rows:
        return {}
    result = {}
    for state, subset in rows.groupby("market_state", dropna=False, sort=True):
        result[str(state)] = _median(_daily_rank_ic(subset, feature, "alpha_target_10d"))
    return result


def _missing_mechanism(rows: pd.DataFrame, values: pd.Series) -> str:
    if values.notna().all():
        return "none"
    by_date = values.notna().groupby(rows["trade_date"]).mean()
    if by_date.eq(0).any():
        return "structural_by_date"
    return "intermittent"


def _non_overlapping_block_means(values: list[float], block_size: int) -> list[float]:
    return [float(np.mean(values[index:index + block_size])) for index in range(0, len(values), block_size) if values[index:index + block_size]]


def _t_stat(values: list[float]) -> float:
    array = np.asarray(values, dtype="float64")
    if len(array) < 2 or np.isclose(array.std(ddof=1), 0):
        return np.nan
    return float(array.mean() / (array.std(ddof=1) / math.sqrt(len(array))))


def _psi(reference: np.ndarray | None, current: np.ndarray) -> float:
    if reference is None or not len(reference) or not len(current):
        return np.nan
    expected, _ = np.histogram(reference, bins=PSI_BINS)
    observed, _ = np.histogram(current, bins=PSI_BINS)
    expected = np.clip(expected / expected.sum(), 1e-6, None)
    observed = np.clip(observed / observed.sum(), 1e-6, None)
    return float(np.sum((observed - expected) * np.log(observed / expected)))


def _median(values: list[float]) -> float:
    finite = np.asarray([value for value in values if math.isfinite(value)], dtype="float64")
    return float(np.median(finite)) if len(finite) else np.nan


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0
