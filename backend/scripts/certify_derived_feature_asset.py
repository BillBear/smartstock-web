#!/usr/bin/env python3
"""Certify a new feature contract against an immutable existing feature matrix."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ``python scripts/...`` runs with the scripts directory on ``sys.path``.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.feature_materialization import certify_derived_feature_asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset-root", required=True, type=Path)
    parser.add_argument("--parent-feature-asset-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()

    manifest = certify_derived_feature_asset(
        source_dataset_root=args.source_dataset_root,
        parent_feature_asset_root=args.parent_feature_asset_root,
        output_root=args.output_root,
        code_commit=args.code_commit,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0 if manifest["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
