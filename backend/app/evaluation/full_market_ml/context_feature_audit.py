"""Development-only evidence for point-in-time market and industry context features."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .feature_audit import FeatureAuditResult, audit_features
from .market_industry_features import (
    INDUSTRY_FEATURE_NAMES,
    MARKET_FEATURE_NAMES,
    build_industry_state_features,
    build_market_state_features,
)
from .splits import FinalHoldoutAccessError, SplitPlan


CONTEXT_FEATURE_NAMES = (*MARKET_FEATURE_NAMES, *INDUSTRY_FEATURE_NAMES)
CONTEXT_SOURCE_COLUMNS = (
    "trade_date",
    "symbol",
    "valid_ohlc",
    "industry_l1",
    "adjusted_return_1d",
    "adjusted_return_5d",
    "adjusted_return_20d",
    "price_to_sma_20d",
    "amount_ratio_5d",
    "turnover_rate",
    "total_mv",
    "at_up_limit",
    "at_down_limit",
)
CONTEXT_OUTCOME_COLUMNS = (
    "trade_date",
    "symbol",
    "future_return_10d",
    "net_return_after_cost_10d",
    "label_severe_negative_10d",
    "eligible_for_training_10d",
)


class ContextFeatureAuditError(ValueError):
    """Raised when the point-in-time context evidence input is incomplete or unsafe."""


@dataclass(frozen=True)
class ContextFeatureAuditResult:
    """Row-aligned context values plus development-only univariate evidence."""

    context_features: pd.DataFrame
    audit: FeatureAuditResult


def build_context_feature_audit(rows: pd.DataFrame, split_plan: SplitPlan) -> ContextFeatureAuditResult:
    """Build audited context columns without allowing outcomes into their construction."""
    dataset = _normalize_development_rows(rows, split_plan)
    source = dataset.loc[:, CONTEXT_SOURCE_COLUMNS].copy()
    context = build_market_state_features(source)
    context = build_industry_state_features(context)
    context_features = context.loc[:, ["trade_date", "symbol", *CONTEXT_FEATURE_NAMES]].copy()
    context_features = context_features.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)

    outcomes = dataset.loc[:, CONTEXT_OUTCOME_COLUMNS].copy()
    audit_rows = outcomes.merge(
        context_features,
        on=["trade_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    audit_rows["eligible_for_training"] = audit_rows["eligible_for_training_10d"].eq(True)
    evidence = audit_features(audit_rows, split_plan, feature_schema=CONTEXT_FEATURE_NAMES)
    return ContextFeatureAuditResult(context_features=context_features, audit=evidence)


def _normalize_development_rows(rows: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    required = set(CONTEXT_SOURCE_COLUMNS) | set(CONTEXT_OUTCOME_COLUMNS)
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ContextFeatureAuditError("context feature audit missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if result["trade_date"].isna().any() or result["symbol"].eq("").any():
        raise ContextFeatureAuditError("context feature audit has an invalid trade_date or symbol")
    if result["trade_date"].isin(split_plan.final_dates).any() or (~result["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("context feature audit accepts only SplitPlan development dates")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise ContextFeatureAuditError("context feature audit has duplicate trade_date and symbol rows")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)
