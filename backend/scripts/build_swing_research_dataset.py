#!/usr/bin/env python3
"""Bounded TuShare daily research acquisition, immutable cache and offline replay.

No application bootstrap, database, current universe, model or calendar service.
Archives hold decoded JSON (nonfinite numbers explicitly replaced by null), not
original HTTP bytes. Acquisition completeness is not historical PIT eligibility.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.evaluation.swing_dataset import compact_trade_date, join_daily_inputs
from app.evaluation.swing_protocol import validate_protocol


API_URL = "https://api.tushare.pro"
FIELDS = {
    "daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
    "daily_basic": "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,circ_mv",
    "adj_factor": "ts_code,trade_date,adj_factor",
}
JOIN_NAMES = {"daily": "daily", "daily_basic": "basics", "adj_factor": "factors"}
LIMITATIONS = [
    "historical_security_status_unavailable", "historical_input_availability_unknown",
    "no_intraday_inputs", "no_historical_names_ST_listing_retirement_or_price_limits",
    "empty_daily_does_not_prove_market_closed", "daily_rows_define_observed_historical_universe",
    "no_tradability_or_label_maturity_claim", "decoded_JSON_not_original_HTTP_bytes",
    "6000_row_boundary_blocks_without_verified_pagination",
]


class CollectionError(ValueError):
    """Controlled, credential-free failure reason."""


class ProviderError(Exception):
    def __init__(self, category, provider_code=None, http_status=None, payload=None):
        self.category = category
        self.provider_code = provider_code
        self.http_status = http_status
        self.payload = payload
        super().__init__(category)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def read_json(path):
    data = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        data = gzip.decompress(data)
    return json.loads(data)


def _write(path, value, immutable):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = encoded(value)
    if path.suffix == ".gz":
        data = gzip.compress(data, mtime=0)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if immutable:
            try:
                os.link(temporary, path)
            except FileExistsError:
                try:
                    same = encoded(read_json(path)) == encoded(value)
                except (ValueError, OSError, EOFError):
                    raise CollectionError("corrupt_cache") from None
                if not same:
                    raise CollectionError("immutable_content_conflict")
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_immutable(path, value):
    _write(path, value, immutable=True)


def calendar_dates(start, end):
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    while current <= last:
        yield current.strftime("%Y%m%d")
        current += timedelta(days=1)


def sanitize_nonfinite(value):
    count = 0
    def visit(item):
        nonlocal count
        if isinstance(item, float) and not math.isfinite(item):
            count += 1
            return None
        if isinstance(item, dict):
            return {key: visit(child) for key, child in item.items()}
        if isinstance(item, list):
            return [visit(child) for child in item]
        return item
    return visit(value), count


def _provider_category(message):
    lowered = str(message).lower()
    if any(word in lowered for word in ("token", "permission", "权限", "授权")):
        return "permission_denied"
    if any(word in lowered for word in ("quota", "limit", "频率", "每分钟", "每天", "积分", "次数")):
        return "quota_exceeded"
    return "provider_error"


def make_fetcher(env_file):
    # Lazy dependencies: replay does not import dotenv/requests or need a token.
    from dotenv import dotenv_values
    import requests
    token = dotenv_values(env_file).get("TUSHARE_TOKEN") if env_file else os.environ.get("TUSHARE_TOKEN")
    if not isinstance(token, str) or not token.strip():
        raise CollectionError("TUSHARE_TOKEN_required")

    def fetch(endpoint, parameters, fields, timeout):
        try:
            reply = requests.post(API_URL, json={"api_name": endpoint, "token": token,
                "params": parameters, "fields": fields}, timeout=timeout, allow_redirects=False)
        except requests.Timeout:
            raise TimeoutError() from None
        except requests.ConnectionError:
            raise ConnectionError() from None
        except requests.RequestException:
            raise ProviderError("transport_error") from None
        try:
            payload = reply.json()
        except ValueError:
            payload = {"non_json_body": reply.text}
        # Never persist a reflected token, including an unexpected success message.
        def redact(value):
            if isinstance(value, str):
                return re.sub(r"https?://[^\s\"<>]+", "[REDACTED_URL]", value.replace(token, "[REDACTED]"))
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                result = {}
                for key, item in value.items():
                    safe_key = redact(key)
                    if safe_key in result:
                        raise ProviderError("redaction_key_collision", http_status=reply.status_code,
                            payload={"response_omitted": True, "reason": "redaction_key_collision"})
                    result[safe_key] = redact(item)
                return result
            return value
        payload = redact(payload)
        if reply.status_code != 200:
            category = "permission_denied" if reply.status_code in (401, 403) else (
                "quota_exceeded" if reply.status_code == 429 else "http_error")
            raise ProviderError(category, http_status=reply.status_code, payload=payload)
        if isinstance(payload, dict) and "non_json_body" in payload:
            raise ProviderError("invalid_json", http_status=200, payload=payload)
        return payload
    return fetch


def _rows(archive):
    payload = archive["payload"]
    if not isinstance(payload, dict) or type(payload.get("code")) is not int:
        raise CollectionError("invalid_response_schema")
    if payload["code"] != 0:
        raise ProviderError(_provider_category(payload.get("msg")), provider_code=payload["code"])
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("fields"), list) or not isinstance(data.get("items"), list):
        raise CollectionError("invalid_response_schema")
    fields, items = data["fields"], data["items"]
    if any(type(field) is not str for field in fields) or len(set(fields)) != len(fields):
        raise CollectionError("invalid_response_fields")
    if set(fields) != set(archive["fields"].split(",")):
        raise CollectionError("invalid_response_fields")
    # A full boundary response is unresolved even if its rows happen to repeat.
    if len(items) >= 6000:
        raise CollectionError("possible_truncation")
    rows, seen = [], set()
    for item in items:
        if not isinstance(item, list) or len(item) != len(fields):
            raise CollectionError("invalid_response_row")
        row = dict(zip(fields, item))
        try:
            day = compact_trade_date(row["trade_date"])
        except ValueError:
            raise CollectionError("invalid_response_date") from None
        if day != archive["parameters"]["trade_date"]:
            raise CollectionError("wrong_date")
        symbol = row["ts_code"]
        if type(symbol) is not str or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", symbol):
            raise CollectionError("invalid_response_symbol")
        key = (symbol, day)
        if key in seen:
            raise CollectionError("duplicate_key")
        seen.add(key)
        rows.append(row)
    return rows


def _load_archive(path, identity_hash, endpoint, day):
    try:
        archive = read_json(path)
        checksum = archive.pop("archive_sha256")
        if digest(archive) != checksum:
            raise CollectionError("cache_checksum_mismatch")
        archive["archive_sha256"] = checksum
        if (archive["identity_sha256"] != identity_hash or archive["source"] != "tushare"
                or archive["endpoint"] != endpoint or archive["parameters"] != {"trade_date": day}
                or archive["fields"] != FIELDS[endpoint] or archive["api_url"] != API_URL):
            raise CollectionError("cache_contract_mismatch")
        if archive["payload_sha256"] != digest(archive["payload"]):
            raise CollectionError("cache_checksum_mismatch")
        return archive
    except CollectionError:
        raise
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        raise CollectionError("corrupt_cache") from None


def collect(protocol, output_dir, cache_dir=None, env_file=None, cache_only=False,
            label_end_date=None, max_new_requests=None, requests_per_minute=120,
            fetcher=None, sleep=time.sleep, monotonic=time.monotonic, progress=print,
            today=date.today):
    protocol = validate_protocol(protocol)
    if not 0 < requests_per_minute <= 120:
        raise ValueError("requests_per_minute must be in (0, 120]")
    if max_new_requests is not None and (type(max_new_requests) is not int or max_new_requests < 0):
        raise ValueError("max_new_requests must be a nonnegative integer")
    signal_start, signal_end = protocol["dates"]["research"]
    end = label_end_date or signal_end
    if date.fromisoformat(end).isoformat() != end or end < signal_end:
        raise ValueError("label_end_date must be ISO date at or after signal end")
    if date.fromisoformat(end) >= today():
        raise ValueError("label_end_date must precede the current calendar date")
    backend = Path(__file__).resolve().parents[1]
    source_hashes = {"collector": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "normalizer": hashlib.sha256((backend / "app/evaluation/swing_dataset.py").read_bytes()).hexdigest()}
    identity = {"schema_version": "swing-collector-v1", "protocol_sha256": protocol["protocol_sha256"],
        "implementation_sha256": source_hashes,
        "source": "tushare", "adjustment": "raw", "api_url": API_URL, "fields": FIELDS,
        "warmup_start": protocol["dates"]["warmup_start"], "signal_range": [signal_start, signal_end],
        "label_end_date": end, "response_cap": 6000, "pagination": "unverified_stop_at_cap",
        "availability_policy": "unknown_no_retrieval_time_substitution"}
    identity_hash = digest(identity)
    output_dir = Path(output_dir)
    cache_dir = Path(cache_dir) if cache_dir else output_dir / "cache"
    for root in (cache_dir, output_dir):
        write_immutable(root / "identity.json", identity)
    write_immutable(output_dir / "protocol.json", protocol)
    keys = list(calendar_dates(identity["warmup_start"], end))
    entries = {day: {"status": "missing_requests", "output": None, "dataset_sha256": None,
                     "coverage_sha256": None, "endpoints": {}} for day in keys}
    requests_made, last_request, stop_reason, blocked = 0, None, None, False
    errors = []

    def error_record(endpoint, day, category, **details):
        record = {"endpoint": endpoint, "parameters": {"trade_date": day}, "error": category,
                  "fetched_at": datetime.now(timezone.utc).isoformat(), **details}
        filename = "errors/" + uuid.uuid4().hex + ".json"
        write_immutable(cache_dir / filename, record)
        errors.append({key: value for key, value in record.items() if key != "response_archive"} | {
            "error_file": filename,
            "response_payload_sha256": details.get("response_archive", {}).get("payload_sha256")})

    def acquire(endpoint, day):
        nonlocal requests_made, last_request, fetcher, stop_reason
        path = cache_dir / "requests" / day / (endpoint + ".json.gz")
        if path.exists():
            return _load_archive(path, identity_hash, endpoint, day)
        if cache_only or stop_reason:
            return None
        for attempt in range(3):
            if max_new_requests is not None and requests_made >= max_new_requests:
                stop_reason = "request_budget"
                return None
            if fetcher is None:
                fetcher = make_fetcher(env_file)
            if last_request is not None:
                sleep(max(0, 60 / requests_per_minute - (monotonic() - last_request)))
            last_request = monotonic()
            requests_made += 1
            started = monotonic()
            fetched_at = datetime.now(timezone.utc).isoformat()
            def archive_response(payload, http_status=200):
                payload, nonfinite_count = sanitize_nonfinite(payload)
                archive = {"schema_version": "swing-raw-response-v1", "source": "tushare",
                    "identity_sha256": identity_hash, "endpoint": endpoint, "api_url": API_URL,
                    "parameters": {"trade_date": day}, "fields": FIELDS[endpoint],
                    "fetched_at": fetched_at, "elapsed_seconds": round(monotonic() - started, 6),
                    "http_status": http_status, "payload": payload, "payload_sha256": digest(payload),
                    "nonfinite_to_null_count": nonfinite_count,
                    "security_redaction": "transport_redacts_token_and_URL_strings",
                    "representation": "decoded_json_nonfinite_to_null_not_HTTP_bytes"}
                archive["archive_sha256"] = digest(archive)
                return archive
            try:
                payload = fetcher(endpoint, {"trade_date": day}, FIELDS[endpoint], 8)
                if isinstance(payload, dict) and payload.get("code", 0) != 0:
                    code = payload.get("code")
                    raise ProviderError(_provider_category(payload.get("msg")),
                        provider_code=code if type(code) is int else None, http_status=200, payload=payload)
                archive = archive_response(payload)
                write_immutable(path, archive)
                return archive
            except (TimeoutError, ConnectionError) as exc:
                category = "timeout" if isinstance(exc, TimeoutError) else "connection_error"
                error_record(endpoint, day, category, attempt=attempt + 1)
                if attempt == 2:
                    stop_reason = category
            except ProviderError as exc:
                error_record(endpoint, day, exc.category, provider_code=exc.provider_code,
                    http_status=exc.http_status, response_archive=archive_response(exc.payload, exc.http_status))
                stop_reason = exc.category
                return None
        return None

    for day in keys:
        entry, inputs = entries[day], {}
        try:
            for endpoint in FIELDS:
                archive = acquire(endpoint, day)
                if archive is None:
                    continue
                # Provenance is separate from normalized content fingerprints.
                entry["endpoints"][endpoint] = {key: archive[key] for key in
                    ("payload_sha256", "archive_sha256", "fetched_at", "elapsed_seconds", "http_status", "nonfinite_to_null_count")}
                entry["endpoints"][endpoint]["cache_file"] = f"requests/{day}/{endpoint}.json.gz"
                payload = archive["payload"]
                items = payload.get("data", {}).get("items") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else None
                entry["endpoints"][endpoint]["row_count"] = len(items) if isinstance(items, list) else None
                rows = _rows(archive)
                entry["endpoints"][endpoint].update(row_count=len(rows), status="ok" if rows else "empty")
                inputs[JOIN_NAMES[endpoint]] = rows
                if endpoint == "daily" and not rows:
                    inputs.update(basics=[], factors=[])
                    break
            if len(inputs) == 3:
                joined = join_daily_inputs(**inputs, metadata={"source": "tushare", "adjustment": "raw"})
                role = "warmup" if day < compact_trade_date(signal_start) else (
                    "label_only" if day > compact_trade_date(signal_end) else "signal")
                output = {"schema_version": "swing-dataset-date-v1", "trade_date": day, "role": role, **joined}
                filename = f"dates/{day}.json.gz"
                write_immutable(output_dir / filename, output)
                entry.update(status="observed_daily" if inputs["daily"] else "empty_daily_unknown",
                    output=filename, dataset_sha256=digest(output), coverage_sha256=digest(joined["coverage"]),
                    daily_rows=joined["coverage"]["daily_rows"], complete_rows=joined["coverage"]["complete_rows"])
                progress(f"date={day} status={entry['status']} rows={entry['daily_rows']} new_requests={requests_made}")
        except (CollectionError, ProviderError) as exc:
            stop_reason = exc.category if isinstance(exc, ProviderError) else str(exc)
            blocked = True
            entry["status"] = "blocked"
            if endpoint in entry["endpoints"]:
                entry["endpoints"][endpoint]["status"] = stop_reason
            error_record(endpoint, day, stop_reason)
            break
        if stop_reason:
            # Continue replaying already cached dates, but never start more requests.
            continue

    coverage_index = {day: {key: entry.get(key) for key in
        ("status", "coverage_sha256", "daily_rows", "complete_rows")} | {
            "endpoints": {endpoint: {key: item.get(key) for key in
                ("payload_sha256", "row_count", "status", "nonfinite_to_null_count")}
                for endpoint, item in entry["endpoints"].items()}} for day, entry in entries.items()}
    complete_dates = sum(item["output"] is not None for item in entries.values())
    coverage = {"expected_calendar_request_dates": len(keys), "processed_dates": complete_dates,
        "observed_daily_dates": sum(item["status"] == "observed_daily" for item in entries.values()),
        "empty_daily_unknown_dates": sum(item["status"] == "empty_daily_unknown" for item in entries.values()),
        "daily_rows": sum(item.get("daily_rows", 0) for item in entries.values()),
        "complete_rows": sum(item.get("complete_rows", 0) for item in entries.values())}
    manifest = {"schema_version": "swing-collection-manifest-v1", "identity": identity,
        "identity_sha256": identity_hash, "status": "blocked" if blocked else (
            "complete" if complete_dates == len(keys) else "incomplete"),
        "stop_reason": stop_reason or ("cache_missing_requests" if cache_only and complete_dates < len(keys) else None),
        "generated_at": datetime.now(timezone.utc).isoformat(), "new_requests": requests_made,
        "request_policy": {"requests_per_minute": requests_per_minute, "timeout_seconds": 8,
                           "max_transport_retries": 2, "max_new_requests": max_new_requests},
        "dataset_sha256": digest({"identity_sha256": identity_hash,
            "dates": {day: entry["dataset_sha256"] for day, entry in entries.items()}}),
        "coverage_sha256": digest({"identity_sha256": identity_hash, "dates": coverage_index}),
        "coverage": coverage, "dates": entries, "errors": errors, "limitations": LIMITATIONS}
    _write(output_dir / "manifest.json", manifest, immutable=False)
    progress(f"status={manifest['status']} new_requests={requests_made} processed_dates={complete_dates}/{len(keys)} stop_reason={manifest['stop_reason']}")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--label-end-date")
    parser.add_argument("--max-new-requests", "--request-limit", type=int, dest="max_new_requests")
    parser.add_argument("--requests-per-minute", type=int, default=120)
    args = parser.parse_args(argv)
    try:
        result = collect(**{**vars(args), "protocol": read_json(args.protocol)})
    except (ValueError, OSError):
        print("collector_failed: invalid configuration, identity conflict or unreadable file", file=sys.stderr)
        return 1
    return {"complete": 0, "incomplete": 2, "blocked": 1}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
