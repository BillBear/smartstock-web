#!/usr/bin/env python3
"""Run the development-only full-market trading-amount tail audit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.amount_tail_stage import run_amount_tail_signal_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-run-root", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    result = run_amount_tail_signal_audit(
        arguments.config,
        arguments.source_run_root,
        arguments.asset_root,
        arguments.output_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
