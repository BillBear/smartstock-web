"""Shared money-flow scoring policy.

Keep this module small and deterministic so ranking, market-leader scoring, and
legacy CoachService paths do not silently diverge on the same money-flow input.
"""
from __future__ import annotations

from typing import Any

from app.services.numeric_utils import clamp, safe_float


class MoneyFlowPolicy:
    REAL_FLOW_MULTIPLIER = 8.0
    PROXY_FLOW_MULTIPLIER = 3.0

    @classmethod
    def multiplier_for_quality(cls, quality: Any) -> float:
        normalized = str(quality or "").strip().lower()
        if normalized == "real":
            return cls.REAL_FLOW_MULTIPLIER
        if normalized == "proxy":
            return cls.PROXY_FLOW_MULTIPLIER
        return 0.0

    @classmethod
    def score_from_inflow_yi(cls, inflow_yi: float, quality: Any) -> float:
        multiplier = cls.multiplier_for_quality(quality)
        normalized_inflow = safe_float(inflow_yi, 0.0)
        return clamp(50.0 + normalized_inflow * multiplier, 0.0, 100.0)
