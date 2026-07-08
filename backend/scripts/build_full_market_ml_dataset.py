from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build normalized full-market ML panel from collected TuShare partitions.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--min-daily-count", type=int, default=4500)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.full_market_panel_builder import build_full_market_panel

    args = parse_args(argv)
    _, report = build_full_market_panel(args.input_dir, output_path=args.output_path, min_daily_count=args.min_daily_count)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
