from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run read-only TuShare enhanced feature audit from CSV panels.")
    parser.add_argument("--base-panel-csv", required=True)
    parser.add_argument("--daily-basic-csv")
    parser.add_argument("--adj-factor-csv")
    parser.add_argument("--stk-limit-csv")
    parser.add_argument("--suspend-csv")
    parser.add_argument("--index-csv")
    parser.add_argument("--moneyflow-csv")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--train-ratio", type=float, default=0.6)
    parser.add_argument("--round-trip-cost-pct", type=float, default=0.13)
    parser.add_argument("--min-margin-pct", type=float, default=0.30)
    parser.add_argument("--min-total-dates", type=int, default=4)
    parser.add_argument("--min-test-dates", type=int, default=2)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.tushare_enhanced_feature_audit import (
        build_tushare_enhanced_feature_panel,
        run_tushare_enhanced_feature_audit,
        write_tushare_enhanced_feature_artifacts,
    )

    args = parse_args(argv)
    base = pd.read_csv(args.base_panel_csv)
    feature_panel = build_tushare_enhanced_feature_panel(
        base,
        daily_basic_panel=_read_optional_csv(args.daily_basic_csv),
        adj_factor_panel=_read_optional_csv(args.adj_factor_csv),
        stk_limit_panel=_read_optional_csv(args.stk_limit_csv),
        suspend_panel=_read_optional_csv(args.suspend_csv),
        index_panel=_read_optional_csv(args.index_csv),
        moneyflow_panel=_read_optional_csv(args.moneyflow_csv),
    )
    summary = run_tushare_enhanced_feature_audit(
        feature_panel,
        horizon=int(args.horizon),
        train_ratio=float(args.train_ratio),
        round_trip_cost_pct=float(args.round_trip_cost_pct),
        min_margin_pct=float(args.min_margin_pct),
        min_total_dates=int(args.min_total_dates),
        min_test_dates=int(args.min_test_dates),
    )
    paths = write_tushare_enhanced_feature_artifacts(summary, feature_panel, args.output_dir)
    print(
        json.dumps(
            {
                "status": "tushare_enhanced_feature_audit_completed",
                "experiment_status": summary.get("status"),
                "production_evidence": summary.get("production_evidence"),
                "strategy_impact": summary.get("strategy_impact"),
                "baseline_rule": summary.get("baseline_rule"),
                "best_enhanced_rule": summary.get("best_enhanced_rule"),
                "ml_v2_2_allowed": (summary.get("ml_v2_2_gate") or {}).get("allowed"),
                "output_dir": str(args.output_dir),
                "artifacts": paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_optional_csv(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    return pd.read_csv(candidate)


if __name__ == "__main__":
    raise SystemExit(main())
