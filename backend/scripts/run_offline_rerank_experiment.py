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
    parser = argparse.ArgumentParser(description="Run a read-only offline rerank experiment on enriched candidate features.")
    parser.add_argument("--candidate-features-csv", required=True, help="candidate_features.csv from candidate feature enrichment")
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
    from app.evaluation.offline_rerank_experiment import (
        run_offline_rerank_experiment,
        write_offline_rerank_artifacts,
    )

    args = parse_args(argv)
    candidates = pd.read_csv(args.candidate_features_csv)
    summary = run_offline_rerank_experiment(
        candidates,
        horizon=int(args.horizon),
        train_ratio=float(args.train_ratio),
        round_trip_cost_pct=float(args.round_trip_cost_pct),
        min_margin_pct=float(args.min_margin_pct),
        min_total_dates=int(args.min_total_dates),
        min_test_dates=int(args.min_test_dates),
    )
    paths = write_offline_rerank_artifacts(summary, args.output_dir)
    selected = summary.get("selected_rule") or {}
    decision = summary.get("decision") or {}
    print(
        json.dumps(
            {
                "status": "offline_rerank_experiment_completed",
                "experiment_status": summary.get("status"),
                "decision": decision.get("outcome"),
                "production_evidence": summary.get("production_evidence"),
                "selected_rule": selected.get("name", ""),
                "eligible_date_count": (summary.get("sample") or {}).get("eligible_date_count"),
                "output_dir": str(args.output_dir),
                "artifacts": paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
