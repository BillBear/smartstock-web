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
    parser = argparse.ArgumentParser(description="Run read-only candidate rerank policy experiments.")
    parser.add_argument("--candidate-features", required=True)
    parser.add_argument("--policies", default="momentum_macd_v1,balanced_liquidity_v1")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--train-ratio", type=float, default=0.6)
    parser.add_argument("--round-trip-cost-pct", type=float, default=0.13)
    parser.add_argument("--min-margin-pct", type=float, default=0.30)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap()
    from app.evaluation.rerank_candidate_policy import run_rerank_policy_experiment, write_rerank_policy_artifacts

    args = parse_args(argv)
    candidate_features = pd.read_csv(args.candidate_features)
    policies = [item.strip() for item in str(args.policies).split(",") if item.strip()]
    summary = run_rerank_policy_experiment(
        candidate_features,
        policies=policies,
        horizon=int(args.horizon),
        train_ratio=float(args.train_ratio),
        round_trip_cost_pct=float(args.round_trip_cost_pct),
        min_margin_pct=float(args.min_margin_pct),
    )
    paths = write_rerank_policy_artifacts(summary, args.output_dir)
    print(
        json.dumps(
            {
                "status": "completed",
                "experiment_status": summary.get("status"),
                "decision": (summary.get("decision") or {}).get("outcome"),
                "selected_rule": (summary.get("selected_rule") or {}).get("name", ""),
                "production_evidence": summary.get("production_evidence"),
                "artifacts": paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
