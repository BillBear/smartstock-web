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
    parser = argparse.ArgumentParser(description="Compare SmartStock ranking against read-only rule baselines.")
    parser.add_argument("--candidate-csv", required=True, help="ranking_item_labels.csv from historical ranking evaluation")
    parser.add_argument("--feature-sample-path", required=True, help="CSV or parquet sample containing rule feature columns")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--round-trip-cost-pct", type=float, default=0.13)
    parser.add_argument("--min-margin-pct", type=float, default=0.30)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.rule_baseline_comparison import run_rule_baseline_comparison, write_rule_comparison_artifacts

    args = parse_args(argv)
    candidates = pd.read_csv(args.candidate_csv)
    features = _read_feature_sample(Path(args.feature_sample_path))
    summary = run_rule_baseline_comparison(
        candidates,
        features,
        horizon=int(args.horizon),
        round_trip_cost_pct=float(args.round_trip_cost_pct),
        min_margin_pct=float(args.min_margin_pct),
    )
    paths = write_rule_comparison_artifacts(summary, args.output_dir)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "decision": summary["decision"]["outcome"],
                "candidate_row_count": summary["coverage"]["candidate_row_count"],
                "joined_row_count": summary["coverage"]["joined_row_count"],
                "joined_date_count": summary["coverage"]["joined_date_count"],
                "production_evidence": summary["production_evidence"],
                "output_dir": str(args.output_dir),
                "artifacts": paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_feature_sample(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


if __name__ == "__main__":
    raise SystemExit(main())
