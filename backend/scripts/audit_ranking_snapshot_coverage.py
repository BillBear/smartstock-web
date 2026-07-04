#!/usr/bin/env python3
"""Audit persisted snapshot coverage for ranking evaluation readiness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.ranking_coverage_audit import (  # noqa: E402
    build_ranking_snapshot_coverage_audit,
    write_ranking_snapshot_coverage_audit,
)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit SmartStock ranking evaluation snapshot coverage.")
    parser.add_argument("--strategy-code", default="trend_breakout")
    parser.add_argument("--risk-level", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--horizons", default="3,5,10,20")
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--min-market-snapshot-count", type=int, default=500)
    parser.add_argument("--min-covered-dates", type=int, default=30)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    args.horizons = _parse_int_list(parser, "horizons", args.horizons)
    return args


def run(argv: Optional[Iterable[str]] = None, store=None) -> int:
    args = parse_args(argv)
    if store is None:
        from app.main import coach_store
        store = coach_store

    audit = build_ranking_snapshot_coverage_audit(
        store=store,
        strategy_code=args.strategy_code,
        risk_level=args.risk_level,
        start_date=args.start_date,
        end_date=args.end_date,
        horizons=args.horizons,
        user_id=args.user_id,
        as_of_date=args.as_of_date,
        min_market_snapshot_count=args.min_market_snapshot_count,
        min_covered_dates=args.min_covered_dates,
    )
    if args.output:
        write_ranking_snapshot_coverage_audit(args.output, audit)
    print_summary(audit)
    return 0


def print_summary(audit: dict) -> None:
    print(f"coverage_status: {audit.get('coverage_status')}")
    print(f"requested_dates: {audit.get('requested_date_count')}")
    print(f"pick_covered_dates: {audit.get('pick_covered_date_count')}")
    print(f"missing_pick_dates: {audit.get('missing_pick_date_count')}")
    print(f"market_snapshot_summary: {json.dumps(audit.get('market_snapshot_summary') or {}, ensure_ascii=False, sort_keys=True)}")
    print(f"incomplete_label_dates: {audit.get('incomplete_label_date_count')}")
    print(f"blocking_reasons: {','.join(audit.get('blocking_reasons') or []) or '-'}")
    if audit.get("missing_pick_dates"):
        print("missing_pick_date_list: " + ",".join(audit.get("missing_pick_dates") or []))


def _parse_int_list(parser: argparse.ArgumentParser, name: str, value: str):
    try:
        items = [int(item.strip()) for item in str(value).split(",") if item.strip()]
    except ValueError:
        parser.error(f"{name} must be a comma-separated integer list")
    if not items:
        parser.error(f"{name} must not be empty")
    if any(item <= 0 for item in items):
        parser.error(f"{name} values must be greater than 0")
    return items


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
