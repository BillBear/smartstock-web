"""Pure, offline diagnostics for quote field completeness and numeric validity."""

import math


def classify_value(value):
    """Return missing, invalid, zero or valid without replacing unavailable data."""
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
    except (ValueError, TypeError, OverflowError):
        return "invalid"
    if not math.isfinite(number):
        return "invalid"
    return "zero" if number == 0 else "valid"


def summarize_fields(rows, fields):
    """Count exclusive value classes for each requested field, preserving names.

    Rows and fields must be lists or tuples, containing dictionaries and unique
    nonblank string names respectively. Malformed inputs raise ValueError even
    when no rows or fields would otherwise need processing.
    """
    if not isinstance(rows, (list, tuple)):
        raise ValueError("rows must be a list or tuple of dictionaries")
    if not isinstance(fields, (list, tuple)):
        raise ValueError("fields must be a list or tuple of field names")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("each row must be a dictionary")

    seen = set()
    for name in fields:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("field names must be nonblank strings")
        if name in seen:
            raise ValueError("field names must be unique")
        seen.add(name)

    row_count = len(rows)
    summaries = {}
    for name in fields:
        stats = {
            "missing_count": 0,
            "invalid_count": 0,
            "zero_count": 0,
            "valid_count": 0,
        }
        for row in rows:
            classification = classify_value(row.get(name))
            stats[classification + "_count"] += 1
        stats["missing_rate"] = stats["missing_count"] / row_count if row_count else 0.0
        stats["invalid_rate"] = stats["invalid_count"] / row_count if row_count else 0.0
        summaries[name] = stats
    return {"row_count": row_count, "fields": summaries}
