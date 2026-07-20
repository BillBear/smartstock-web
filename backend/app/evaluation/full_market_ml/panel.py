"""Historically correct, symbol-sharded panel construction for offline ML."""
from __future__ import annotations

from bisect import bisect_left
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
from .fundamental_features import build_point_in_time_fundamental_features
from .manifests import CollectionManifest, load_manifest, validate_partition


SHARD_COUNT = 64
_STATIC_ENDPOINTS = {"stock_basic", "namechange", "index_classify", "index_member_all"}
_STOCK_CODE_ENDPOINTS = {
    "daily",
    "daily_basic",
    "adj_factor",
    "stk_limit",
    "moneyflow",
    "stock_basic",
    "namechange",
    "suspend_d",
    "index_member_all",
}
ALLOWED_FEATURE_COLUMNS = (
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "volume_shares",
    "amount_cny",
    "is_suspended",
    "is_st",
    "industry_l1",
    "industry_relative_enabled",
    "listing_age_trade_days",
    "valid_ohlc",
    "at_up_limit",
    "at_down_limit",
    "median_amount_20d",
    "turnover_rate",
    "volume_ratio",
    "total_mv",
    "circ_mv",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "net_mf_amount",
    "net_mf_vol",
    "buy_sm_amount",
    "sell_sm_amount",
    "buy_md_amount",
    "sell_md_amount",
    "buy_lg_amount",
    "sell_lg_amount",
    "buy_elg_amount",
    "sell_elg_amount",
    "market_index_close",
    "market_index_amount",
)
FUTURE_EXECUTION_COLUMNS = (
    "next_open_date",
    "next_adjusted_open",
    "next_valid_ohlc",
    "next_is_suspended",
    "next_at_up_limit_open",
    "entry_tradeable",
)


@dataclass(frozen=True)
class PanelBuildResult:
    stage: str
    row_count: int
    shard_paths: tuple[Path, ...]
    industry_relative_enabled: bool
    feature_contract_path: Path


@dataclass(frozen=True)
class _CalendarLookup:
    open_dates: tuple[str, ...]
    rank_by_date: dict[str, int]


def augment_panel_with_point_in_time_fundamentals(
    panel: pd.DataFrame,
    fina_indicator: pd.DataFrame,
    forecast: pd.DataFrame | None = None,
    express: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add announcement-safe research features without mutating the base panel contract."""
    return build_point_in_time_fundamental_features(panel, fina_indicator, forecast, express)


def build_full_market_panel(config: FullMarketMLConfig, runtime_root: str | Path, stage: str) -> PanelBuildResult:
    """Build an immutable panel without materialising the full market in memory."""
    root = Path(runtime_root)
    manifest = load_manifest(root, stage, config.sha256, config.collection.request_pacing_seconds)
    if not manifest.ready:
        raise ValueError("collection manifest is not ready for panel construction")
    _validate_ready_manifest_partitions(root, manifest)

    output = root / "panel" / f"stage={stage}"
    if output.exists():
        raise ValueError("panel stage already exists; use a new immutable stage identifier")
    temporary = Path(tempfile.mkdtemp(prefix=f".panel-{stage}-", dir=output.parent if output.parent.exists() else root))
    try:
        static = _load_static_frames(root, manifest)
        trade_dates = _open_trade_dates(root, manifest)
        if not trade_dates:
            raise ValueError("no open trade dates available for panel construction")
        calendar_lookup = _build_calendar_lookup(static["trade_cal"])
        for trade_date in trade_dates:
            frames = dict(static)
            frames.update(_load_daily_frames(root, manifest, trade_date))
            if frames.get("daily", pd.DataFrame()).empty:
                continue
            base = _build_base_panel(
                frames,
                industry_relative_enabled=manifest.industry_relative_enabled,
                calendar_lookup=calendar_lookup,
            )
            if base.empty:
                continue
            _write_intermediate_shards(base, temporary, trade_date)

        shard_paths, row_count, feature_contract_path = _finalize_shards(temporary, output, manifest.industry_relative_enabled)
        return PanelBuildResult(stage, row_count, tuple(shard_paths), manifest.industry_relative_enabled, feature_contract_path)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def build_historical_universe(stock_basic: pd.DataFrame, trade_dates: Iterable[str]) -> pd.DataFrame:
    """Expand listing/delisting intervals; never infer history from current status."""
    basic = stock_basic.copy()
    if basic.empty:
        return pd.DataFrame(columns=["trade_date", "symbol"])
    if "list_status" in basic.columns:
        delisted = basic["list_status"].astype(str).str.upper().eq("D")
        missing_delist_date = "delist_date" not in basic.columns
        empty_delist_date = (
            pd.Series(False, index=basic.index)
            if missing_delist_date
            else basic["delist_date"].fillna("").astype(str).str.strip().eq("")
        )
        if bool(delisted.any()) and (missing_delist_date or bool((delisted & empty_delist_date).any())):
            raise ValueError("delisted stock rows require delist_date for historical universe reconstruction")
    basic["symbol"] = _symbols(basic)
    basic["list_date"] = basic.get("list_date", pd.Series("", index=basic.index)).map(_date_text)
    basic["delist_date"] = basic.get("delist_date", pd.Series("", index=basic.index)).map(_date_text)
    rows = []
    for trade_date in sorted({_date_text(value) for value in trade_dates}):
        included = basic[(basic["list_date"] <= trade_date) & ((basic["delist_date"] == "") | (basic["delist_date"] >= trade_date))]
        rows.extend({"trade_date": trade_date, "symbol": symbol} for symbol in included["symbol"].tolist())
    return pd.DataFrame(rows, columns=["trade_date", "symbol"])


def _validate_ready_manifest_partitions(root: Path, manifest: CollectionManifest) -> None:
    for record in manifest.partitions:
        if record.status != "failed":
            validate_partition(root, record)


def build_panel_from_frames(
    frames: Mapping[str, pd.DataFrame], *, industry_relative_enabled: bool = True,
    allowed_exchanges: Iterable[str] | None = None,
) -> pd.DataFrame:
    """In-memory test helper with the same historical transformations as production."""
    return _finalize_symbol_panel(
        _build_base_panel(
            frames,
            industry_relative_enabled=industry_relative_enabled,
            allowed_exchanges=allowed_exchanges,
        )
    )


def _build_base_panel(
    frames: Mapping[str, pd.DataFrame], *, industry_relative_enabled: bool,
    calendar_lookup: _CalendarLookup | None = None,
    allowed_exchanges: Iterable[str] | None = None,
) -> pd.DataFrame:
    frames = filter_frames_to_exchanges(frames, allowed_exchanges)
    daily = _deduplicate_market_rows(_frame(frames, "daily"), "daily")
    if daily.empty:
        return pd.DataFrame()
    daily["symbol"] = _symbols(daily)
    daily["trade_date"] = daily["trade_date"].map(_date_text)
    historical_universe = build_historical_universe(_frame(frames, "stock_basic"), daily["trade_date"].unique())
    daily = daily.merge(historical_universe, on=["symbol", "trade_date"], how="inner")
    if daily.empty:
        return pd.DataFrame()
    daily = _join_daily_endpoint_fields(
        daily,
        _frame(frames, "daily_basic"),
        "daily_basic",
        ("turnover_rate", "volume_ratio", "total_mv", "circ_mv", "pe", "pe_ttm", "pb", "ps"),
    )
    daily = _join_daily_endpoint_fields(
        daily,
        _frame(frames, "moneyflow"),
        "moneyflow",
        (
            "net_mf_amount", "net_mf_vol", "buy_sm_amount", "sell_sm_amount",
            "buy_md_amount", "sell_md_amount", "buy_lg_amount", "sell_lg_amount",
            "buy_elg_amount", "sell_elg_amount",
        ),
    )
    daily = _join_market_context_fields(daily, _frame(frames, "index_daily"))
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
    panel["listing_age_trade_days"] = _listing_ages(
        panel,
        _frame(frames, "stock_basic"),
        calendar_lookup or _build_calendar_lookup(_frame(frames, "trade_cal")),
    )
    panel["valid_ohlc"] = (
        panel[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & panel["high"].ge(panel["low"])
        & panel["high"].ge(panel[["open", "close"]].max(axis=1))
        & panel["low"].le(panel[["open", "close"]].min(axis=1))
        & panel["adj_factor"].gt(0)
    )
    limits = _deduplicate_market_rows(_frame(frames, "stk_limit"), "stk_limit")
    panel["at_up_limit"], panel["at_down_limit"], panel["at_up_limit_open"] = _limit_flags(panel, limits)
    panel["next_open_date"] = _next_open_dates(panel, _frame(frames, "trade_cal"))
    return panel.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)


def filter_frames_to_exchanges(
    frames: Mapping[str, pd.DataFrame], allowed_exchanges: Iterable[str] | None,
) -> dict[str, pd.DataFrame]:
    """Filter raw stock-code frames before stripping their exchange suffixes.

    The panel's public ``symbol`` identity is intentionally six-digit for
    downstream compatibility.  Therefore an exchange-specific research
    universe must be applied here, before any call to :func:`_symbols`.
    """
    if allowed_exchanges is None:
        return {name: _frame(frames, name) for name in frames}
    allowed = {str(exchange).strip().upper() for exchange in allowed_exchanges}
    if not allowed or any(not exchange.isalpha() for exchange in allowed):
        raise ValueError("allowed_exchanges must contain one or more exchange suffixes")
    filtered: dict[str, pd.DataFrame] = {}
    for name in frames:
        frame = _frame(frames, name)
        if name not in _STOCK_CODE_ENDPOINTS or frame.empty:
            filtered[name] = frame
            continue
        code_column = "con_code" if name == "index_member_all" and "con_code" in frame else "ts_code"
        if code_column not in frame:
            raise ValueError(f"{name} requires a stock code before exchange-universe filtering")
        codes = frame[code_column].astype("string").str.strip().str.upper()
        exchanges = codes.str.rsplit(".", n=1).str[-1]
        filtered[name] = frame.loc[exchanges.isin(allowed)].copy()
    return filtered


def _finalize_symbol_panel(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return panel
    panel = panel.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True).copy()
    grouped = panel.groupby("symbol", sort=False)
    panel["median_amount_20d"] = grouped["amount_cny"].transform(lambda values: values.rolling(20, min_periods=20).median())
    next_session = panel[["symbol", "trade_date", "adjusted_open", "valid_ohlc", "is_suspended", "at_up_limit_open"]].rename(
        columns={
            "trade_date": "next_open_date",
            "adjusted_open": "next_adjusted_open",
            "valid_ohlc": "next_valid_ohlc",
            "is_suspended": "next_is_suspended",
            "at_up_limit_open": "next_at_up_limit_open",
        }
    )
    panel = panel.merge(next_session, on=["symbol", "next_open_date"], how="left", validate="many_to_one")
    next_valid = panel["next_valid_ohlc"].eq(True)
    next_suspended = panel["next_is_suspended"].eq(True) | panel["next_is_suspended"].isna()
    next_at_up_limit = panel["next_at_up_limit_open"].eq(True) | panel["next_at_up_limit_open"].isna()
    panel["entry_tradeable"] = next_valid & ~next_suspended & ~next_at_up_limit & panel["next_adjusted_open"].notna()
    panel["eligible_signal_day"] = (
        panel["listing_age_trade_days"].ge(120)
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
    key_columns = ["trade_date", "symbol"]
    comparison_columns = [
        column for column in result.columns if column not in {"_source_order", "source_row_id", *key_columns}
    ]
    if comparison_columns:
        distinct = result.groupby(key_columns, sort=False, dropna=False)[comparison_columns].nunique(dropna=False)
        if bool((distinct > 1).any(axis=None)):
            raise ValueError(f"conflicting duplicate {endpoint} rows for trade_date,symbol")
    return result.drop_duplicates(key_columns, keep="last").drop(columns=["symbol"], errors="ignore")


def _join_daily_endpoint_fields(
    daily: pd.DataFrame, endpoint_rows: pd.DataFrame, endpoint: str, fields: tuple[str, ...]
) -> pd.DataFrame:
    """Left join raw same-day endpoint values; absent optional rows remain explicit nulls."""
    values = _deduplicate_market_rows(endpoint_rows, endpoint)
    if values.empty:
        result = daily.copy()
        for field in fields:
            result[field] = pd.NA
        return result
    values["symbol"] = _symbols(values)
    values["trade_date"] = values["trade_date"].map(_date_text)
    for field in fields:
        if field not in values:
            values[field] = pd.NA
    return daily.merge(values[["symbol", "trade_date", *fields]], on=["symbol", "trade_date"], how="left", validate="many_to_one")


def _join_market_context_fields(daily: pd.DataFrame, index_daily: pd.DataFrame) -> pd.DataFrame:
    """Broadcast one stable market index bar to every stock row on that date."""
    if index_daily.empty:
        result = daily.copy()
        result["market_index_close"] = pd.NA
        result["market_index_amount"] = pd.NA
        return result
    values = index_daily.copy()
    values["trade_date"] = values.get("trade_date", pd.Series("", index=values.index)).map(_date_text)
    values["ts_code"] = values.get("ts_code", pd.Series("", index=values.index)).astype(str)
    preferred = values.loc[values["ts_code"].eq("000001.SH")].copy()
    if preferred.empty:
        preferred = values.sort_values("ts_code", kind="stable").copy()
    for trade_date, rows in preferred.groupby("trade_date", sort=False):
        for column in ("close", "amount"):
            if column in rows and pd.to_numeric(rows[column], errors="coerce").nunique(dropna=True) > 1:
                raise ValueError(f"conflicting index_daily rows for trade_date={trade_date}")
    preferred = preferred.drop_duplicates("trade_date", keep="first")
    context = pd.DataFrame(
        {
            "trade_date": preferred["trade_date"],
            "market_index_close": pd.to_numeric(preferred.get("close"), errors="coerce"),
            "market_index_amount": pd.to_numeric(preferred.get("amount"), errors="coerce"),
        }
    )
    return daily.merge(context, on="trade_date", how="left", validate="many_to_one")


def _frame(frames: Mapping[str, pd.DataFrame], name: str) -> pd.DataFrame:
    value = frames.get(name)
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _symbols(frame: pd.DataFrame) -> pd.Series:
    source = frame["symbol"] if "symbol" in frame else frame.get("ts_code", pd.Series(index=frame.index, dtype=str))
    return source.astype(str).str.split(".", regex=False).str[0].str.zfill(6)


def _date_text(value) -> str:
    if pd.isna(value) or value is None:
        return ""
    digits = "".join(character for character in str(value) if character.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else str(value)


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
    for symbol, values in intervals.items():
        ordered = sorted(values, key=lambda value: (value[0], value[1], str(value[2])))
        previous = []
        for current in ordered:
            current_start, current_end, current_name = current
            for prior_start, prior_end, prior_name in previous:
                if not current_start or not prior_start:
                    continue
                overlaps = not prior_end or current_start <= prior_end
                exact_duplicate = (prior_start, prior_end, prior_name) == (current_start, current_end, current_name)
                if overlaps and not exact_duplicate:
                    raise ValueError(f"overlapping historical industry intervals for symbol={symbol}")
            previous.append(current)
    return pd.Series(
        [next((name for start, end, name in intervals.get(symbol, []) if start <= trade_date and (not end or trade_date <= end)), pd.NA) for symbol, trade_date in zip(panel.symbol, panel.trade_date)],
        index=panel.index,
        dtype="object",
    )


def _build_calendar_lookup(trade_cal: pd.DataFrame) -> _CalendarLookup:
    open_dates = tuple(_open_dates(trade_cal))
    return _CalendarLookup(open_dates=open_dates, rank_by_date={trade_date: index + 1 for index, trade_date in enumerate(open_dates)})


def _listing_ages(panel: pd.DataFrame, stock_basic: pd.DataFrame, calendar_lookup: _CalendarLookup) -> pd.Series:
    if stock_basic.empty or not calendar_lookup.open_dates:
        return pd.Series(0, index=panel.index, dtype="int64")
    basics = stock_basic.copy()
    basics["symbol"] = _symbols(basics)
    list_dates = dict(zip(basics.symbol, basics.get("list_date", pd.Series("", index=basics.index)).map(_date_text)))
    first_open_rank = {}
    for symbol, list_date in list_dates.items():
        first_open_index = bisect_left(calendar_lookup.open_dates, list_date) if list_date else len(calendar_lookup.open_dates)
        if first_open_index < len(calendar_lookup.open_dates):
            first_open_rank[symbol] = first_open_index + 1
    trade_ranks = panel["trade_date"].map(calendar_lookup.rank_by_date)
    listing_ranks = panel["symbol"].map(first_open_rank)
    ages = (trade_ranks - listing_ranks + 1).where(trade_ranks >= listing_ranks, 0)
    return ages.fillna(0).astype("int64")


def _limit_flags(panel: pd.DataFrame, limits: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    if limits.empty:
        empty = pd.Series(False, index=panel.index)
        return empty, empty.copy(), empty.copy()
    limits = limits.copy()
    limits["symbol"] = _symbols(limits)
    limits["trade_date"] = limits["trade_date"].map(_date_text)
    up_limits = dict(zip(zip(limits.symbol, limits.trade_date), pd.to_numeric(limits.get("up_limit"), errors="coerce")))
    down_limits = dict(zip(zip(limits.symbol, limits.trade_date), pd.to_numeric(limits.get("down_limit"), errors="coerce")))
    keys = list(zip(panel.symbol, panel.trade_date))
    up_close = pd.Series([pd.notna(up_limits.get(key)) and close >= up_limits[key] for key, close in zip(keys, panel.close)], index=panel.index)
    down_close = pd.Series([pd.notna(down_limits.get(key)) and close <= down_limits[key] for key, close in zip(keys, panel.close)], index=panel.index)
    up_open = pd.Series([pd.notna(up_limits.get(key)) and opening >= up_limits[key] for key, opening in zip(keys, panel.open)], index=panel.index)
    return up_close, down_close, up_open


def _load_static_frames(root: Path, manifest: CollectionManifest) -> dict[str, pd.DataFrame]:
    frames = {endpoint: _read_partitions(root, [record for record in manifest.partitions if record.endpoint == endpoint]) for endpoint in _STATIC_ENDPOINTS}
    frames["trade_cal"] = _read_partitions(root, [record for record in manifest.partitions if record.endpoint == "trade_cal"])
    frames["suspend_d"] = _read_partitions(root, [record for record in manifest.partitions if record.endpoint == "suspend_d"])
    return frames


def _load_daily_frames(root: Path, manifest: CollectionManifest, trade_date: str) -> dict[str, pd.DataFrame]:
    compact = trade_date.replace("-", "")
    endpoints = {"daily", "daily_basic", "adj_factor", "stk_limit", "moneyflow", "index_daily", "index_dailybasic"}
    return {
        endpoint: _read_partitions(root, [record for record in manifest.partitions if record.endpoint == endpoint and record.key == compact])
        for endpoint in endpoints
    }


def _open_trade_dates(root: Path, manifest: CollectionManifest) -> list[str]:
    calendar = _read_partitions(root, [record for record in manifest.partitions if record.endpoint == "trade_cal"])
    return _open_dates(calendar)


def _read_partitions(root: Path, records) -> pd.DataFrame:
    frames = [pq.ParquetFile(validate_partition(root, record)).read().to_pandas() for record in records if record.status != "failed"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write_intermediate_shards(panel: pd.DataFrame, temporary: Path, trade_date: str) -> None:
    for shard in range(SHARD_COUNT):
        rows = panel[panel.symbol.map(_shard_for_symbol) == shard]
        if rows.empty:
            continue
        path = temporary / f"shard={shard:02d}" / f"trade_date={trade_date}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(rows, preserve_index=False), path)


def _finalize_shards(temporary: Path, output: Path, industry_relative_enabled: bool) -> tuple[list[Path], int, Path]:
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
        _write_feature_contract(staging)
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, output)
        return paths, row_count, output / "feature_contract.json"
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _write_feature_contract(staging: Path) -> None:
    contract = {
        "schema_version": 1,
        "allowed_feature_columns": list(ALLOWED_FEATURE_COLUMNS),
        "excluded_future_execution_columns": list(FUTURE_EXECUTION_COLUMNS),
    }
    (staging / "feature_contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _shard_for_symbol(symbol: str) -> int:
    return int.from_bytes(hashlib.sha256(symbol.encode("ascii")).digest()[:8], "big") % SHARD_COUNT
