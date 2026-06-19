#!/usr/bin/env python3
"""Run reproducible candidate ranking evaluation reports."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.ranking_labels import DEFAULT_STRONG_LABEL_CONFIG
from app.evaluation.ranking_fixtures import smoke_fixture_rows
from app.evaluation.ranking_replay import RankingReplayService
from app.evaluation.ranking_report import build_ranking_report


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate historical SmartStock candidate ranking quality.")
    parser.add_argument("--strategy-code", required=True)
    parser.add_argument("--risk-level", required=True, choices=("low", "medium", "high"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--horizons", default="3,5,10,20")
    parser.add_argument("--top-k", default="3,5,10")
    parser.add_argument("--commission", type=float, default=0.0003)
    parser.add_argument("--slippage", type=float, default=0.001)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fixture", choices=("smoke",), default=None)
    args = parser.parse_args(argv)
    return validate_args(parser, args)


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> argparse.Namespace:
    start = _parse_date(parser, "start-date", args.start_date)
    end = _parse_date(parser, "end-date", args.end_date)
    if start > end:
        parser.error("start-date must be on or before end-date")
    args.horizons = _parse_int_list(parser, "horizons", args.horizons)
    args.top_k = _parse_int_list(parser, "top-k", args.top_k)
    if args.commission < 0:
        parser.error("commission must be greater than or equal to 0")
    if args.slippage < 0:
        parser.error("slippage must be greater than or equal to 0")
    return args


def run(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    label_config = dict(DEFAULT_STRONG_LABEL_CONFIG)
    label_config["horizons"] = list(args.horizons)
    execution_config = {
        "commission": float(args.commission),
        "slippage": float(args.slippage),
        "fixture": args.fixture,
    }
    if args.fixture == "smoke":
        rows, coverage = smoke_fixture_rows(args.horizons)
    else:
        from app.main import coach_store, data_source_manager

        service = RankingReplayService(store=coach_store, data_source_manager=data_source_manager)
        replay = service.replay(
            strategy_code=args.strategy_code,
            risk_level=args.risk_level,
            start_date=args.start_date,
            end_date=args.end_date,
            attach_labels=True,
            label_config=label_config,
        )
        rows = replay["rows"]
        coverage = replay["coverage"]
        if coverage.get("coverage_status") == "blocked":
            print("ranking evaluation blocked: no historical candidate snapshots found", file=sys.stderr)
            return 2

    summary = build_ranking_report(
        candidate_rows=rows,
        strategy_code=args.strategy_code,
        risk_level=args.risk_level,
        start_date=args.start_date,
        end_date=args.end_date,
        horizons=args.horizons,
        top_k_values=args.top_k,
        output_dir=args.output_dir,
        label_config=label_config,
        coverage=coverage,
        execution_config=execution_config,
    )
    print_summary(summary, args.output_dir)
    return 0


def print_summary(summary: dict, output_dir: str) -> None:
    metrics = summary.get("metrics") or {}
    print(f"output_dir: {Path(output_dir).resolve()}")
    print(f"coverage_status: {(summary.get('coverage') or {}).get('coverage_status')}")
    print(f"candidate_rows: {summary.get('candidate_row_count')}")
    print(
        "Precision@3={precision_at_3} Precision@5={precision_at_5} Precision@10={precision_at_10}".format(
            **metrics
        )
    )
    print(f"Recall@10={metrics.get('recall_at_10')} NDCG@10={metrics.get('ndcg_at_10')} MRR={metrics.get('mrr')}")


def _parse_date(parser: argparse.ArgumentParser, name: str, value: str):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        parser.error(f"{name} must use YYYY-MM-DD")
    if parsed.isoformat() != value:
        parser.error(f"{name} must use YYYY-MM-DD")
    return parsed


def _parse_int_list(parser: argparse.ArgumentParser, name: str, value: str) -> List[int]:
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
