#!/usr/bin/env python3
"""Audit an immutable full-market dataset against its historical listing universe."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.panel import build_historical_universe
from app.evaluation.full_market_ml.sample_audit import build_sample_audit


PANEL_COLUMNS = (
    "trade_date", "symbol", "valid_ohlc", "listing_age_trade_days",
    "eligible_signal_day", "entry_tradeable", "is_st", "is_suspended",
    "industry_l1", "total_mv", "amount_cny", "median_amount_20d",
    "at_up_limit", "at_down_limit", "turnover_rate", "net_mf_amount", "market_state_10d",
)


def audit_dataset(asset_root: Path, dataset_id: str, *, stock_basic_path: Path | None = None) -> dict:
    dataset_root = asset_root / "datasets" / dataset_id
    registry_path = dataset_root / "artifacts" / "full-build" / "dataset_registry_v3.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    raw_sha = str(registry["payload"]["raw_manifest_sha256"])
    raw_root = asset_root / "raw" / f"raw_{raw_sha[:16]}"
    shard_root = dataset_root / "artifacts" / "full-build" / "dataset-v3"
    shards = sorted(shard_root.glob("shard=*/data.parquet"))
    if not shards:
        raise FileNotFoundError(f"no dataset shards under {shard_root}")
    available = set(pq.ParquetFile(shards[0]).schema.names)
    columns = [column for column in PANEL_COLUMNS if column in available]
    panel = pd.concat((pq.read_table(path, columns=columns).to_pandas() for path in shards), ignore_index=True)

    if stock_basic_path:
        stock_basic = pq.read_table(stock_basic_path).to_pandas()
    else:
        stock_basic_files = sorted((raw_root / "raw" / "endpoint=stock_basic").glob("list_status=*/data.parquet"))
        if not stock_basic_files:
            raise FileNotFoundError("raw stock_basic partitions are unavailable")
        stock_basic = pd.concat((pq.read_table(path).to_pandas() for path in stock_basic_files), ignore_index=True)
    if "list_status" not in stock_basic.columns or "delist_date" not in stock_basic.columns:
        raise ValueError("historical stock_basic lacks list_status/delist_date; collect a corrected snapshot")
    trade_dates = sorted(panel["trade_date"].astype(str).str.replace("-", "", regex=False).unique().tolist())
    historical = build_historical_universe(stock_basic, trade_dates)
    expected = (
        historical.groupby("trade_date", sort=True)["symbol"]
        .nunique()
        .rename("expected_active_count")
        .reset_index()
    )
    report = build_sample_audit(panel, expected)
    report.update({"dataset_id": dataset_id, "raw_asset_id": raw_root.name})
    return report


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stock-basic-path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = audit_dataset(args.asset_root, args.dataset_id, stock_basic_path=args.stock_basic_path)
    if not args.dry_run:
        if not args.output:
            parser.error("--output is required unless --dry-run is used")
        _write_json_atomic(args.output, report)
    print(json.dumps({"output": str(args.output) if args.output else None, "ready": report["ready"], "blocking_codes": report["blocking_codes"]}, ensure_ascii=False))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
