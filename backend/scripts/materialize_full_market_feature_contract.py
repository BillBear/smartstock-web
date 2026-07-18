#!/usr/bin/env python3
"""Materialize an immutable V2 feature asset from a certified full-market panel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.feature_materialization import materialize_feature_asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--shard-count", type=int, default=16)
    args = parser.parse_args()
    report = materialize_feature_asset(
        source_dataset_root=args.source_dataset_root,
        output_root=args.output_root,
        code_commit=args.code_commit,
        shard_count=args.shard_count,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
