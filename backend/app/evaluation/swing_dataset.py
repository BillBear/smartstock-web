"""Pure, day-batch research inputs. No fetching, adjustment, proxies or trading.

Only TuShare daily/raw, daily_basic and adj_factor contracts are supported.
Hashes fingerprint the supplied decoded response, not the original HTTP bytes.
Raw rejected records may contain NaN/Infinity: their fingerprints use Python's
stable JSON spelling, while such values never enter accepted numeric fields.
"""

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import math
import re


_DAILY_FIELDS = {
    "open": ("open", 1), "high": ("high", 1), "low": ("low", 1),
    "close": ("close", 1), "pre_close": ("pre_close", 1),
    "change": ("change", 1), "pct_change": ("pct_chg", 1),
    "volume": ("vol", 100), "amount": ("amount", 1000),
}
_BASIC_FIELDS = {
    "turnover_rate": ("turnover_rate", 1), "turnover_rate_f": ("turnover_rate_f", 1),
    "volume_ratio": ("volume_ratio", 1), "circ_mv": ("circ_mv", 10000),
}
_FACTOR_FIELDS = {"adj_factor": ("adj_factor", 1)}
_CORE_DAILY = ("open", "high", "low", "close", "volume", "amount")
_PRICE_FIELDS = ("open", "high", "low", "close", "pre_close")
_UNITS = {
    **{field: "yuan_per_share" for field in (*_PRICE_FIELDS, "change")},
    "pct_change": "percent", "volume": "shares", "amount": "yuan",
    "turnover_rate": "percent", "turnover_rate_f": "percent",
    "volume_ratio": "unitless", "circ_mv": "yuan", "adj_factor": "unitless",
}
_ENDPOINTS = {"daily": "daily", "basics": "daily_basic", "factors": "adj_factor"}


def compact_trade_date(value: str) -> str:
    """Validate YYYYMMDD or YYYY-MM-DD without inferring a trading calendar."""
    if type(value) is not str or not re.fullmatch(r"(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})", value):
        raise ValueError("trade_date must be YYYYMMDD or YYYY-MM-DD")
    compact = value.replace("-", "")
    try:
        date(int(compact[:4]), int(compact[4:6]), int(compact[6:]))
    except ValueError as exc:
        raise ValueError(f"invalid trade_date: {value}") from exc
    return compact


def _sha256(value):
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("raw response must contain JSON-compatible values") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _contract(source, adjustment):
    if source != "tushare" or adjustment != "raw":
        raise ValueError(f"unsupported input contract: {source}/{adjustment}")


def _key(row):
    if type(row) is not dict:
        raise ValueError("raw row must be an object")
    code = row.get("ts_code")
    if type(code) is not str or not re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", code):
        raise ValueError("unsupported ts_code: expected six-digit SH/SZ/BJ symbol")
    return code, compact_trade_date(row.get("trade_date"))


def _preflight(rows, name):
    if type(rows) is not list:
        raise ValueError(f"{name} response must be a list")
    seen = set()
    for row in rows:
        if type(row) is dict:
            if any(field in row for field in ("schema_version", "units", "raw_inputs", "volume")):
                raise ValueError("already normalized input is not accepted")
            if "value_kind" in row and row["value_kind"] != "actual":
                raise ValueError("proxy or unknown value_kind is not accepted as provider raw input")
            _contract(row.get("source", "tushare"), row.get("adjustment", "raw"))
        try:
            key = _key(row)
        except ValueError:
            continue
        if key in seen:
            raise ValueError(f"duplicate {name} symbol/date key: {key}")
        seen.add(key)


def _number(raw, field, multiplier):
    value = raw.get(field)
    if value is None:
        return None
    if type(value) not in (int, float, str) or (type(value) is str and not value.strip()):
        raise ValueError(f"invalid numeric {field}")
    try:
        number = float(value) * multiplier
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"invalid numeric {field}") from exc
    if not math.isfinite(number):
        raise ValueError(f"non-finite numeric {field}")
    if field not in ("change", "pct_chg") and number < 0:
        raise ValueError(f"negative numeric {field}")
    if field in (*_PRICE_FIELDS, "adj_factor") and number == 0:
        raise ValueError(f"non-positive numeric {field}")
    return number


def _values(raw, fields):
    return {field: _number(raw, original, multiplier)
            for field, (original, multiplier) in fields.items()}


def _normalize_daily(row):
    code, day = _key(row)
    values = _values(row, _DAILY_FIELDS)
    missing = [field for field in _CORE_DAILY if values[field] is None]
    return {
        "schema_version": "swing-daily-input-v1", "symbol": code[:6], "ts_code": code,
        "trade_date": day, **values, "source": "tushare", "adjustment": "raw",
        "units": {field: _UNITS[field] for field in _DAILY_FIELDS},
        "value_kind": {field: "missing" if value is None else "actual" for field, value in values.items()},
        "fetched_at": None, "available_at": None, "availability_status": "unknown",
        "availability_assumption": None,
        "quality_status": "incomplete" if missing else "complete",
        "quality_issues": [f"missing:{field}" for field in missing],
        "adjusted_input_usable": False,
        "raw": deepcopy(row), "raw_sha256": _sha256(row),
    }


def normalize_daily_rows(rows: list, source: str, adjustment: str) -> list:
    """Normalize raw TuShare daily rows once; invalid rows raise ValueError.

    No price is multiplied by an adjustment factor. pre_close/pct_chg retain
    TuShare's corporate-action reference semantics, not previous raw close.
    Missing values stay None. Use join_daily_inputs for per-row quarantine.
    """
    _contract(source, adjustment)
    _preflight(rows, "daily")
    return [_normalize_daily(row) for row in rows]


def _timestamp(value, field):
    if value is None:
        return None
    try:
        if type(value) is not str:
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp or null") from exc
    return parsed


def _metadata(metadata, inputs):
    if type(metadata) is not dict or type(metadata.get("endpoints", {})) is not dict:
        raise ValueError("metadata and endpoints must be objects")
    _contract(metadata.get("source", "tushare"), metadata.get("adjustment", "raw"))
    available_at = _timestamp(metadata.get("available_at"), "available_at")
    _timestamp(metadata.get("fetched_at"), "fetched_at")
    assumption = metadata.get("availability_assumption")
    if assumption is not None and (type(assumption) is not str or not assumption.strip()):
        raise ValueError("availability_assumption must be a nonempty string or null")
    if available_at is not None and not assumption:
        raise ValueError("available_at requires an explicit availability_assumption")
    endpoints = {}
    for name, endpoint in _ENDPOINTS.items():
        item = metadata.get("endpoints", {}).get(name, {})
        if type(item) is not dict:
            raise ValueError(f"metadata endpoint {name} must be an object")
        _contract(item.get("source", "tushare"), item.get("adjustment", "raw"))
        if item.get("endpoint", endpoint) != endpoint:
            raise ValueError(f"unsupported endpoint contract for {name}")
        _timestamp(item.get("fetched_at"), f"{name}.fetched_at")
        endpoint_available = _timestamp(item.get("available_at"), f"{name}.available_at")
        if available_at is not None and endpoint_available is not None and endpoint_available > available_at:
            raise ValueError(f"batch available_at precedes {name}.available_at")
        status = item.get("status", "ok" if inputs[name] else "empty")
        if status not in ("ok", "empty", "error", "timeout", "permission_denied", "unavailable", "partial", "unknown"):
            raise ValueError(f"unsupported endpoint status: {status}")
        if status == "ok" and not inputs[name]:
            status = "empty"
        endpoints[name] = {"source": "tushare", "endpoint": endpoint, **deepcopy(item), "status": status}
    return endpoints


def join_daily_inputs(daily: list, basics: list, factors: list, metadata: dict) -> dict:
    """Join *raw* responses by exchange-qualified symbol and date in one batch.

    Duplicate keys and unsupported contracts hard-fail. Invalid records and
    orphan supplements are quarantined with raw hashes. Row completeness only
    describes this data contract, not tradability or historically proven access.
    available_at is caller-supplied, explicitly assumed, and never fabricated
    from fetched_at. Metadata, including endpoint/fallback details, is retained.
    Call once per date for bounded memory; this function performs no IO.
    """
    inputs = {"daily": daily, "basics": basics, "factors": factors}
    for name, records in inputs.items():
        _preflight(records, name)
    endpoints = _metadata(metadata, inputs)
    hashes = {name: _sha256(records) for name, records in inputs.items()}
    rejected = []
    indexes = {name: {} for name in inputs}

    def reject(name, index, raw, reason):
        rejected.append({"input": name, "index": index, "reason": reason,
                         "raw": deepcopy(raw), "raw_sha256": _sha256(raw)})

    for name, records in inputs.items():
        for index, raw in enumerate(records):
            try:
                key = _key(raw)
                values = (_normalize_daily(raw) if name == "daily" else
                          _values(raw, _BASIC_FIELDS if name == "basics" else _FACTOR_FIELDS))
            except ValueError as exc:
                reject(name, index, raw, str(exc))
                continue
            indexes[name][key] = (index, raw, values)

    for name in ("basics", "factors"):
        for key, (index, raw, _) in indexes[name].items():
            if key not in indexes["daily"]:
                reject(name, index, raw, "unmatched_key")

    rows = []
    matched = {"basics": 0, "factors": 0}
    for key, (_, raw, row) in indexes["daily"].items():
        raw_inputs = {"daily": deepcopy(raw), "basics": None, "factors": None}
        for name, fields in (("basics", _BASIC_FIELDS), ("factors", _FACTOR_FIELDS)):
            entry = indexes[name].get(key)
            values = entry[2] if entry else {field: None for field in fields}
            if entry:
                matched[name] += 1
                raw_inputs[name] = deepcopy(entry[1])
            row.update(values)
            row["value_kind"].update({field: "missing" if value is None else "actual"
                                       for field, value in values.items()})
        row["units"] = dict(_UNITS)
        row["raw_inputs"] = raw_inputs
        row["raw_input_sha256"] = {name: _sha256(raw) if raw is not None else None
                                     for name, raw in raw_inputs.items()}
        row["fetched_at"] = deepcopy(metadata.get("fetched_at"))
        row["available_at"] = deepcopy(metadata.get("available_at"))
        row["availability_assumption"] = deepcopy(metadata.get("availability_assumption"))
        row["availability_status"] = "assumed" if row["availability_assumption"] else "unknown"
        missing = [field for field in (*_CORE_DAILY, *_BASIC_FIELDS, "adj_factor") if row[field] is None]
        row["quality_issues"] = [f"missing:{field}" for field in missing]
        row["quality_issues"] += [f"endpoint:{name}:{item['status']}" for name, item in endpoints.items()
                                  if item["status"] != "ok"]
        row["quality_status"] = "incomplete" if row["quality_issues"] else "complete"
        row["adjusted_input_usable"] = (all(row[field] is not None for field in (*_CORE_DAILY, "adj_factor"))
                                         and all(endpoints[name]["status"] == "ok" for name in ("daily", "factors")))
        rows.append(row)

    field_coverage = {}
    for field in _UNITS:
        actual = sum(row[field] is not None for row in rows)
        field_coverage[field] = {"actual": actual, "missing": len(rows) - actual, "proxy": 0,
                                 "fraction": actual / len(rows) if rows else None}
    return {
        "rows": rows,
        "coverage": {
            "received": {name: len(records) for name, records in inputs.items()},
            "daily_rows": len(rows), "matched": matched,
            "rejected": {name: sum(item["input"] == name for item in rejected) for name in inputs},
            "complete_rows": sum(row["quality_status"] == "complete" for row in rows),
            "adjusted_input_usable": sum(row["adjusted_input_usable"] for row in rows),
            "endpoint_status": {name: item["status"] for name, item in endpoints.items()},
            "field_coverage": field_coverage,
        },
        "provenance": {"source": "tushare", "adjustment": "raw", "endpoints": endpoints,
                       "response_sha256": hashes, "metadata": deepcopy(metadata)},
        "rejected": rejected,
    }
