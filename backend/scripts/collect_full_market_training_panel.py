from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Collect TuShare full-market training panels.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-dir", default="../runtime/ml_full_market")
    parser.add_argument("--min-daily-count", type=int, default=4500)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.full_market_panel_builder import FullMarketPanelCollector
    from app.services.tushare_service import TuShareService

    args = parse_args(argv)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "start_date": args.start_date,
                    "end_date": args.end_date,
                    "output_dir": args.output_dir,
                    "endpoints": [
                        "stock_basic",
                        "daily",
                        "daily_basic",
                        "adj_factor",
                        "stk_limit",
                        "suspend_d",
                        "moneyflow",
                        "index_daily",
                        "index_dailybasic",
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 0
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("TUSHARE_TOKEN is required unless --dry-run is used", file=sys.stderr)
        return 2
    client = TuShareService(token).pro
    collector = FullMarketPanelCollector(
        client,
        args.output_dir,
        min_daily_count=args.min_daily_count,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(collector.collect(args.start_date, args.end_date), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
