#!/usr/bin/env python3
"""Capture a bounded provider-field contract probe without application startup.

Probe mode makes exactly six TuShare requests: daily, daily_basic and
adj_factor for each of 20260720 and 20260831. Tencent is one batch request;
AKShare is one spot request in an isolated child process. Cache-only mode
performs no transport and refuses an altered raw capture.
"""

import argparse
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import signal
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.provider_contract_check import compare_field_stages, build_verified_replay, stage_summary
from app.services.data_source_manager import DataSourceManager
from app.services.tushare_service import TuShareService


DATES = ("20260720", "20260831")
SYMBOLS = ("000651.SZ", "601988.SH", "000001.SZ")
PLAIN_SYMBOLS = tuple(symbol[:6] for symbol in SYMBOLS)
TUSHARE_FIELDS = {
    "daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
    "daily_basic": "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,circ_mv",
    "adj_factor": "ts_code,trade_date,adj_factor",
}
FIELD_MAP = {
    "price": {"raw": "close", "adapted": "price", "normalized": "price", "source": "tushare.daily", "unit": "yuan_per_share", "multiplier": 1},
    "open": {"raw": "open", "adapted": "open", "normalized": "open", "source": "tushare.daily", "unit": "yuan_per_share", "multiplier": 1},
    "high": {"raw": "high", "adapted": "high", "normalized": "high", "source": "tushare.daily", "unit": "yuan_per_share", "multiplier": 1},
    "low": {"raw": "low", "adapted": "low", "normalized": "low", "source": "tushare.daily", "unit": "yuan_per_share", "multiplier": 1},
    "volume": {"raw": "vol", "adapted": "volume", "normalized": "volume", "source": "tushare.daily", "unit": "shares", "multiplier": 100},
    "amount": {"raw": "amount", "adapted": "amount", "normalized": "amount", "source": "tushare.daily", "unit": "yuan", "multiplier": 1000},
    "turnover_rate": {"raw": "turnover_rate", "adapted": "turnover_rate", "normalized": "turnover_rate", "source": "tushare.daily_basic", "unit": "percent", "multiplier": 1},
    "turnover_rate_f": {"raw": "turnover_rate_f", "adapted": "turnover_rate_f", "normalized": "turnover_rate_f", "source": "tushare.daily_basic", "unit": "percent", "multiplier": 1},
    "volume_ratio": {"raw": "volume_ratio", "adapted": "volume_ratio", "normalized": "volume_ratio", "source": "tushare.daily_basic", "unit": "unitless", "multiplier": 1},
    "circ_mv": {"raw": "circ_mv", "adapted": "circ_mv", "normalized": "circ_mv", "source": "tushare.daily_basic", "unit": "yuan", "multiplier": 10000},
    "adj_factor": {"raw": "adj_factor", "adapted": "adj_factor", "normalized": "adj_factor", "source": "tushare.adj_factor", "unit": "unitless", "multiplier": 1},
}


class ProbeError(ValueError):
    """Credential-free failure category for a bounded provider request."""


class _Timeout(Exception):
    pass


def _sanitize(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"__nonfinite__": "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")}
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _encoded(value):
    return json.dumps(_sanitize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _encoded(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _error_category(exc, token):
    message = str(exc).replace(token, "[REDACTED]") if token else str(exc)
    lowered = message.lower()
    if isinstance(exc, _Timeout) or "timeout" in lowered:
        return "timeout"
    if any(item in lowered for item in ("permission", "token", "权限", "积分", "quota")):
        return "permission_or_quota"
    return "provider_error"


def _run_with_timeout(seconds, operation):
    if not hasattr(signal, "SIGALRM"):
        return operation()
    def on_alarm(_signum, _frame):
        raise _Timeout()
    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return operation()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _load_token(env_file):
    from dotenv import dotenv_values
    token = dotenv_values(env_file).get("TUSHARE_TOKEN")
    if not isinstance(token, str) or not token.strip():
        raise ProbeError("TUSHARE_TOKEN_required")
    return token.strip()


def _selected_records(dataframe, date_value):
    if dataframe is None:
        return []
    records = dataframe.to_dict(orient="records")
    return [row for row in records if str(row.get("ts_code") or "") in SYMBOLS and str(row.get("trade_date") or "") == date_value]


def _adapter_rows(daily_rows, trade_date):
    """Exercise the current production adapter with captured daily rows only."""
    import pandas as pd

    class CapturedPro:
        def stock_basic(self, **_kwargs):
            return pd.DataFrame([{"name": "captured"}])

        def daily(self, **kwargs):
            symbol = kwargs.get("ts_code")
            return pd.DataFrame([row for row in daily_rows if row.get("ts_code") == symbol])

    service = object.__new__(TuShareService)
    service._cache = {}
    service._cache_ttl = 60
    service.pro = CapturedPro()
    manager = object.__new__(DataSourceManager)
    adapted, normalized = [], []
    for symbol in SYMBOLS:
        rows = [row for row in daily_rows if row.get("ts_code") == symbol]
        if not rows:
            continue
        quote = service.get_realtime_quote(symbol)
        plain_symbol = symbol[:6]
        adapted.append({"symbol": plain_symbol, "trade_date": trade_date, "values": quote or {}})
        normalized.append({"symbol": plain_symbol, "trade_date": trade_date, "values": manager._normalize_realtime_quote(quote or {}, plain_symbol)})
    return adapted, normalized


def _raw_rows(responses, trade_date):
    for rows in responses.values():
        _validate_endpoint_rows(rows, trade_date)
    by_symbol = {symbol: {} for symbol in SYMBOLS}
    for endpoint, rows in responses.items():
        for row in rows:
            symbol = row.get("ts_code")
            if symbol in by_symbol:
                by_symbol[symbol].update(row)
    return [{"symbol": symbol[:6], "trade_date": trade_date, "values": values}
            for symbol, values in sorted(by_symbol.items()) if values]


def _akshare_worker(queue):
    try:
        import akshare as ak
        dataframe = ak.stock_zh_a_spot_em()
        rows = dataframe[dataframe["代码"].astype(str).isin(PLAIN_SYMBOLS)].to_dict(orient="records")
        queue.put({"status": "ok", "rows": rows})
    except Exception as exc:  # Child reports a credential-free category only.
        queue.put({"status": "unavailable", "error": type(exc).__name__})


def _probe_akshare():
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_akshare_worker, args=(queue,))
    process.start()
    process.join(60)
    if process.is_alive():
        process.terminate()
        process.join()
        return {"status": "timeout", "rows": []}
    return queue.get() if not queue.empty() else {"status": "unavailable", "rows": []}


def _probe_tencent():
    from app.services.tencent_service import TencentService
    try:
        quotes = _run_with_timeout(15, lambda: TencentService(timeout=15).get_realtime_quotes_batch(PLAIN_SYMBOLS))
        return {"status": "ok" if len(quotes) == len(PLAIN_SYMBOLS) else "partial", "rows": list(quotes.values())}
    except Exception as exc:
        return {"status": _error_category(exc, ""), "rows": []}


def probe(env_file, output_dir):
    """Run the bounded live probe; never start the app or construct a store."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("probe output already exists")
    token = _load_token(env_file)
    import tushare as ts
    pro = ts.pro_api(token)
    output_dir.mkdir(parents=True)
    raw_files, all_raw, all_adapted, all_normalized, statuses = [], [], [], [], []
    for day in DATES:
        responses = {}
        for endpoint, fields in TUSHARE_FIELDS.items():
            try:
                operation = lambda endpoint=endpoint, fields=fields: getattr(pro, endpoint)(trade_date=day, fields=fields)
                rows = _selected_records(_run_with_timeout(15, operation), day)
                responses[endpoint] = rows
                status = "ok" if len(rows) == len(SYMBOLS) else "partial"
            except Exception as exc:
                responses[endpoint] = []
                status = _error_category(exc, token)
            relative = Path("raw") / day / f"tushare-{endpoint}.json"
            digest = _write_json(output_dir / relative, {"source": "tushare", "endpoint": endpoint, "trade_date": day, "status": status, "rows": responses[endpoint]})
            raw_files.append({"path": str(relative), "sha256": digest})
            statuses.append({"source": "tushare", "endpoint": endpoint, "trade_date": day, "status": status, "row_count": len(responses[endpoint])})
        raw_rows = _raw_rows(responses, day)
        adapted_rows, normalized_rows = _adapter_rows(responses["daily"], day)
        all_raw.extend(raw_rows)
        all_adapted.extend(adapted_rows)
        all_normalized.extend(normalized_rows)
    tencent = _probe_tencent()
    tencent_relative = Path("raw/tencent-batch.json")
    raw_files.append({"path": str(tencent_relative), "sha256": _write_json(output_dir / tencent_relative, tencent)})
    statuses.append({"source": "tencent", "endpoint": "batch_quote", "trade_date": None, "status": tencent["status"], "row_count": len(tencent["rows"])})
    akshare = _probe_akshare()
    akshare_relative = Path("raw/akshare-spot.json")
    raw_files.append({"path": str(akshare_relative), "sha256": _write_json(output_dir / akshare_relative, akshare)})
    statuses.append({"source": "akshare", "endpoint": "stock_zh_a_spot_em", "trade_date": None, "status": akshare["status"], "row_count": len(akshare.get("rows", []))})
    stage_relative = Path("raw/stage-records.json")
    raw_files.append({"path": str(stage_relative), "sha256": _write_json(output_dir / stage_relative, {"raw_rows": all_raw, "adapted_rows": all_adapted, "normalized_rows": all_normalized})})
    diff = compare_field_stages(all_raw, all_adapted, all_normalized, FIELD_MAP)
    _write_json(output_dir / "field-contracts.json", {"schema_version": "provider-field-contract-v1", "fields": FIELD_MAP})
    _write_json(output_dir / "stage-diff.json", {"rows": diff["rows"], "issues": diff["issues"]})
    _write_json(output_dir / "coverage.json", diff["coverage"])
    manifest = {
        "schema_version": "provider-field-probe-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tushare_request_budget": 6,
        "tushare_requests_attempted": len(DATES) * len(TUSHARE_FIELDS),
        "symbols": list(SYMBOLS),
        "trade_dates": list(DATES),
        "raw_files": raw_files,
        "statuses": statuses,
        "limitations": [
            "tencent_batch_quote_is_current_time_only_not_historical_comparison",
            "akshare_spot_is_current_time_only_not_historical_comparison",
            "probe_observes_current_adapter_behavior_and_does_not_change_production_fields",
        ],
    }
    _write_json(output_dir / "request-manifest.json", manifest)
    complete = all(item["status"] == "ok" for item in statuses)
    return {"status": "complete" if complete else "partial", "output_dir": str(output_dir), "statuses": statuses}


def _validate_endpoint_rows(rows, day):
    if not isinstance(rows, list):
        raise ValueError("endpoint rows must be a list")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("trade_date") != day:
            raise ValueError("wrong response date")
        symbol = row.get("ts_code")
        if symbol not in SYMBOLS:
            raise ValueError("unexpected response symbol")
        if symbol in seen:
            raise ValueError("duplicate response symbol/date")
        seen.add(symbol)


def analyze_captures(captures, field_map):
    """Validate identities before rebuilding, never trust captured stage rows."""
    by_day = {day: {} for day in DATES}
    realtime = {}
    for capture in captures:
        if not isinstance(capture, dict):
            raise ValueError("capture must be an object")
        source = capture.get("source")
        path = capture.get("_capture", {}).get("path", "")
        if "raw_rows" in capture:
            # Legacy stage-records are derived and known to be contaminated.
            continue
        if source is None:
            source = {"tencent-batch.json": "tencent", "akshare-spot.json": "akshare"}.get(Path(path).name)
        if source == "tushare":
            day, endpoint = capture.get("trade_date"), capture.get("endpoint")
            if day not in by_day or endpoint not in TUSHARE_FIELDS:
                raise ValueError("unexpected endpoint/date")
            if endpoint in by_day[day]:
                raise ValueError("duplicate endpoint/date")
            _validate_endpoint_rows(capture.get("rows"), day)
            by_day[day][endpoint] = capture
        elif source in {"tencent", "akshare"}:
            if source in realtime:
                raise ValueError("duplicate realtime endpoint")
            rows = capture.get("rows", [])
            if not isinstance(rows, list):
                raise ValueError("realtime rows must be a list")
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("realtime row must be an object")
                symbol = row.get("code") or row.get("symbol") or row.get("代码")
                if symbol not in PLAIN_SYMBOLS:
                    raise ValueError("unexpected realtime symbol")
                if symbol in seen:
                    raise ValueError("duplicate realtime symbol")
                seen.add(symbol)
            realtime[source] = capture
        else:
            raise ValueError("unknown capture source")
    all_raw, all_adapted, all_normalized = [], [], []
    statuses, source_keys = [], {}
    for day in DATES:
        responses = {}
        for endpoint in TUSHARE_FIELDS:
            capture = by_day[day].get(endpoint, {})
            rows = capture.get("rows", [])
            responses[endpoint] = rows
            source = "tushare." + endpoint
            source_keys.setdefault(source, []).extend((row["ts_code"][:6], day) for row in rows)
            statuses.append({"source": source, "trade_date": day,
                             "status": capture.get("status", "unknown"),
                             "observed_rows": len(rows), "expected_rows": len(SYMBOLS),
                             "complete": capture.get("status") == "ok" and len(rows) == len(SYMBOLS)})
        raw_rows = _raw_rows(responses, day)
        adapted_rows, normalized_rows = _adapter_rows(responses.get("daily", []), day)
        all_raw.extend(raw_rows)
        all_adapted.extend(adapted_rows)
        all_normalized.extend(normalized_rows)
    diff = compare_field_stages(all_raw, all_adapted, all_normalized, field_map, source_keys)
    for source, stats in diff["coverage"].items():
        stats["expected_rows"] = len(DATES) * len(SYMBOLS)
    realtime_stages = {}
    manager = object.__new__(DataSourceManager)
    for source in ("tencent", "akshare"):
        capture = realtime.get(source, {})
        rows = capture.get("rows", [])
        statuses.append({"source": source, "trade_date": None, "status": capture.get("status", "unavailable"),
                         "observed_rows": len(rows), "expected_rows": len(SYMBOLS),
                         "complete": capture.get("status") == "ok" and len(rows) == len(SYMBOLS)})
        fields = list(field_map)
        raw, adapted, normalized = [], [], []
        if source == "tencent":
            adapted = rows
            normalized = manager._normalize_market_snapshot(rows)
        else:
            raw = rows
        stage_rows = {"raw": raw, "adapted": adapted, "normalized": normalized}
        diff["coverage"][source] = {
            "observed_rows": len(rows), "expected_rows": len(SYMBOLS),
            "denominator": len(raw), "rate": None, "comparison": "not_comparable",
            "stages": {stage: stage_summary(values, fields) for stage, values in stage_rows.items()},
        }
        realtime_stages[source] = {"status": "not_comparable", "trade_date": None,
                                   "reason": "raw_payload_not_captured" if source == "tencent" else "unavailable_or_unadapted",
                                   **stage_rows}
    complete = all(item["complete"] for item in statuses)
    return {"status": "complete" if complete else "partial", "replay_completed": True,
            "capture_status": "complete" if complete else "partial",
            "contract_status": "issues_detected" if diff["issues"] else "not_comparable" if not all_raw else "retained",
            "statuses": statuses, "coverage": diff["coverage"],
            "stage_diff": {"rows": diff["rows"], "issues": diff["issues"], "realtime_stages": realtime_stages}}


def replay_probe(input_dir, output_dir):
    """Use the sole validated replay route; transport is never constructed."""
    return build_verified_replay(input_dir, output_dir, FIELD_MAP, analyze_captures)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("probe", "cache-only"), required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "probe":
            if not args.env_file:
                raise ProbeError("--env-file is required for probe")
            result = probe(args.env_file, args.output_dir)
        else:
            if not args.input_dir:
                raise ProbeError("--input-dir is required for cache-only")
            result = replay_probe(args.input_dir, args.output_dir)
    except (OSError, ProbeError, ValueError, FileExistsError) as exc:
        print(f"provider_contract_check_failed:{type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"provider_contract_check_status:{result['status']}")
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
