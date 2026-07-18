#!/usr/bin/env python3
"""Derive a research-only ML sample contract from immutable asset evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.sample_contract_runner import derive_sample_contract


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, default=Path(os.environ.get("ML_ASSET_ROOT", "../ml-assets")))
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--label-run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, default=None)
    parser.add_argument("--security-state-asset", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=Path("config/ml-training-sample-certification-v1.json"))
    return parser.parse_args(argv)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _minimum_feature_coverage(path: Path) -> tuple[float, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("sample certification config must be a JSON object")
    minimum = float(value.get("minimum_feature_coverage", 0.0))
    if minimum != 0.95:
        raise ValueError("sample-contract derivation requires minimum_feature_coverage=0.95")
    return minimum, _sha256_file(path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        minimum_coverage, config_sha256 = _minimum_feature_coverage(args.config)
        result = derive_sample_contract(
            asset_root=args.asset_root,
            dataset_id=args.dataset_id,
            label_run_root=args.label_run_root,
            output_root=args.output_root,
            raw_root=args.raw_root,
            security_state_asset_root=args.security_state_asset,
            minimum_feature_coverage=minimum_coverage,
            derivation_policy_sha256=config_sha256,
        )
    except (FileNotFoundError, FileExistsError, ValueError, json.JSONDecodeError) as error:
        print(f"sample_contract_error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
