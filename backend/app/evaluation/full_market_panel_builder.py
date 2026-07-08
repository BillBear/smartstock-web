from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd


DEFAULT_ENDPOINTS = [
    "stock_basic",
    "daily",
    "daily_basic",
    "adj_factor",
    "stk_limit",
    "suspend_d",
    "moneyflow",
    "index_daily",
    "index_dailybasic",
]


@dataclass
class FullMarketPanelCollector:
    client: Any
    output_dir: str | Path
    min_daily_count: int = 4500
    sleep_seconds: float = 0.0
    endpoints: Iterable[str] | None = None

    def collect(self, start_date: str, end_date: str) -> Dict[str, Any]:
        root = Path(self.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        trade_dates = self._trade_dates(start_date, end_date)
        endpoints = list(self.endpoints or DEFAULT_ENDPOINTS)
        collected: List[Dict[str, Any]] = []
        skipped = 0
        low_quality_dates: List[str] = []
        for trade_date in trade_dates:
            daily_path = _partition_path(root, "daily", trade_date)
            if daily_path.exists():
                skipped += 1
                continue
            endpoint_rows: Dict[str, int] = {}
            for endpoint in endpoints:
                frame = self._call_endpoint(endpoint, trade_date)
                endpoint_rows[endpoint] = int(len(frame))
                _write_frame(_partition_path(root, endpoint, trade_date), frame)
                if self.sleep_seconds:
                    time.sleep(float(self.sleep_seconds))
            if endpoint_rows.get("daily", 0) < int(self.min_daily_count):
                low_quality_dates.append(_date_text(trade_date))
            collected.append({"trade_date": _date_text(trade_date), "rows": endpoint_rows})
        manifest = {
            "start_date": _date_text(start_date),
            "end_date": _date_text(end_date),
            "date_count": len(trade_dates),
            "collected_count": len(collected),
            "skipped_existing_count": skipped,
            "endpoints": endpoints,
            "dates": collected,
            "quality": {
                "min_daily_count": int(self.min_daily_count),
                "low_quality_dates": low_quality_dates,
            },
        }
        manifest_path = root / "manifests" / "collection_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def _trade_dates(self, start_date: str, end_date: str) -> List[str]:
        start_compact = _date_compact(start_date)
        end_compact = _date_compact(end_date)
        if not hasattr(self.client, "trade_cal"):
            return [_date_compact(item) for item in pd.bdate_range(_date_text(start_date), _date_text(end_date)).strftime("%Y%m%d")]
        frame = self.client.trade_cal(start_date=start_compact, end_date=end_compact)
        if frame is None or frame.empty:
            return []
        date_col = "cal_date" if "cal_date" in frame.columns else "trade_date"
        local = frame.copy()
        if "is_open" in local.columns:
            local = local[pd.to_numeric(local["is_open"], errors="coerce").fillna(0).astype(int) == 1]
        dates = [_date_compact(item) for item in local[date_col].tolist()]
        return [date for date in dates if start_compact <= date <= end_compact]

    def _call_endpoint(self, endpoint: str, trade_date: str) -> pd.DataFrame:
        method = getattr(self.client, endpoint, None)
        if method is None:
            return pd.DataFrame()
        try:
            if endpoint == "stock_basic":
                frame = method(exchange="", list_status="L")
            elif endpoint == "suspend_d":
                frame = method(trade_date=_date_compact(trade_date), suspend_type="S")
            else:
                frame = method(trade_date=_date_compact(trade_date))
        except TypeError:
            frame = method(trade_date=_date_compact(trade_date))
        except Exception:
            return pd.DataFrame()
        result = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame or [])
        if endpoint == "stock_basic" and "trade_date" not in result.columns:
            result = result.copy()
            result["trade_date"] = _date_compact(trade_date)
        return result


def build_full_market_panel(
    collected_root: str | Path,
    output_path: str | Path | None = None,
    min_daily_count: int = 4500,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    root = Path(collected_root)
    daily = _read_endpoint(root, "daily")
    if daily.empty:
        return pd.DataFrame(), {"row_count": 0, "blocking_reasons": ["missing_daily"]}
    panel = _normalize_symbol_date(daily)
    panel = panel.rename(columns={"vol": "volume"})
    if "amount" in panel.columns:
        panel["amount"] = _num(panel["amount"]) * 1000.0
    if "volume" in panel.columns:
        panel["volume"] = _num(panel["volume"]) * 100.0
    for column in ["open", "high", "low", "close", "pre_close", "pct_chg", "volume", "amount"]:
        if column not in panel.columns:
            panel[column] = 0.0
        panel[column] = _num(panel[column])

    stock_basic = _normalize_symbol_date(_read_endpoint(root, "stock_basic"))
    if not stock_basic.empty:
        panel = _merge(panel, stock_basic, ["name", "industry", "market", "list_date", "list_status"])
    daily_basic = _normalize_symbol_date(_read_endpoint(root, "daily_basic"))
    panel = _merge(
        panel,
        daily_basic,
        ["turnover_rate", "turnover_rate_f", "volume_ratio", "pe_ttm", "pb", "total_mv", "circ_mv"],
    )
    adj_factor = _normalize_symbol_date(_read_endpoint(root, "adj_factor"))
    panel = _merge(panel, adj_factor, ["adj_factor"])
    stk_limit = _normalize_symbol_date(_read_endpoint(root, "stk_limit"))
    panel = _merge(panel, stk_limit, ["up_limit", "down_limit"])
    moneyflow = _normalize_symbol_date(_read_endpoint(root, "moneyflow"))
    panel = _merge(panel, moneyflow, ["net_mf_amount", "buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"])
    panel = _attach_suspend(panel, _read_endpoint(root, "suspend_d"))
    panel = _finish_panel(panel)
    report = assess_full_market_panel_quality(panel, min_daily_count=min_daily_count)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(output, index=False)
    return panel, report


def assess_full_market_panel_quality(panel: pd.DataFrame, min_daily_count: int = 4500) -> Dict[str, Any]:
    if panel is None or panel.empty:
        return {
            "trainable": False,
            "row_count": 0,
            "date_count": 0,
            "symbol_count": 0,
            "low_quality_dates": [],
            "blocking_reasons": ["empty_panel"],
        }
    local = panel.copy()
    daily_count = local.groupby("trade_date")["symbol"].nunique()
    low_quality = [str(date) for date, count in daily_count.items() if int(count) < int(min_daily_count)]
    reasons = []
    if low_quality:
        reasons.append("daily_count_below_minimum")
    return {
        "trainable": not reasons,
        "row_count": int(len(local)),
        "date_count": int(local["trade_date"].nunique()),
        "symbol_count": int(local["symbol"].nunique()),
        "min_daily_count": int(daily_count.min()) if not daily_count.empty else 0,
        "median_daily_count": float(daily_count.median()) if not daily_count.empty else 0.0,
        "low_quality_dates": low_quality,
        "blocking_reasons": reasons,
    }


def _partition_path(root: Path, endpoint: str, trade_date: str) -> Path:
    return root / "raw" / endpoint / f"trade_date={_date_compact(trade_date)}" / "data.parquet"


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    (frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()).to_parquet(path, index=False)


def _read_endpoint(root: Path, endpoint: str) -> pd.DataFrame:
    paths = sorted((root / "raw" / endpoint).glob("trade_date=*/data.parquet"))
    frames = [pd.read_parquet(path) for path in paths if path.exists()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalize_symbol_date(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "symbol" not in local.columns and "ts_code" in local.columns:
        local["symbol"] = local["ts_code"]
    if "trade_date" not in local.columns and "date" in local.columns:
        local["trade_date"] = local["date"]
    if "symbol" not in local.columns or "trade_date" not in local.columns:
        return pd.DataFrame()
    local["symbol"] = local["symbol"].map(_symbol)
    local["trade_date"] = local["trade_date"].map(_date_text)
    return local[(local["symbol"] != "") & (local["trade_date"] != "")].copy()


def _merge(panel: pd.DataFrame, other: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    if other is None or other.empty:
        for column in columns:
            if column not in panel.columns:
                panel[column] = pd.NA
        return panel
    keep = ["symbol", "trade_date"] + [column for column in columns if column in other.columns]
    if len(keep) <= 2:
        return panel
    slim = other[keep].drop_duplicates(["symbol", "trade_date"], keep="last")
    overlap = [column for column in keep[2:] if column in panel.columns]
    if overlap:
        panel = panel.drop(columns=overlap)
    return panel.merge(slim, on=["symbol", "trade_date"], how="left")


def _attach_suspend(panel: pd.DataFrame, suspend: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    flags = _normalize_symbol_date(suspend)
    if flags.empty:
        local["is_suspended"] = False
        return local
    slim = flags[["symbol", "trade_date"]].drop_duplicates()
    slim["is_suspended"] = True
    merged = local.merge(slim, on=["symbol", "trade_date"], how="left")
    merged["is_suspended"] = merged["is_suspended"].eq(True)
    return merged


def _finish_panel(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    local["trade_date"] = local["trade_date"].map(_date_text)
    local = local.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    for column in [
        "adj_factor",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe_ttm",
        "pb",
        "total_mv",
        "circ_mv",
        "up_limit",
        "down_limit",
        "net_mf_amount",
        "buy_lg_amount",
        "buy_elg_amount",
        "sell_lg_amount",
        "sell_elg_amount",
    ]:
        if column not in local.columns:
            local[column] = pd.NA
        local[column] = _num(local[column])
    local["adj_factor"] = local["adj_factor"].fillna(1.0)
    local["adj_close"] = local["close"] * local["adj_factor"]
    local["board"] = local.apply(_board, axis=1)
    local["list_date"] = local.get("list_date", "").fillna("").astype(str)
    local["is_st"] = local.get("name", "").fillna("").astype(str).str.upper().str.contains("ST|退", regex=True)
    local["hit_limit_up_today"] = local["up_limit"].notna() & local["close"].ge(local["up_limit"] * 0.999)
    local["hit_limit_down_today"] = local["down_limit"].notna() & local["close"].le(local["down_limit"] * 1.001)
    next_open = local.groupby("symbol")["open"].shift(-1)
    next_up = local.groupby("symbol")["up_limit"].shift(-1)
    next_suspended = local.groupby("symbol")["is_suspended"].shift(-1).fillna(True).astype(bool)
    local["entry_tradeable"] = next_open.notna() & ~next_suspended & (next_up.isna() | next_open.lt(next_up * 0.999))
    return local.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _symbol(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else ""


def _date_compact(value: Any) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y%m%d")


def _date_text(value: Any) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _num(values: Any) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")


def _board(row: pd.Series) -> str:
    market = str(row.get("market") or "").lower()
    symbol = str(row.get("symbol") or "")
    if "科创" in market or symbol.startswith("688"):
        return "star"
    if "创业" in market or symbol.startswith("300"):
        return "chinext"
    if symbol.startswith(("4", "8")):
        return "beijing"
    return "main"
