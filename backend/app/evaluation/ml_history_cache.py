from __future__ import annotations

import hashlib
import importlib.util
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


class MLHistoryCache:
    """Resume-friendly explicit range history cache for offline ML training."""

    def __init__(
        self,
        source: Any,
        cache_root: str | Path,
        retry_count: int = 2,
        sleep_seconds: float = 1.5,
        inter_request_sleep_seconds: float = 0.0,
        circuit_sleep_seconds: float = 65.0,
        sleep_func=time.sleep,
        prefer_parquet: bool | None = None,
    ):
        self.source = source
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.retry_count = max(0, int(retry_count or 0))
        self.sleep_seconds = max(0.0, float(sleep_seconds or 0.0))
        self.inter_request_sleep_seconds = max(0.0, float(inter_request_sleep_seconds or 0.0))
        self.circuit_sleep_seconds = max(0.0, float(circuit_sleep_seconds or 0.0))
        self.sleep_func = sleep_func
        self._request_lock = threading.Lock()
        self._last_remote_request_at = 0.0
        if prefer_parquet is None:
            prefer_parquet = importlib.util.find_spec("pyarrow") is not None
        self.format = "parquet" if prefer_parquet else "csv"
        self._manifest: Dict[str, Any] = {
            "format": self.format,
            "cache_root": str(self.cache_root),
            "cache_hits": 0,
            "cache_misses": 0,
            "fetched_symbols": [],
            "failed_symbols": [],
        }

    def get_history_data_range(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        normalized_symbol = _normalize_symbol(symbol)
        normalized_start = _normalize_date(start_date)
        normalized_end = _normalize_date(end_date)
        if not normalized_symbol or not normalized_start or not normalized_end or normalized_start > normalized_end:
            return pd.DataFrame()

        path = self._cache_path(normalized_symbol, normalized_start, normalized_end)
        if path.exists():
            self._manifest["cache_hits"] += 1
            return _slice_history(self._read(path), normalized_start, normalized_end)

        self._manifest["cache_misses"] += 1
        history = self._fetch_with_retries(normalized_symbol, normalized_start, normalized_end)
        history = _slice_history(history, normalized_start, normalized_end)
        if history.empty:
            self._record_failed(normalized_symbol, "empty_history")
            self._write_manifest()
            return history

        self._write(path, history)
        self._manifest["fetched_symbols"].append(normalized_symbol)
        self._write_manifest()
        return history

    def fetch_many(self, symbols: List[str], start_date: str, end_date: str, workers: int = 2) -> Dict[str, Any]:
        valid_symbols: List[str] = []
        failed_symbols: List[str] = []
        max_workers = max(1, int(workers or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self.get_history_data_range, symbol, start_date, end_date): symbol
                for symbol in symbols
            }
            for future in as_completed(future_map):
                symbol = _normalize_symbol(future_map[future])
                try:
                    frame = future.result()
                except Exception as exc:
                    self._record_failed(symbol, str(exc)[:160])
                    failed_symbols.append(symbol)
                    continue
                if frame is None or frame.empty:
                    failed_symbols.append(symbol)
                else:
                    valid_symbols.append(symbol)
        self._write_manifest()
        return {
            "valid_symbols": _ordered_unique(valid_symbols, symbols),
            "failed_symbols": _ordered_unique(failed_symbols, symbols),
            "manifest": self.manifest(),
        }

    def manifest(self) -> Dict[str, Any]:
        return {
            **self._manifest,
            "failed_symbols": list(self._manifest.get("failed_symbols") or []),
            "fetched_symbols": list(self._manifest.get("fetched_symbols") or []),
        }

    def _fetch_with_retries(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        attempts = self.retry_count + 1
        last_error = None
        for attempt in range(attempts):
            try:
                self._wait_before_remote_fetch()
                history = self.source.get_history_data_range(symbol, start_date=start_date, end_date=end_date)
                normalized = _normalize_history(history)
                if not normalized.empty:
                    return normalized
                last_error = "empty_history"
            except Exception as exc:
                last_error = exc
            if attempt < attempts - 1 and self.sleep_seconds:
                self.sleep_func(self.sleep_seconds)
        self._record_failed(symbol, str(last_error)[:160] if last_error else "unknown_error")
        return pd.DataFrame()

    def _wait_before_remote_fetch(self) -> None:
        with self._request_lock:
            circuit_wait = self._history_circuit_wait_seconds()
            if circuit_wait > 0:
                self.sleep_func(circuit_wait)
            if self.inter_request_sleep_seconds > 0:
                elapsed = time.time() - self._last_remote_request_at
                wait_seconds = self.inter_request_sleep_seconds - elapsed
                if wait_seconds > 0:
                    self.sleep_func(wait_seconds)
            self._last_remote_request_at = time.time()

    def _history_circuit_wait_seconds(self) -> float:
        if self.circuit_sleep_seconds <= 0:
            return 0.0
        state = getattr(self.source, "_breaker_state", {}) or {}
        now = time.time()
        waits = []
        for key, value in state.items():
            if not str(key).endswith(":history"):
                continue
            remaining = float((value or {}).get("open_until") or 0) - now
            if remaining > 0:
                waits.append(min(self.circuit_sleep_seconds, remaining + 0.5))
        return max(waits) if waits else 0.0

    def _cache_path(self, symbol: str, start_date: str, end_date: str) -> Path:
        key = hashlib.sha256(f"{symbol}:{start_date}:{end_date}".encode("utf-8")).hexdigest()[:16]
        suffix = "parquet" if self.format == "parquet" else "csv"
        return self.cache_root / f"{symbol}_{start_date}_{end_date}_{key}.{suffix}"

    def _read(self, path: Path) -> pd.DataFrame:
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)

    def _write(self, path: Path, frame: pd.DataFrame) -> None:
        if self.format == "parquet":
            try:
                frame.to_parquet(path, index=False)
                return
            except Exception as exc:
                self.format = "csv"
                self._manifest["format"] = "csv"
                self._manifest["parquet_error"] = str(exc)[:160]
                path = path.with_suffix(".csv")
        frame.to_csv(path, index=False)

    def _record_failed(self, symbol: str, reason: str) -> None:
        failures = self._manifest.setdefault("failed_symbols", [])
        if not any(item.get("symbol") == symbol for item in failures):
            failures.append({"symbol": symbol, "reason": reason})

    def _write_manifest(self) -> None:
        path = self.cache_root / "history_cache_manifest.json"
        path.write_text(json.dumps(self.manifest(), ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_history(history: Any) -> pd.DataFrame:
    if history is None:
        return pd.DataFrame()
    frame = history.copy() if hasattr(history, "copy") else pd.DataFrame(history)
    if frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame = frame[frame["date"].notna()].copy()
    return frame.sort_values("date").reset_index(drop=True)


def _slice_history(history: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    frame = _normalize_history(history)
    if frame.empty:
        return frame
    return frame[(frame["date"] >= start_date) & (frame["date"] <= end_date)].reset_index(drop=True)


def _normalize_symbol(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".")[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits if len(digits) == 6 else ""


def _normalize_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()


def _ordered_unique(values: List[str], preferred_order: List[str]) -> List[str]:
    remaining = set(str(item) for item in values)
    ordered = []
    for symbol in preferred_order:
        normalized = _normalize_symbol(symbol)
        if normalized in remaining:
            ordered.append(normalized)
            remaining.remove(normalized)
    for symbol in values:
        normalized = _normalize_symbol(symbol)
        if normalized in remaining:
            ordered.append(normalized)
            remaining.remove(normalized)
    return ordered
