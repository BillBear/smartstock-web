"""Pure comparison of raw, adapted and normalized quote-field contracts.

This module is deliberately transport-free. It records data loss and unit
conversion in captured records; it never supplies missing values or adjusts
production quote behavior.
"""

import math
import re
import hashlib
import json
from pathlib import Path

from app.evaluation.quote_field_diagnostics import classify_value
from app.evaluation.swing_dataset import compact_trade_date


_STATUSES = {
    "retained",
    "unit_converted",
    "field_dropped",
    "missing_coerced_to_zero",
    "invalid",
    "unmatched_identity",
    "not_comparable",
}


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("trade_date must be a string or null")
    return compact_trade_date(value)


def _records(records, name):
    if not isinstance(records, list):
        raise ValueError(f"{name} records must be a list")
    indexed = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValueError(f"{name} record must be an object")
        symbol = item.get("symbol")
        values = item.get("values")
        if not isinstance(symbol, str) or not re.fullmatch(r"[0-9]{6}(?:\.(?:SH|SZ|BJ))?", symbol):
            raise ValueError(f"{name} record has invalid symbol")
        if not isinstance(values, dict):
            raise ValueError(f"{name} record values must be an object")
        key = (symbol, _date(item.get("trade_date")))
        if key in indexed:
            raise ValueError(f"duplicate {name} symbol/date key: {key}")
        indexed[key] = values
    return indexed


def _field_map(field_map):
    if not isinstance(field_map, dict) or not field_map:
        raise ValueError("field_map must be a nonempty object")
    normalized = {}
    for name, config in field_map.items():
        if not isinstance(name, str) or not name or not isinstance(config, dict):
            raise ValueError("field_map entries must be named objects")
        for key in ("raw", "adapted", "normalized", "source", "unit", "multiplier"):
            if key not in config:
                raise ValueError(f"field_map {name} lacks {key}")
        if any(not isinstance(config[key], str) or not config[key] for key in ("raw", "adapted", "normalized", "source", "unit")):
            raise ValueError(f"field_map {name} has invalid field names")
        multiplier = config["multiplier"]
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not math.isfinite(float(multiplier)) or multiplier <= 0:
            raise ValueError(f"field_map {name} has invalid multiplier")
        normalized[name] = dict(config)
    return normalized


def _number(value):
    if classify_value(value) not in {"zero", "valid"}:
        return None
    return float(value)


def _same(left, right):
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _status(raw_values, adapted_values, normalized_values, config, trade_date):
    raw_value = raw_values.get(config["raw"]) if raw_values is not None else None
    adapted_value = adapted_values.get(config["adapted"]) if adapted_values is not None else None
    normalized_value = normalized_values.get(config["normalized"]) if normalized_values is not None else None
    classes = {
        "raw": classify_value(raw_value),
        "adapted": classify_value(adapted_value),
        "normalized": classify_value(normalized_value),
    }
    if trade_date is None:
        status = "not_comparable"
    elif raw_values is None or adapted_values is None or normalized_values is None:
        status = "unmatched_identity"
    elif classes["raw"] == "missing" and classes["adapted"] == "zero":
        status = "missing_coerced_to_zero"
    elif "invalid" in classes.values():
        status = "invalid"
    elif classes["raw"] in {"zero", "valid"} and classes["adapted"] == "missing":
        status = "field_dropped"
    elif config["adapted"] in adapted_values and classes["adapted"] in {"zero", "valid"} and classes["normalized"] == "missing":
        status = "field_dropped"
    else:
        raw_number, adapted_number, normalized_number = _number(raw_value), _number(adapted_value), _number(normalized_value)
        if raw_number is not None and adapted_number is not None and normalized_number is not None:
            converted = _same(raw_number * float(config["multiplier"]), adapted_number)
            if converted and _same(adapted_number, normalized_number):
                status = "unit_converted" if float(config["multiplier"]) != 1 else "retained"
            elif _same(raw_number, adapted_number) and _same(adapted_number, normalized_number):
                status = "retained"
            else:
                status = "invalid"
        elif classes["raw"] == classes["adapted"] == classes["normalized"] == "missing":
            status = "retained"
        else:
            status = "invalid"
    return {
        "raw": raw_value,
        "adapted": adapted_value,
        "normalized": normalized_value,
        "classification": classes,
        "status": status,
        "source": config["source"],
        "unit": config["unit"],
        "multiplier": config["multiplier"],
    }


def compare_field_stages(raw_rows, adapted_rows, normalized_rows, field_map):
    """Compare records by symbol/date and report loss without silent repair.

    Date-less real-time records are retained for evidence but are explicitly
    ``not_comparable`` rather than treated as a historical observation.
    """
    raw = _records(raw_rows, "raw")
    adapted = _records(adapted_rows, "adapted")
    normalized = _records(normalized_rows, "normalized")
    fields = _field_map(field_map)
    keys = sorted(set(raw) | set(adapted) | set(normalized), key=lambda item: (item[0], item[1] or ""))
    rows = []
    coverage = {source: {"denominator": 0, "comparable": 0, "retained": 0, "rate": None}
                for source in sorted({config["source"] for config in fields.values()})}
    issues = []
    for symbol, trade_date in keys:
        row_fields = {}
        for name, config in fields.items():
            detail = _status(raw.get((symbol, trade_date)), adapted.get((symbol, trade_date)), normalized.get((symbol, trade_date)), config, trade_date)
            if detail["status"] not in _STATUSES:
                raise AssertionError("unsupported field status")
            row_fields[name] = detail
            stats = coverage[config["source"]]
            stats["denominator"] += 1
            if detail["status"] not in {"not_comparable", "unmatched_identity"}:
                stats["comparable"] += 1
                if detail["status"] in {"retained", "unit_converted"}:
                    stats["retained"] += 1
            if detail["status"] not in {"retained", "unit_converted", "not_comparable"}:
                issues.append({"symbol": symbol, "trade_date": trade_date, "field": name, "status": detail["status"]})
        rows.append({"symbol": symbol, "trade_date": trade_date, "fields": row_fields})
    for stats in coverage.values():
        stats["rate"] = stats["retained"] / stats["comparable"] if stats["comparable"] else None
    return {"rows": rows, "coverage": coverage, "issues": issues}


def _canonical_bytes(value):
    """Serialize evidence deterministically and reject non-finite JSON values."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("capture must contain strict JSON values") from exc


def _verified_raw_files(input_dir):
    manifest_path = input_dir / "request-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("request manifest is unreadable") from exc
    files = manifest.get("raw_files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        raise ValueError("request manifest raw_files must be a list")
    verified = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise ValueError("request manifest raw_files entry is invalid")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("raw capture path must be relative")
        path = input_dir / relative
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ValueError("raw capture is unreadable") from exc
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise ValueError("raw capture sha256 mismatch")
        try:
            verified.append(json.loads(payload.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("raw capture is not JSON") from exc
    return verified


def load_verified_capture(input_dir):
    """Return decoded raw artifacts only after every manifest hash verifies."""
    return _verified_raw_files(Path(input_dir))


def build_verified_replay(input_dir, output_dir, field_map):
    """Create a cache-only comparison after verifying captured raw-file hashes.

    The function has no network transport. Existing output directories are a
    hard error so an evidence run cannot silently overwrite another capture.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("replay output already exists")
    captures = load_verified_capture(input_dir)
    raw_rows, adapted_rows, normalized_rows = [], [], []
    for capture in captures:
        if isinstance(capture, list):
            raw_rows.extend(capture)
        elif isinstance(capture, dict):
            for name, target in (("raw_rows", raw_rows), ("adapted_rows", adapted_rows), ("normalized_rows", normalized_rows)):
                rows = capture.get(name, [])
                if not isinstance(rows, list):
                    raise ValueError(f"capture {name} must be a list")
                target.extend(rows)
        else:
            raise ValueError("raw capture must be a list or an object")
    result = compare_field_stages(raw_rows, adapted_rows, normalized_rows, field_map)
    output_dir.mkdir(parents=True)
    for name, value in (("stage-diff.json", {"rows": result["rows"], "issues": result["issues"]}), ("coverage.json", result["coverage"])):
        (output_dir / name).write_bytes(_canonical_bytes(value))
    return result
