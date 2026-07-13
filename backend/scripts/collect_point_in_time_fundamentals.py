"""Collect additive TuShare announcement data for the R4B research round."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.collector import (  # noqa: E402
    POINT_IN_TIME_ENDPOINTS,
    collect_point_in_time_fundamentals,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect point-in-time fundamentals into an immutable asset")
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--raw-asset-id", required=True)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--endpoints", nargs="+", choices=POINT_IN_TIME_ENDPOINTS, default=["fina_indicator"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pacing-seconds", type=float, default=0.05)
    return parser


def load_market_symbols(asset_root: Path, raw_asset_id: str) -> tuple[str, ...]:
    paths = sorted((asset_root / "raw" / raw_asset_id / "raw" / "endpoint=stock_basic").glob("list_status=*/data.parquet"))
    if not paths:
        raise FileNotFoundError("stock_basic partitions are missing")
    rows = pd.concat([pd.read_parquet(path, columns=["ts_code"]) for path in paths], ignore_index=True)
    symbols = tuple(sorted(rows["ts_code"].astype("string").dropna().str.upper().unique()))
    if len(symbols) < 4500:
        raise ValueError(f"full-market symbol list is too small: {len(symbols)}")
    return symbols


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured")
    import tushare as ts

    asset_root = Path(args.asset_root).resolve()
    symbols = load_market_symbols(asset_root, args.raw_asset_id)
    output = asset_root / "fundamentals" / args.asset_id
    manifest = collect_point_in_time_fundamentals(
        ts.pro_api(token),
        symbols,
        output,
        start_date=args.start_date,
        end_date=args.end_date,
        pacing_seconds=args.pacing_seconds,
        endpoints=tuple(args.endpoints),
        workers=args.workers,
    )
    summary = {
        "status": manifest["status"],
        "asset_id": args.asset_id,
        "symbol_count": len(symbols),
        "partition_count": manifest["partition_count"],
        "error_count": len(manifest["errors"]),
        "manifest": str(output / "collection_manifest.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
