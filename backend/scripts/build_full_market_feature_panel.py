from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def _bootstrap() -> Path:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build a read-only full-market feature panel from historical OHLCV rows.")
    parser.add_argument("--history-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--min-symbols-per-date", type=int, default=5000)
    parser.add_argument("--return-windows", default="1,5,10,20,60")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap()
    from app.evaluation.full_market_feature_panel import (
        build_full_market_feature_panel,
        summarize_full_market_feature_panel,
        write_full_market_feature_panel_artifacts,
    )

    args = parse_args(argv)
    history = pd.read_csv(args.history_csv)
    windows = [int(item.strip()) for item in str(args.return_windows).split(",") if item.strip()]
    panel = build_full_market_feature_panel(
        history,
        min_symbols_per_date=int(args.min_symbols_per_date),
        return_windows=windows,
    )
    paths = write_full_market_feature_panel_artifacts(
        panel,
        output_csv=args.output_csv,
        min_symbols_per_date=int(args.min_symbols_per_date),
        summary_json=args.summary_json or None,
    )
    summary = summarize_full_market_feature_panel(panel, min_symbols_per_date=int(args.min_symbols_per_date))
    print(json.dumps({"status": "completed", **summary, "artifacts": paths}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
