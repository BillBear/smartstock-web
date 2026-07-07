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
    parser = argparse.ArgumentParser(description="Audit full-market to candidate-pool funnel outcomes.")
    parser.add_argument("--feature-panel", required=True)
    parser.add_argument("--label-panel", required=True)
    parser.add_argument("--candidate-features", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--top-rank-cutoff", type=int, default=10)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap()
    from app.evaluation.universe_funnel_audit import (
        audit_universe_funnel,
        build_universe_from_feature_and_label_panels,
        write_universe_funnel_artifacts,
    )

    args = parse_args(argv)
    feature_panel = pd.read_csv(args.feature_panel)
    label_panel = pd.read_csv(args.label_panel)
    candidates = pd.read_csv(args.candidate_features)
    universe = build_universe_from_feature_and_label_panels(feature_panel, label_panel)
    report = audit_universe_funnel(
        universe,
        candidates,
        horizon=int(args.horizon),
        top_rank_cutoff=int(args.top_rank_cutoff),
    )
    paths = write_universe_funnel_artifacts(report, args.output_dir)
    print(json.dumps({"status": "completed", **report["summary"], "artifacts": paths}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
