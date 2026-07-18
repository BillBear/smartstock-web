#!/usr/bin/env python3
"""Run pre-registered, development-only train-only scorecard OOF evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.train_only_scorecard_oof import run_train_only_scorecard_oof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset-root", required=True, type=Path)
    parser.add_argument("--feature-asset-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args()
    report = run_train_only_scorecard_oof(
        source_dataset_root=args.source_dataset_root,
        feature_asset_root=args.feature_asset_root,
        output_root=args.output_root,
        code_commit=args.code_commit,
        bootstrap_iterations=max(1, int(args.bootstrap_iterations)),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
