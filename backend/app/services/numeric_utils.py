"""Shared numeric guards for coach services."""
from __future__ import annotations

import math
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return float(default)
        result = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(result):
        return float(default)
    return result


def clamp(value: Any, low: float, high: float) -> float:
    try:
        result = float(value)
    except Exception:
        return low
    if not math.isfinite(result):
        return low
    return max(low, min(high, result))
