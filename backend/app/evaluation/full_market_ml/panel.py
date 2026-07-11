"""Historically correct, symbol-sharded panel construction for offline ML."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import FullMarketMLConfig
from .manifests import CollectionManifest, load_manifest


SHARD_COUNT = 64
_STATIC_ENDPOINTS = {"stock_basic", "namechange", "index_classify", "index_member_all"}


@dataclass(frozen=True)
class PanelBuildResult:
    stage: str
    row_count: int
    shard_paths: tuple[Path, ...]
    industry_relative_enabled: bool


def build_full_market_panel(config: FullMarketMLConfig, runtime_root: str | Path, stage: str) -> PanelBuildResult:
    """Build an immutable panel without materialising the full market in memory."""
    root = Path(runtime_root)
    manifest = load_manifest(root, stage, config.sha256, config.collection.request_pacing_seconds)
    if not manifest.ready:
        raise ValueError("collection manifest is not ready for panel construction")

    output = root / "panel" / f"stage={stage}"
    if output.exists():
        raise ValueError("panel stage already exists; use a new immutable stage identifier")
    temporary = Path(tempfile.mkdtemp(prefix=f".panel-{stage}-", dir=output.parent if output.parent.exists() else root))
    try:
        static = _load_static_frames(root, manifest)
        trade_dates = _open_trade_dates(root, manifest)
        if not trade_dates:
            raise ValueError("no open trade dates available for panel construction")
        for trade_date in trade_dates:
            frames = dict(static)
            frames.update(_load_daily_frames(root, manifest, trade_date))
            if frames.get("daily", pd.DataFrame()).empty:
                continue
            base = _build_base_panel(frames, industry_relative_enabled=manifest.industry_relative_enabled)
            if base.empty:
                continue
            _write_intermediate_shards(base, temporary, trade_date)

        shard_paths, row_count = _finalize_shards(temporary, output, manifest.industry_relative_enabled)
        return PanelBuildResult(stage, row_count, tuple(shard_paths), manifest.industry_relative_enabled)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def build_historical_universe(stock_basic: pd.DataFrame, trade_dates: Iterable[str]) -> pd.DataFrame:
    """Expand listing/delisting intervals; never infer history from current status."""
    basic = stock_basic.copy()
    if basic.empty:
        return pd.DataFrame(columns=["trade_date", "symbol"])
    basic["symbol"] = _symbols(basic)
    basic["list_date"] = basic.get("list_date", pd.Series("", index=basic.index)).map(_date_text)
    basic["delist_date"] = basic.get("delist_date", pd.Series("", index=basic.index)).map(_date_text)
    rows = []
    for trade_date in sorted({_date_text(value) for value in trade_dates}):
        included = basic[(basic["list_date"] <= trade_date) & ((basic["delist_date"] == "") | (basic["delist_date"] >= trade_date))]
        rows.extend({"trade_date": trade_date, "symbol": symbol} for symbol in included["symbol"].tolist())
    return pd.DataFrame(rows, columns=["trade_date", "symbol"])


def build_panel_from_frames(
    frames: Mapping[str, pd.DataFrame], *, industry_relative_enabled: bool = True
) -> pd.DataFrame:
    """In-memory test helper with the same historical transformations as production."""
    return _finalize_symbol_panel(_build_base_panel(frames, industry_relative_enabled=industry_relative_enabled))


def _build_base_panel(frames: Mapping[str, pd.DataFrame], *, industry_relative_enabled: bool) -> pd.DataFrame:
    daily = _deduplicate_market_rows(_frame(frames, "daily"), "daily")
    if daily.empty:
        return pd.DataFrame()
    daily["symbol"] = _symbols(daily)
    daily["trade_date"] = daily["trade_date"].map(_date_text)
    historical_universe = build_historical_universe(_frame(frames, "stock_basic"), daily["trade_date"].unique())
    daily = daily.merge(historical_universe, on=["symbol", "trade_date"], how="inner")
    if daily.empty:
        return pd.DataFrame()
    adjustments = _deduplicate_market_rows(_frame(frames, "adj_factor"), "adj_factor")
    if not adjustments.empty:
        adjustments["symbol"] = _symbols(adjustments)
        adjustments["trade_date"] = adjustments["trade_date"].map(_date_text)
        adjustments = adjustments[["symbol", "trade_date", "adj_factor"]]
    panel = daily.merge(adjustments, on=["symbol", "trade_date"], how="left")
    panel["adj_factor"] = pd.to_numeric(panel["adj_factor"], errors="coerce")
    for raw_name, adjusted_name in (("open", "adjusted_open"), ("high", "adjusted_high"), ("low", "adjusted_low"), ("close", "adjusted_close")):
        panel[raw_name] = pd.to_numeric(panel.get(raw_name), errors="coerce")
        panel[adjusted_name] = panel[raw_name] * panel["adj_factor"]
    panel["volume_shares"] = pd.to_numeric(panel.get("vol"), errors="coerce") * 100.0
    panel["amount_cny"] = pd.to_numeric(panel.get("amount"), errors="coerce") * 1000.0
    panel["is_suspended"] = _suspension_flags(panel, _frame(frames, "suspend_d"), _frame(frames, "trade_cal"))
    panel["is_st"] = _st_flags(panel, _frame(frames, "namechange"))
    panel["industry_l1"] = _industry_values(panel, frames, industry_relative_enabled)
    panel["industry_relative_enabled"] = bool(industry_relative_enabled)
    panel["listing_age_trade_days"] = _listing_ages(panel, _frame(frames, "stock_basic"), _frame(frames, "trade_cal"))
    panel["valid_ohlc"] = (
        panel[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & panel["high"].ge(panel["low"])
        & panel["high"].ge(panel[["open", "close"]].max(axis=1))
        & panel["low"].le(panel[["open", "close"]].min(axis=1))
    )
    limits = _frame(frames, "stk_limit")
    panel["at_up_limit"] = _up_limit_flags(panel, limits)
    panel["next_open_date"] = _next_open_dates(panel, _frame(frames, "trade_cal"))
    return panel.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _finalize_symbol_panel(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return panel
    panel = panel.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True).copy()
    grouped = panel.groupby("symbol", sort=False)
    panel["median_amount_20d"] = grouped["amount_cny"].transform(lambda values: values.rolling(20, min_periods=20).median())
    next_session = panel[["symbol", "trade_date", "adjusted_open", "valid_ohlc", "is_suspended", "at_up_limit"]].rename(
        columns={
            "trade_date": "next_open_date",
            "adjusted_open": "next_adjusted_open",
            "valid_ohlc": "next_valid_ohlc",
            "is_suspended": "next_is_suspended",
            "at_up_limit": "next_at_up_limit",
        }
    )
    panel = panel.merge(next_session, on=["symbol", "next_open_date"], how="left", validate="many_to_one")
    next_valid = panel["next_valid_ohlc"].eq(True)
    next_suspended = panel["next_is_suspended"].eq(True) | panel["next_is_suspended"].isna()
    next_at_up_limit = panel["next_at_up_limit"].eq(True) | panel["next_at_up_limit"].isna()
    panel["entry_tradeable"] = next_valid & ~next_suspended & ~next_at_up_limit & panel["next_adjusted_open"].notna()
    panel["eligible_signal_day"] = (
        panel["listing_age_trade_days"].ge(20)
        & ~panel["is_st"]
        & ~panel["is_suspended"]
        & panel["valid_ohlc"]
        & panel["median_amount_20d"].gt(0)
    )
    return panel


def _deduplicate_market_rows(frame: pd.DataFrame, endpoint: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    result["symbol"] = _symbols(result)
    result["trade_date"] = result["trade_date"].map(_date_text)
    retained = []
    for _, rows in result.groupby(["trade_date", "symbol"], sort=False, dropna=False):
        signatures = {_row_signature(row) for _, row in rows.iterrows()}
        if len(signatures) > 1:
            raise ValueError(f"conflicting duplicate {endpoint} rows for trade_date,symbol")
        retained.append(rows.iloc[-1])
    return pd.DataFrame(retained).drop(columns=["symbol"], errors="ignore")


def _row_signature(row: pd.Series) -> str:
    payload = {key: _json_scalar(value) for key, value in row.items() if key not in {"_source_order", "source_row_id"}}
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_scalar(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return str(value) if not isinstance(value, (str, int, float, bool)) else value


def _frame(frames: Mapping[str, pd.DataFrame], name: str) -> pd.DataFrame:
    value = frames.get(name)
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _symbols(frame: pd.DataFrame) -> pd.Series:
    source = frame["symbol"] if "symbol" in frame else frame.get("ts_code", pd.Series(index=frame.index, dtype=str))
    return source.astype(str).str.split(".", regex=False).str[0].str.zfill(6)


def _date_text(value) -> str:
    if pd.isna(value) or value is None:
        return ""
    text = str(value).replace("-", "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 else text


def _suspension_flags(panel: pd.DataFrame, suspended: pd.DataFrame, trade_cal: pd.DataFrame) -> pd.Series:
    if suspended.empty:
        return pd.Series(False, index=panel.index)
    suspended = suspended.copy()
    suspended["symbol"] = _symbols(suspended)
    if "trade_date" in suspended:
        suspended["trade_date"] = suspended["trade_date"].map(_date_text)
        suspended_keys = set(zip(suspended["symbol"], suspended["trade_date"]))
        return pd.Series([(symbol, trade_date) in suspended_keys for symbol, trade_date in zip(panel.symbol, panel.trade_date)], index=panel.index)

    available_dates = set(_open_dates(trade_cal) or sorted(panel["trade_date"].unique()))
    intervals = {}
    for symbol, suspend_date, resume_date in zip(
        suspended["symbol"],
        suspended.get("suspend_date", pd.Series("", index=suspended.index)).map(_date_text),
        suspended.get("resume_date", pd.Series("", index=suspended.index)).map(_date_text),
    ):
        if suspend_date:
            intervals.setdefault(symbol, []).append((suspend_date, resume_date))
    return pd.Series(
        [
            trade_date in available_dates
            and any(start <= trade_date and (not resume_date or trade_date < resume_date) for start, resume_date in intervals.get(symbol, []))
            for symbol, trade_date in zip(panel.symbol, panel.trade_date)
        ],
        index=panel.index,
    )


def _next_open_dates(panel: pd.DataFrame, trade_cal: pd.DataFrame) -> pd.Series:
    dates = _open_dates(trade_cal)
    successor = dict(zip(dates, dates[1:]))
    return panel["trade_date"].map(successor)


def _open_dates(trade_cal: pd.DataFrame) -> list[str]:
    if trade_cal.empty or "cal_date" not in trade_cal or "is_open" not in trade_cal:
        return []
    return sorted({_date_text(value) for value in trade_cal.loc[trade_cal["is_open"].astype(str) == "1", "cal_date"]})


def _st_flags(panel: pd.DataFrame, namechange: pd.DataFrame) -> pd.Series:
    if namechange.empty:
        return pd.Series(False, index=panel.index)
    intervals = namechange.copy()
    intervals["symbol"] = _symbols(intervals)
    name_column = "name" if "name" in intervals else "namechange"
    intervals = intervals[intervals[name_column].fillna("").astype(str).str.upper().str.contains("ST", regex=False)]
    starts = intervals.get("start_date", pd.Series("", index=intervals.index)).map(_date_text)
    ends = intervals.get("end_date", pd.Series("", index=intervals.index)).map(_date_text)
    by_symbol = {}
    for symbol, start, end in zip(intervals.symbol, starts, ends):
        by_symbol.setdefault(symbol, []).append((start, end))
    return pd.Series(
        [any(start <= trade_date and (not end or trade_date <= end) for start, end in by_symbol.get(symbol, [])) for symbol, trade_date in zip(panel.symbol, panel.trade_date)],
        index=panel.index,
    )


def _industry_values(panel: pd.DataFrame, frames: Mapping[str, pd.DataFrame], enabled: bool) -> pd.Series:
    if not enabled:
        return pd.Series(pd.NA, index=panel.index, dtype="object")
    classifications = _frame(frames, "index_classify")
    members = _frame(frames, "index_member_all")
    if classifications.empty or members.empty:
        return pd.Series(pd.NA, index=panel.index, dtype="object")
    name_by_code = dict(zip(classifications.get("index_code", []), classifications.get("industry_name", [])))
    members["symbol"] = _symbols(members.rename(columns={"con_code": "ts_code"}) if "con_code" in members else members)
    starts = members.get("in_date", pd.Series("", index=members.index)).map(_date_text)
    ends = members.get("out_date", pd.Series("", index=members.index)).map(_date_text)
    intervals = {}
    for symbol, code, start, end in zip(members.symbol, members.get("l1_code", pd.Series("", index=members.index)), starts, ends):
        intervals.setdefault(symbol, []).append((start, end, name_by_code.get(code)))
    return pd.Series(
        [next((name for start, end, name in intervals.get(symbol, []) if start <= trade_date and (not end or trade_date <= end)), pd.NA) for symbol, trade_date in zip(panel.symbol, panel.trade_date)],
        index=panel.index,
        dtype="object",
    )


def _listing_ages(panel: pd.DataFrame, stock_basic: pd.DataFrame, trade_cal: pd.DataFrame) -> pd.Series:
    if stock_basic.empty or trade_cal.empty:
        return pd.Series(0, index=panel.index, dtype="int64")
    basics = stock_basic.copy()
    basics["symbol"] = _symbols(basics)
    list_dates = dict(zip(basics.symbol, basics.get("list_date", pd.Series("", index=basics.index)).map(_date_text)))
    open_dates = sorted({_date_text(value) for value in trade_cal.loc[trade_cal.get("is_open", 0).astype(str) == "1", "cal_date"]})
    age_by_symbol = {}
    for symbol, list_date in list_dates.items():
        age = 0
        values = {}
        for trade_date in open_dates:
            if list_date and trade_date >= list_date:
                age += 1
            values[trade_date] = age
        age_by_symbol[symbol] = values
    return pd.Series([age_by_symbol.get(symbol, {}).get(trade_date, 0) for symbol, trade_date in zip(panel.symbol, panel.trade_date)], index=panel.index)


def _up_limit_flags(panel: pd.DataFrame, limits: pd.DataFrame) -> pd.Series:
    if limits.empty or "up_limit" not in limits:
        return pd.Series(False, index=panel.index)
    limits = limits.copy()
    limits["symbol"] = _symbols(limits)
    limits["trade_date"] = limits["trade_date"].map(_date_text)
    values = {(symbol, trade_date): up for symbol, trade_date, up in zip(limits.symbol, limits.trade_date, pd.to_numeric(limits.up_limit, errors="coerce"))}
    return pd.Series([pd.notna(values.get((symbol, trade_date))) and opening >= values[(symbol, trade_date)] for symbol, trade_date, opening in zip(panel.symbol, panel.trade_date, panel.open)], index=panel.index)


def _load_static_frames(root: Path, manifest: CollectionManifest) -> dict[str, pd.DataFrame]:
    frames = {endpoint: _read_partitions(root, [record for record in manifest.partitions if record.endpoint == endpoint]) for endpoint in _STATIC_ENDPOINTS}
    frames["trade_cal"] = _read_partitions(root, [record for record in manifest.partitions if record.endpoint == "trade_cal"])
    frames["suspend_d"] = _read_partitions(root, [record for record in manifest.partitions if record.endpoint == "suspend_d"])
    return frames


def _load_daily_frames(root: Path, manifest: CollectionManifest, trade_date: str) -> dict[str, pd.DataFrame]:
    compact = trade_date.replace("-", "")
    endpoints = {"daily", "adj_factor", "stk_limit"}
    return {
        endpoint: _read_partitions(root, [record for record in manifest.partitions if record.endpoint == endpoint and record.key == compact])
        for endpoint in endpoints
    }


def _open_trade_dates(root: Path, manifest: CollectionManifest) -> list[str]:
    calendar = _read_partitions(root, [record for record in manifest.partitions if record.endpoint == "trade_cal"])
    return _open_dates(calendar)


def _read_partitions(root: Path, records) -> pd.DataFrame:
    frames = [pq.ParquetFile(root / record.path).read().to_pandas() for record in records if record.status != "failed" and (root / record.path).is_file()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write_intermediate_shards(panel: pd.DataFrame, temporary: Path, trade_date: str) -> None:
    for shard in range(SHARD_COUNT):
        rows = panel[panel.symbol.map(_shard_for_symbol) == shard]
        if rows.empty:
            continue
        path = temporary / f"shard={shard:02d}" / f"trade_date={trade_date}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(rows, preserve_index=False), path)


def _finalize_shards(temporary: Path, output: Path, industry_relative_enabled: bool) -> tuple[list[Path], int]:
    staging = output.parent / f".{output.name}.tmp"
    if staging.exists():
        shutil.rmtree(staging)
    paths = []
    row_count = 0
    try:
        for shard in range(SHARD_COUNT):
            source_paths = sorted((temporary / f"shard={shard:02d}").glob("trade_date=*/data.parquet"))
            frame = pd.concat([pq.ParquetFile(path).read().to_pandas() for path in source_paths], ignore_index=True) if source_paths else pd.DataFrame()
            finalized = _finalize_symbol_panel(frame)
            if not industry_relative_enabled and not finalized.empty:
                finalized["industry_l1"] = pd.NA
                finalized["industry_relative_enabled"] = False
            path = staging / f"shard={shard:02d}" / "data.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(finalized, preserve_index=False), path)
            paths.append(output / f"shard={shard:02d}" / "data.parquet")
            row_count += len(finalized)
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, output)
        return paths, row_count
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _shard_for_symbol(symbol: str) -> int:
    return int.from_bytes(hashlib.sha256(symbol.encode("ascii")).digest()[:8], "big") % SHARD_COUNT
