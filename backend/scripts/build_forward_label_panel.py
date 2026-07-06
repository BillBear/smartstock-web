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
    parser = argparse.ArgumentParser(description="Build a read-only forward label panel from historical OHLCV rows.")
    parser.add_argument("--history-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--horizons", default="3,5,10,20")
    parser.add_argument("--take-profit-pct", type=float, default=10.0)
    parser.add_argument("--stop-loss-pct", type=float, default=-6.0)
    parser.add_argument("--strong-return-pct", type=float, default=5.0)
    parser.add_argument("--limit-threshold-pct", type=float, default=9.8)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap()
    from app.evaluation.forward_label_panel import (
        build_forward_label_panel,
        summarize_forward_label_panel,
        write_forward_label_artifacts,
    )

    args = parse_args(argv)
    history = pd.read_csv(args.history_csv)
    horizons = [int(item.strip()) for item in str(args.horizons).split(",") if item.strip()]
    panel = build_forward_label_panel(
        history,
        horizons=horizons,
        take_profit_pct=float(args.take_profit_pct),
        stop_loss_pct=float(args.stop_loss_pct),
        strong_return_pct=float(args.strong_return_pct),
        limit_threshold_pct=float(args.limit_threshold_pct),
    )
    paths = write_forward_label_artifacts(
        panel,
        output_csv=args.output_csv,
        horizons=horizons,
        summary_json=args.summary_json or None,
    )
    summary = summarize_forward_label_panel(panel, horizons=horizons)
    print(json.dumps({"status": "completed", **summary, "artifacts": paths}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
