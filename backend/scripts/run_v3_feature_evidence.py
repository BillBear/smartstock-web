#!/usr/bin/env python3
"""Run read-only V3 feature evidence on registered walk-forward dates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.v3_feature_evidence import run_v3_feature_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset-root", required=True, type=Path)
    parser.add_argument("--feature-asset-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    report = run_v3_feature_evidence(
        source_dataset_root=args.source_dataset_root,
        feature_asset_root=args.feature_asset_root,
        output_root=args.output_root,
        code_commit=args.code_commit,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
