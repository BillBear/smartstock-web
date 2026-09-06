"""Pure, offline diagnostics for quote field completeness and numeric validity."""

import math


def classify_value(value):
    """Classify a provider value without replacing unavailable data."""
    if value is None:
        return "missing"
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return "missing"
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        return "invalid"

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "invalid"
    if not math.isfinite(number):
        return "invalid"
    return "zero" if number == 0 else "valid"


def summarize_fields(rows, fields):
    """Summarize exclusive missing/invalid/zero/valid states per field."""
    if not isinstance(rows, (list, tuple)) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("rows must be a list or tuple of dictionaries")
    if not isinstance(fields, (list, tuple)):
        raise ValueError("fields must be a list or tuple of field names")
    if any(not isinstance(name, str) or not name.strip() for name in fields):
        raise ValueError("field names must be nonblank strings")
    if len(set(fields)) != len(fields):
        raise ValueError("field names must be unique")

    row_count = len(rows)
    result = {}
    for name in fields:
        stats = {f"{kind}_count": 0 for kind in ("missing", "invalid", "zero", "valid")}
        for row in rows:
            stats[f"{classify_value(row.get(name))}_count"] += 1
        stats["missing_rate"] = stats["missing_count"] / row_count if row_count else 0.0
        stats["invalid_rate"] = stats["invalid_count"] / row_count if row_count else 0.0
        result[name] = stats
    return {"row_count": row_count, "fields": result}
