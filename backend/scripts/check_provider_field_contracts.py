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
from pathlib import Path
import signal
import sys
import time
import re
import threading
from queue import Empty
from importlib.metadata import version, PackageNotFoundError
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.provider_contract_check import compare_field_stages, build_verified_replay, stage_summary, load_verified_capture
from app.evaluation.swing_dataset import join_daily_inputs
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
    "pct_change": {"raw": "pct_chg", "adapted": "pct_change", "normalized": "pct_change", "source": "tushare.daily", "unit": "percent", "multiplier": 1},
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


class _Timeout(BaseException):
    """Do not let provider broad Exception handlers swallow our deadline."""
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
    if not all(hasattr(signal, attr) for attr in ("SIGALRM", "setitimer", "getitimer", "ITIMER_REAL")) or threading.current_thread() is not threading.main_thread():
        raise ProbeError("safe_timeout_unsupported")
    if seconds <= 0:
        raise _Timeout()
    def on_alarm(_signum, _frame):
        raise _Timeout()
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    previous = signal.signal(signal.SIGALRM, on_alarm)
    effective = min(seconds, previous_timer[0]) if previous_timer[0] else seconds
    signal.setitimer(signal.ITIMER_REAL, effective)
    try:
        return operation()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, previous_timer[0] - (time.monotonic() - started)), previous_timer[1])


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
    seen = set()
    for row in records:
        symbol = row.get("ts_code")
        if row.get("trade_date") != date_value:
            raise ValueError("wrong response date")
        if not isinstance(symbol, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", symbol):
            raise ValueError("invalid response symbol")
        if symbol in seen:
            raise ValueError("duplicate response symbol/date")
        seen.add(symbol)
    return [row for row in records if row["ts_code"] in SYMBOLS]


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
                by_symbol[symbol].update({key: row[key] for key in TUSHARE_FIELDS[endpoint].split(",") if key in row})
    return [{"symbol": symbol[:6], "trade_date": trade_date, "values": values}
            for symbol, values in sorted(by_symbol.items()) if values]


def _akshare_worker(queue):
    try:
        import akshare as ak
        dataframe = ak.stock_zh_a_spot_em()
        rows = dataframe[dataframe["代码"].astype(str).isin(PLAIN_SYMBOLS)].to_dict(orient="records")
        queue.put({"status": "ok", "rows": rows, "evidence_level": "selected_sdk_rows",
                   "request": {"endpoint": "stock_zh_a_spot_em", "parameters": {}, "fields": "SDK_default"},
                   "response_metadata": {"returned_rows_before_filter": len(dataframe), "columns": list(dataframe.columns),
                                         "source_date": "unknown", "http_status": "unknown"}, "sdk_version": version("akshare")})
    except Exception as exc:  # Child reports a credential-free category only.
        queue.put({"status": "unavailable", "error": type(exc).__name__})


def _probe_akshare(timeout=60):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_akshare_worker, args=(queue,))
    process.start()
    try:
        # Drain before join: a large SDK result must not deadlock the queue feeder.
        try:
            return queue.get(timeout=min(60, timeout))
        except Empty:
            return {"status": "timeout", "rows": []}
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        queue.close()


def _probe_tencent():
    from app.services.tencent_service import TencentService
    service = TencentService(timeout=15)
    market_symbols = ",".join(service._to_market_symbol(symbol) for symbol in PLAIN_SYMBOLS)
    request = {"symbols": list(PLAIN_SYMBOLS), "timeout_seconds": 15}
    try:
        response = service.session.get(service.QUOTE_API.format(market_symbol=market_symbols), timeout=15)
        response.raise_for_status()
        payload = response.content.decode("gbk", errors="strict")
        quotes, seen, parse_errors = [], set(), []
        for line in payload.split(";"):
            if '=\"' not in line:
                continue
            prefix, raw = line.strip().split('=\"', 1)
            symbol = service._to_plain_symbol(prefix.replace("v_", ""))
            if symbol not in PLAIN_SYMBOLS or symbol in seen:
                raise ProbeError("duplicate_or_unexpected_tencent_symbol")
            seen.add(symbol)
            try:
                quote = service._parse_quote_payload(symbol, raw.rsplit('"', 1)[0])
                if quote:
                    quotes.append(quote)
                else:
                    parse_errors.append({"symbol": symbol, "status": "parser_rejected"})
            except (ValueError, IndexError):
                parse_errors.append({"symbol": symbol, "status": "parser_error"})
        return {"status": "ok" if len(quotes) == len(PLAIN_SYMBOLS) else "partial", "rows": quotes,
                "raw_payload": payload, "evidence_level": "raw_payload_and_adapted",
                "request": request, "parse_errors": parse_errors,
                "response_metadata": {"http_status": response.status_code, "source_date": "inspect_raw_payload",
                                      "unit_contract": "unknown"}}
    except (Exception, _Timeout) as exc:
        return {"status": _error_category(exc, ""), "rows": []}
    finally:
        service.session.close()


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    if isinstance(value, dict):
        return {_redact(str(key), token): _redact(item, token) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, token) for item in value]
    return value


def probe(env_file, output_dir):
    """Bound live capture; this task exercises it with fake transports only."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("probe output already exists")
    _run_with_timeout(1, lambda: None)  # Reject unsafe platforms before loading credentials.
    token = _load_token(env_file)
    import tushare as ts
    pro = ts.pro_api(token)
    output_dir.mkdir(parents=True)
    captures, raw_files = [], []
    attempted, source_stopped = 0, False
    started = time.monotonic()
    deadline = started + 180

    def save(relative, capture):
        safe = _sanitize(_redact(capture, token))
        digest = _write_json(output_dir / relative, safe)
        ref = {"path": relative, "sha256": digest}
        raw_files.append(ref)
        captures.append(dict(safe, _capture=ref))

    def collect():
        nonlocal attempted, source_stopped
        for day in DATES:
            for endpoint, fields in TUSHARE_FIELDS.items():
                request = {"trade_date": day, "fields": fields}
                before = time.monotonic()
                capture = {"source": "tushare", "endpoint": endpoint, "trade_date": day,
                           "rows": [], "status": "skipped_after_source_failure" if source_stopped else "budget_exhausted",
                           "evidence_level": "selected_sdk_rows", "request": request,
                           "sdk_version": version("tushare"), "started_at": datetime.now(timezone.utc).isoformat()}
                remaining = deadline - before
                if not source_stopped and remaining > 0 and attempted < 6:
                    attempted += 1
                    try:
                        frame = _run_with_timeout(min(15, remaining), lambda: getattr(pro, endpoint)(**request))
                        rows = _selected_records(frame, day)
                        returned = len(frame) if frame is not None else 0
                        # Only the daily 6000 boundary is established in existing project evidence.
                        limit = 6000 if endpoint == "daily" else None
                        at_limit = returned >= limit if limit is not None else None
                        capture.update(rows=rows, status="ok" if len(rows) == len(SYMBOLS) and not at_limit else "partial",
                                       response_metadata={"returned_rows_before_filter": returned,
                                                          "columns": list(frame.columns) if frame is not None else [],
                                                          "selected_rows": len(rows), "source_date": day if returned else "unknown",
                                                          "known_limit": limit, "at_limit": at_limit,
                                                          "truncation_status": "possible" if at_limit else "unknown" if limit is None else "below_known_limit",
                                                          "http_status": "unknown"})
                    except (Exception, _Timeout) as exc:
                        capture["status"] = _error_category(exc, token)
                    source_stopped = capture["status"] != "ok"
                capture["elapsed_seconds"] = time.monotonic() - before
                save(f"raw/{day}/tushare-{endpoint}.json", capture)

        for name, operation, timeout in (("tencent", _probe_tencent, 15), ("akshare", _probe_akshare, 60)):
            before = time.monotonic()
            remaining = deadline - before
            capture = {"status": "budget_exhausted", "rows": []}
            if remaining > 0:
                try:
                    bound = min(timeout, remaining)
                    capture = _run_with_timeout(bound, lambda: operation(bound) if name == "akshare" else operation())
                except (Exception, _Timeout) as exc:
                    capture = {"status": _error_category(exc, token), "rows": []}
            capture.update(source=name, elapsed_seconds=time.monotonic() - before)
            save("raw/tencent-batch.json" if name == "tencent" else "raw/akshare-spot.json", capture)

    try:
        _run_with_timeout(180, collect)
    except _Timeout:
        # The outer hard deadline may interrupt validation as well as transport.
        # Keep every already written capture and make the incomplete run explicit.
        pass

    manifest = {"schema_version": "provider-field-probe-v2", "generated_at": datetime.now(timezone.utc).isoformat(),
                "symbols": list(SYMBOLS), "trade_dates": list(DATES), "raw_files": raw_files,
                "tushare_request_budget": 6, "tushare_requests_attempted": attempted,
                "network_budget_seconds": 180, "elapsed_seconds": time.monotonic() - started,
                "code_provenance": code_provenance(),
                "statuses": [{"source": item["source"], "endpoint": item.get("endpoint"),
                              "trade_date": item.get("trade_date"), "status": item["status"]} for item in captures]}
    _write_json(output_dir / "request-manifest.json", manifest)
    result = analyze_captures(captures, FIELD_MAP)
    for name, value in (("field-contracts.json", {"schema_version": "provider-field-contract-v2", "fields": FIELD_MAP}),
                        ("stage-diff.json", result["stage_diff"]), ("coverage.json", result["coverage"])):
        _write_json(output_dir / name, value)
    _write_json(output_dir / "analysis-manifest.json",
                {key: result[key] for key in ("replay_completed", "capture_status", "contract_status", "code_provenance")})
    return result


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


def _akshare_adapter_rows(rows):
    """Characterize the existing adapter in this standalone offline CLI only."""
    if not rows:
        return []
    import pandas as pd
    from unittest.mock import patch
    from app.services.akshare_service import AKShareService
    service = object.__new__(AKShareService)  # Its constructor changes proxies.
    with patch("app.services.akshare_service.ak.stock_zh_a_spot_em", return_value=pd.DataFrame(rows)):
        adapted = service.get_a_share_spot_snapshot()
    for row in adapted:
        # The adapter clock is not a provider timestamp or a historical identity.
        row["update_time"] = None
    return adapted


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
            if source is not None or Path(path).name != "stage-records.json":
                raise ValueError("unexpected derived stage marker")
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
    research_rows, research_batches = [], []
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
        endpoint_metadata = {}
        refs = {}
        for name, endpoint in (("daily", "daily"), ("basics", "daily_basic"), ("factors", "adj_factor")):
            capture = by_day[day].get(endpoint, {})
            status = capture.get("status", "unknown")
            status = {"permission_or_quota": "permission_denied", "provider_error": "error"}.get(status, status)
            if status not in {"ok", "empty", "error", "timeout", "permission_denied", "unavailable", "partial", "unknown"}:
                status = "unknown"
            endpoint_metadata[name] = {"endpoint": endpoint, "status": status}
            refs[endpoint] = capture.get("_capture", {"path": None, "sha256": None})
        joined = join_daily_inputs(responses["daily"], responses["daily_basic"], responses["adj_factor"],
                                   {"source": "tushare", "adjustment": "raw", "endpoints": endpoint_metadata})
        for row in joined["rows"]:
            row["capture_refs"] = refs
        research_rows.extend(joined["rows"])
        research_batches.append({"trade_date": day, **{key: joined[key] for key in ("coverage", "provenance", "rejected")}})
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
            adapted = _akshare_adapter_rows(rows)
            normalized = manager._normalize_market_snapshot(adapted)
        stage_rows = {"raw": raw, "adapted": adapted, "normalized": normalized}
        raw_names = {"price": "最新价", "pct_change": "涨跌幅", "open": "今开", "high": "最高", "low": "最低",
                     "volume": "成交量", "amount": "成交额", "turnover_rate": "换手率", "volume_ratio": "量比",
                     "circ_mv": "流通市值", "pe": "市盈率-动态", "pb": "市净率", "total_mv": "总市值"}
        fields = list(dict.fromkeys(fields + ["pe", "pb", "total_mv"]))
        summaries = {}
        for stage, values in stage_rows.items():
            summaries[stage] = {"row_count": len(values), "fields": {}}
            for field in fields:
                key = raw_names.get(field, field) if source == "akshare" and stage == "raw" else field
                stats = stage_summary(values, [key])["fields"][key]
                summaries[stage]["fields"][field] = dict(stats, input_field=key)
        diff["coverage"][source] = {
            "observed_rows": len(rows), "expected_rows": len(SYMBOLS),
            "denominator": len(raw), "rate": None, "comparison": "not_comparable",
            "stages": summaries,
        }
        realtime_stages[source] = {"status": "not_comparable", "trade_date": None,
                                   "reason": ("unit_contract_unknown" if "raw_payload" in capture else "raw_payload_not_captured") if source == "tencent" else "provider_time_and_units_unverified",
                                   "raw_payload": capture.get("raw_payload"),
                                   "adapter_timestamp_origin": "unknown_without_raw_payload" if source == "tencent" else "adapter_now_not_provider",
                                   **stage_rows}
    complete = all(item["complete"] for item in statuses)
    return {"status": "complete" if complete else "partial", "replay_completed": True,
            "capture_status": "complete" if complete else "partial",
            "contract_status": "issues_detected" if diff["issues"] else "not_comparable" if not all_raw else "retained",
            "statuses": statuses, "coverage": diff["coverage"], "code_provenance": code_provenance(),
            "capture_metadata": [{"file": item.get("_capture"),
                                  "evidence_level": item.get("evidence_level", "selected_sdk_rows" if item.get("source") == "tushare" else "adapted_only" if "tencent" in item.get("_capture", {}).get("path", "") else "no_response" if not item.get("rows") else "unknown"),
                                  "request": item.get("request", "unknown"),
                                  "response_metadata": item.get("response_metadata", "unknown"),
                                  "sdk_version": item.get("sdk_version", "unknown"),
                                  "elapsed_seconds": item.get("elapsed_seconds", "unknown")}
                                 for item in captures if "raw_rows" not in item],
            "stage_diff": {"rows": diff["rows"], "issues": diff["issues"], "realtime_stages": realtime_stages,
                           "research_rows": research_rows, "research_batches": research_batches}}


def code_provenance():
    root = Path(__file__).resolve().parents[1]
    paths = ["scripts/check_provider_field_contracts.py", "app/evaluation/provider_contract_check.py",
             "app/evaluation/quote_field_diagnostics.py", "app/evaluation/swing_dataset.py",
             "app/services/tushare_service.py", "app/services/tencent_service.py",
             "app/services/akshare_service.py", "app/services/data_source_manager.py", "app/services/coach_service.py"]
    versions = {"python": sys.version.split()[0]}
    for package in ("tushare", "akshare", "pandas", "requests"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "unavailable"
    return {"sha256": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}, "versions": versions}


def replay_probe(input_dir, output_dir):
    """Use the sole validated replay route; transport is never constructed."""
    return build_verified_replay(input_dir, output_dir, FIELD_MAP, analyze_captures)


def replay_tencent_contract(input_dir, output_dir, unit_assumption=None):
    """Compare the frozen raw response without replacing any production getter."""
    from app.services.tencent_service import TencentService
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("contract output already exists")
    captures = load_verified_capture(input_dir)
    selected = [capture for capture in captures if capture.get("source") == "tencent"
                or Path(capture["_capture"]["path"]).name == "tencent-batch.json"]
    if len(selected) != 1:
        raise ValueError("exactly one Tencent capture required")
    capture = selected[0]
    payload = capture.get("raw_payload")
    rows, seen = [], set()
    if payload is not None and not isinstance(payload, str):
        raise ValueError("raw payload must be a string")
    for line in (payload or "").split(";"):
        if not line.strip():
            continue
        match = re.fullmatch(r'v_((?:sz|sh|bj)([0-9]{6}))="([^"]*)"', line.strip())
        if not match:
            raise ValueError("invalid Tencent response envelope")
        symbol, raw = match.group(2), match.group(3)
        expected_market = "sh" if symbol.startswith("6") else "sz"
        if symbol not in PLAIN_SYMBOLS or not match.group(1).startswith(expected_market) or symbol in seen:
            raise ValueError("duplicate or unexpected Tencent identity")
        seen.add(symbol)
        strict = TencentService.parse_quote_contract(symbol, raw, unit_assumption=unit_assumption)
        legacy = None
        legacy_status = "not_replayed_missing_provider_time"
        if strict["source_time"] is not None:
            try:
                legacy = object.__new__(TencentService)._parse_quote_payload(symbol, raw)
                legacy_status = "ok" if legacy is not None else "unavailable"
            except (ValueError, IndexError, OverflowError):
                legacy_status = "parser_error"
        differences = {field: {"legacy": (legacy or {}).get(field), "research": value}
                       for field, value in strict["values"].items() if (legacy or {}).get(field) != value}
        rows.append({"symbol": symbol, "capture_ref": capture["_capture"], "strict": strict,
                     "legacy": legacy, "legacy_status": legacy_status, "differences": differences})
    result = {"schema_version": "tencent-contract-replay-v1", "transport": "none", "replay_completed": True,
              "production_enabled": False, "unit_contract_status": "unknown" if unit_assumption is None else "unverified_assumption",
              "source_status": capture.get("status", "unknown"), "expected_rows": len(PLAIN_SYMBOLS),
              "observed_rows": len(rows), "raw_payload_available": payload is not None,
              "rows": sorted(rows, key=lambda row: row["symbol"]), "code_provenance": code_provenance(),
              "input_manifest_sha256": hashlib.sha256((Path(input_dir) / "request-manifest.json").read_bytes()).hexdigest()}
    complete = capture.get("status") == "ok" and len(rows) == len(PLAIN_SYMBOLS) and all(
        row["strict"]["status"] == "complete_under_assumption" for row in rows)
    result["status"] = "complete" if complete else "partial"
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "tencent-contract.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("probe", "cache-only", "tencent-contract"), required=True)
    parser.add_argument("--unit-assumption", choices=("volume_lots_amount_yuan_v1",))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.unit_assumption and args.mode != "tencent-contract":
            raise ProbeError("unit assumption only supported in research contract replay")
        if args.mode == "probe":
            if not args.env_file:
                raise ProbeError("--env-file is required for probe")
            result = probe(args.env_file, args.output_dir)
        else:
            if not args.input_dir:
                raise ProbeError("--input-dir is required for cache-only")
            result = (replay_tencent_contract(args.input_dir, args.output_dir, args.unit_assumption)
                      if args.mode == "tencent-contract" else replay_probe(args.input_dir, args.output_dir))
    except (OSError, ProbeError, ValueError, FileExistsError) as exc:
        print(f"provider_contract_check_failed:{type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"provider_contract_check_status:{result['status']}")
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
