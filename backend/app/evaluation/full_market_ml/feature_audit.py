"""Development-only feature coverage and discrimination evidence for full-market ML."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from itertools import combinations

import numpy as np
import pandas as pd

from .features import CORE_FEATURE_SPECS, OPTIONAL_FEATURE_SPECS, FeatureLeakageError, assert_leak_free_schema
from .splits import FinalHoldoutAccessError, SplitPlan


TARGET_COLUMN = "future_return_10d"
BUCKET_COUNT = 5
HIGH_CORRELATION_THRESHOLD = 0.95
MIN_GROUP_COVERAGE = 0.80
_FEATURE_GROUPS = {
    spec.name: spec.feature_group
    for spec in (*CORE_FEATURE_SPECS, *OPTIONAL_FEATURE_SPECS)
}
_FEATURE_GROUPS.update({"net_mf_amount": "moneyflow", "net_mf_vol": "moneyflow", "moneyflow": "moneyflow"})
_NON_FEATURE_COLUMNS = {"trade_date", "symbol", TARGET_COLUMN, "eligible_for_training"}
_LABEL_PREFIXES = ("future_", "label_", "relevance_", "mfe_", "mae_", "market_median_", "industry_median_")


@dataclass(frozen=True)
class FeatureAuditResult:
    """Tabular evidence suitable for direct CSV export without model training."""

    coverage: pd.DataFrame
    ic: pd.DataFrame
    bucket_returns: pd.DataFrame
    correlation: pd.DataFrame
    drift: pd.DataFrame
    group_eligibility: pd.DataFrame

    @property
    def csv_rows(self) -> dict[str, list[dict]]:
        return self.to_csv_rows()

    def to_csv_rows(self) -> dict[str, list[dict]]:
        return {
            "coverage": self.coverage.to_dict("records"),
            "ic": self.ic.to_dict("records"),
            "bucket_returns": self.bucket_returns.to_dict("records"),
            "correlation": self.correlation.to_dict("records"),
            "drift": self.drift.to_dict("records"),
            "group_eligibility": self.group_eligibility.to_dict("records"),
        }

    @classmethod
    def from_csv_rows(cls, payload: dict[str, list[dict]]) -> "FeatureAuditResult":
        """Restore an audit artifact without recomputing it or reading holdout rows."""
        if not isinstance(payload, dict):
            raise TypeError("feature audit payload must be a mapping")
        required = {"coverage", "ic", "bucket_returns", "correlation", "drift", "group_eligibility"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError("feature audit payload missing: " + ", ".join(missing))
        return cls(**{name: pd.DataFrame(payload[name]) for name in required})


def audit_features(
    development_dataset: pd.DataFrame,
    split_plan: SplitPlan,
    *,
    feature_schema: Iterable[str] | None = None,
) -> FeatureAuditResult:
    """Audit signal-day features exclusively inside the sealed plan's development period.

    Fold evidence is calculated on each expanding fold's development validation dates
    and A-quadrant symbols. Final-time rows are rejected before any feature value is read.
    """
    dataset = _normalize_development_dataset(development_dataset, split_plan)
    # Constant columns carry no cross-sectional information and otherwise create
    # millions of meaningless daily bucket rows on the full-market panel.
    feature_names = [
        feature
        for feature in _feature_names(dataset, feature_schema)
        if pd.to_numeric(dataset[feature], errors="coerce").nunique(dropna=True) > 1
    ]
    coverage_rows: list[dict] = []
    ic_rows: list[dict] = []
    bucket_rows: list[dict] = []
    correlation_rows: list[dict] = []
    drift_rows: list[dict] = []
    prior_fold_values: dict[str, pd.Series] | None = None
    return_target = "net_return_after_cost" if "net_return_after_cost" in dataset else TARGET_COLUMN
    target_columns = [return_target]
    if "label_severe_negative_10d" in dataset:
        target_columns.append("label_severe_negative_10d")

    for fold in split_plan.walk_forward:
        fold_data = dataset.loc[
            dataset["trade_date"].isin(fold.validation_dates) & dataset["symbol"].isin(fold.training_symbols)
        ].copy()
        for feature in feature_names:
            values = pd.to_numeric(fold_data[feature], errors="coerce")
            coverage_rows.append(
                {
                    "fold": fold.fold,
                    "feature": feature,
                    "feature_group": _feature_group(feature),
                    "sample_count": int(len(fold_data)),
                    "non_null_count": int(values.notna().sum()),
                    "coverage": _ratio(values.notna().sum(), len(fold_data)),
                }
            )
            for target in target_columns:
                daily_ic, daily_buckets = _daily_feature_evidence(fold_data, feature, target)
                bucket_rows.extend(
                    {"fold": fold.fold, "feature": feature, "feature_group": _feature_group(feature), "target": target, **row}
                    for row in daily_buckets
                )
                ic_rows.append(_aggregate_ic(fold.fold, feature, _feature_group(feature), target, daily_ic))

        correlation_rows.extend(_fold_correlations(fold.fold, fold_data, feature_names))
        current_values = {feature: pd.to_numeric(fold_data[feature], errors="coerce").dropna() for feature in feature_names}
        drift_rows.extend(_fold_psi(fold.fold, current_values, prior_fold_values))
        prior_fold_values = current_values

    coverage = pd.DataFrame(coverage_rows, columns=["fold", "feature", "feature_group", "sample_count", "non_null_count", "coverage"])
    correlation = pd.DataFrame(correlation_rows, columns=["fold", "feature_left", "feature_right", "correlation", "abs_correlation", "sample_count"])
    ic = _add_feature_decisions(pd.DataFrame(ic_rows), coverage, correlation)
    return FeatureAuditResult(
        coverage=coverage,
        ic=ic,
        bucket_returns=pd.DataFrame(bucket_rows, columns=["fold", "feature", "feature_group", "target", "trade_date", "bucket", "sample_count", "mean_forward_return", "top_bottom_spread"]),
        correlation=correlation,
        drift=pd.DataFrame(drift_rows, columns=["fold", "reference_fold", "feature", "feature_group", "psi", "sample_count", "reference_sample_count"]),
        group_eligibility=_group_eligibility(coverage, ic, return_target),
    )


def _normalize_development_dataset(development_dataset: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    if not isinstance(development_dataset, pd.DataFrame):
        raise TypeError("development_dataset must be a pandas DataFrame")
    required = {"trade_date", "symbol", TARGET_COLUMN}
    missing = sorted(required - set(development_dataset.columns))
    if missing:
        raise ValueError("development_dataset missing columns: " + ", ".join(missing))
    dataset = development_dataset.copy()
    dataset["trade_date"] = pd.to_datetime(dataset["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    dataset["symbol"] = dataset["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if dataset["trade_date"].isin(split_plan.final_dates).any() or (~dataset["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("feature audit accepts only SplitPlan development dates; final holdout rows remain sealed")
    if "eligible_for_training" in dataset:
        dataset = dataset.loc[dataset["eligible_for_training"].eq(True)].copy()
    if dataset.empty:
        raise ValueError("development_dataset has no eligible development rows")
    return dataset.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _feature_names(dataset: pd.DataFrame, feature_schema: Iterable[str] | None = None) -> list[str]:
    allowed = None if feature_schema is None else {str(name) for name in feature_schema}
    features = []
    for column in dataset.columns:
        name = str(column)
        if allowed is not None and name not in allowed:
            continue
        if name in _NON_FEATURE_COLUMNS or name.startswith(_LABEL_PREFIXES):
            continue
        try:
            assert_leak_free_schema([name])
        except FeatureLeakageError:
            continue
        if pd.api.types.is_numeric_dtype(dataset[column]):
            features.append(name)
    if not features:
        raise ValueError("development_dataset has no numeric feature columns")
    return sorted(features)


def _daily_feature_evidence(dataset: pd.DataFrame, feature: str, target: str) -> tuple[list[float], list[dict]]:
    daily_ic: list[float] = []
    buckets: list[dict] = []
    for trade_date, daily in dataset.groupby("trade_date", sort=True):
        valid = daily[[feature, target]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(valid) < 2 or valid[feature].nunique() < 2 or valid[target].nunique() < 2:
            continue
        ic = valid[feature].corr(valid[target], method="spearman")
        if pd.notna(ic):
            daily_ic.append(float(ic))
        ranked = valid[feature].rank(method="first", pct=True)
        bucket = np.minimum(BUCKET_COUNT, np.ceil(ranked * BUCKET_COUNT)).astype("int64")
        returns = valid.assign(_bucket=bucket).groupby("_bucket", sort=True)[target].agg(["count", "mean"])
        if returns.empty:
            continue
        spread = float(returns.loc[returns.index.max(), "mean"] - returns.loc[returns.index.min(), "mean"])
        for bucket_number, row in returns.iterrows():
            buckets.append(
                {
                    "trade_date": trade_date,
                    "bucket": int(bucket_number),
                    "sample_count": int(row["count"]),
                    "mean_forward_return": float(row["mean"]),
                    "top_bottom_spread": spread,
                }
            )
    return daily_ic, buckets


def _aggregate_ic(fold: int, feature: str, group: str, target: str, daily_ic: list[float]) -> dict:
    values = np.asarray(daily_ic, dtype=float)
    mean_ic = float(values.mean()) if len(values) else np.nan
    std_ic = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return {
        "fold": fold,
        "feature": feature,
        "feature_group": group,
        "target": target,
        "date_count": int(len(values)),
        "mean_ic": mean_ic,
        "median_ic": float(np.median(values)) if len(values) else np.nan,
        "ic_std": std_ic,
        "icir": float(mean_ic / std_ic) if std_ic > 0 else (float("inf") if mean_ic > 0 else np.nan),
        "sign_consistency": float((values > 0).mean()) if len(values) else 0.0,
    }


def _fold_correlations(fold: int, dataset: pd.DataFrame, features: list[str]) -> list[dict]:
    numeric = dataset[features].apply(pd.to_numeric, errors="coerce")
    variable_features = [feature for feature in features if numeric[feature].nunique(dropna=True) > 1]
    if len(variable_features) < 2:
        return []
    # Rank each column once, then use a vectorized Pearson correlation on the
    # ranks. Pairwise counts are retained for the audit evidence.
    ranked = numeric[variable_features].rank(method="average", na_option="keep")
    correlations = ranked.corr(method="pearson", min_periods=2)
    rows = []
    for left, right in combinations(variable_features, 2):
        correlation = correlations.loc[left, right]
        if pd.notna(correlation) and abs(correlation) >= HIGH_CORRELATION_THRESHOLD:
            sample_count = int(numeric[[left, right]].notna().all(axis=1).sum())
            rows.append({"fold": fold, "feature_left": left, "feature_right": right, "correlation": float(correlation), "abs_correlation": float(abs(correlation)), "sample_count": sample_count})
    return rows


def _fold_psi(fold: int, values: dict[str, pd.Series], reference: dict[str, pd.Series] | None) -> list[dict]:
    rows = []
    for feature, current in values.items():
        baseline = current if reference is None else reference.get(feature, pd.Series(dtype=float))
        rows.append(
            {
                "fold": fold,
                "reference_fold": fold if reference is None else fold - 1,
                "feature": feature,
                "feature_group": _feature_group(feature),
                "psi": _population_stability_index(baseline, current),
                "sample_count": int(len(current)),
                "reference_sample_count": int(len(baseline)),
            }
        )
    return rows


def _population_stability_index(reference: pd.Series, current: pd.Series) -> float:
    if reference.empty or current.empty:
        return np.nan
    edges = np.unique(np.quantile(reference.to_numpy(dtype=float), np.linspace(0, 1, 11)))
    if len(edges) < 2:
        return 0.0 if reference.nunique() == current.nunique() == 1 and reference.iloc[0] == current.iloc[0] else np.nan
    bins = np.concatenate(([-np.inf], edges[1:-1], [np.inf]))
    expected = np.histogram(reference, bins=bins)[0] / len(reference)
    actual = np.histogram(current, bins=bins)[0] / len(current)
    epsilon = 1e-6
    return float(np.sum((actual - expected) * np.log((actual + epsilon) / (expected + epsilon))))


def _add_feature_decisions(ic: pd.DataFrame, coverage: pd.DataFrame, correlation: pd.DataFrame) -> pd.DataFrame:
    result = ic.copy()
    for (feature, target), rows in result.groupby(["feature", "target"], sort=False):
        feature_coverage = coverage.loc[coverage["feature"].eq(feature), "coverage"].min()
        median_ic = rows["median_ic"].median()
        fold_ics = pd.to_numeric(rows["median_ic"], errors="coerce").dropna()
        positive_consistency = float((fold_ics > 0).mean()) if len(fold_ics) else 0.0
        negative_consistency = float((fold_ics < 0).mean()) if len(fold_ics) else 0.0
        direction = "negative" if median_ic < 0 else "positive"
        direction_consistency = max(positive_consistency, negative_consistency)
        correlated = not correlation.loc[(correlation["feature_left"].eq(feature)) | (correlation["feature_right"].eq(feature))].empty
        if pd.isna(feature_coverage) or feature_coverage < MIN_GROUP_COVERAGE or pd.isna(median_ic) or direction_consistency < 0.8:
            decision = "exclude"
        elif len(rows) >= 2 and not correlated:
            decision = "core_candidate"
        else:
            decision = "interaction_candidate"
        mask = result["feature"].eq(feature) & result["target"].eq(target)
        result.loc[mask, "selection"] = decision
        result.loc[mask, "direction"] = direction
        result.loc[mask, "direction_consistency"] = direction_consistency
    return result


def _group_eligibility(coverage: pd.DataFrame, ic: pd.DataFrame, return_target: str) -> pd.DataFrame:
    rows = []
    for (fold, group), group_coverage in coverage.groupby(["fold", "feature_group"], sort=True):
        minimum_coverage = float(group_coverage.groupby("feature")["coverage"].min().min())
        candidates = ic.loc[
            ic["fold"].eq(fold) & ic["feature_group"].eq(group) & ic["target"].eq(return_target), "selection"
        ]
        if group == "moneyflow":
            eligibility = "pending_oof_group_comparison" if minimum_coverage >= MIN_GROUP_COVERAGE else "exclude"
            requirement = "requires_coverage_at_least_0.80_and_task_12_oof_ndcg10_and_precision5_improvement"
        elif minimum_coverage < MIN_GROUP_COVERAGE:
            eligibility, requirement = "exclude", "coverage_below_0.80"
        elif candidates.eq("core_candidate").any():
            eligibility, requirement = "eligible_for_candidate_model", "development_fold_evidence_only"
        else:
            eligibility, requirement = "interaction_only", "no_core_candidate_without_stable_fold_evidence"
        rows.append({"fold": fold, "feature_group": group, "target": return_target, "coverage": minimum_coverage, "eligibility": eligibility, "requirement": requirement})
    return pd.DataFrame(rows, columns=["fold", "feature_group", "target", "coverage", "eligibility", "requirement"])


def _audit_allowed_features(features: Iterable[str], audit: FeatureAuditResult | None) -> tuple[str, ...]:
    """Apply the sealed feature-audit decisions to a candidate model schema."""
    requested = tuple(str(feature) for feature in features)
    if audit is None:
        return requested
    if audit.ic.empty:
        return ()
    target = "net_return_after_cost" if "net_return_after_cost" in set(audit.ic.get("target", ())) else TARGET_COLUMN
    eligible = set(
        audit.ic.loc[
            audit.ic["target"].eq(target) & audit.ic["selection"].isin({"core_candidate", "interaction_candidate"}),
            "feature",
        ]
    )
    return tuple(feature for feature in requested if feature in eligible)


def _feature_group(feature: str) -> str:
    return _FEATURE_GROUPS.get(feature, "unclassified")


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0
