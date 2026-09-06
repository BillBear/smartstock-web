import math


def classify_value(value):
    """Classify a quote field without conflating missing, invalid, and zero."""
    if value is None:
        return "missing"

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return "missing"
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        return "invalid"

    try:
        numeric_value = float(value)
    except (OverflowError, TypeError, ValueError):
        return "invalid"

    if not math.isfinite(numeric_value):
        return "invalid"
    if numeric_value == 0.0:
        return "zero"
    return "valid"


def summarize_fields(rows, fields):
    """Summarize requested quote fields across a validated sequence of rows."""
    if not isinstance(rows, (list, tuple)):
        raise ValueError("rows must be a list or tuple of dictionaries")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rows must contain only dictionaries")

    if not isinstance(fields, (list, tuple)):
        raise ValueError("fields must be a list or tuple of names")
    seen = set()
    for name in fields:
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError("fields must contain unique, nonempty string names")
        seen.add(name)

    field_stats = {}
    for name in fields:
        field_stats[name] = {
            "missing_count": 0,
            "invalid_count": 0,
            "zero_count": 0,
            "valid_count": 0,
            "missing_rate": 0.0,
            "invalid_rate": 0.0,
        }

    row_count = len(rows)
    for row in rows:
        for name in fields:
            value = row[name] if name in row else None
            category = classify_value(value)
            field_stats[name][category + "_count"] += 1

    for stats in field_stats.values():
        if row_count:
            stats["missing_rate"] = stats["missing_count"] / row_count
            stats["invalid_rate"] = stats["invalid_count"] / row_count

    return {"row_count": row_count, "fields": field_stats}
