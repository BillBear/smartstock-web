#!/usr/bin/env python3
"""Run development-only market and industry context feature evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.context_feature_audit_runner import run_context_feature_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset-root", required=True, type=Path)
    parser.add_argument("--feature-asset-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--smoke", action="store_true", help="Use one registered validation date per fold for a bounded research smoke run.")
    args = parser.parse_args()
    report = run_context_feature_audit(
        source_dataset_root=args.source_dataset_root,
        feature_asset_root=args.feature_asset_root,
        output_root=args.output_root,
        code_commit=args.code_commit,
        smoke=args.smoke,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
