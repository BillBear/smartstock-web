"""Explicit source-quality contracts for externally sourced market data."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional


MoneyFlowQuality = Literal["observed", "estimated", "proxy", "missing"]


def make_money_flow_provenance(
    source: str,
    quality: MoneyFlowQuality,
    *,
    as_of_date: Optional[str] = None,
    fallback_reason: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Build the serializable provenance fields carried with money-flow values."""
    return {
        "data_source": str(source or "unknown").strip().lower() or "unknown",
        "data_quality": quality,
        "as_of_date": as_of_date,
        "fallback_reason": fallback_reason,
    }


def is_observed_money_flow(data: Optional[Dict[str, Any]]) -> bool:
    """Only measured provider output may be used where observed flow is required."""
    return bool(data) and data.get("data_quality") == "observed"
