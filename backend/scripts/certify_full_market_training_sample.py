"""Create a read-only certification for an immutable full-market ML dataset."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.sample_certification_runner import run_certification


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/ml-training-sample-certification-v1.json"))
    parser.add_argument("--asset-root", type=Path, default=Path(os.environ.get("ML_ASSET_ROOT", "../ml-assets")))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--secondary-label-audit", type=Path, default=None)
    parser.add_argument("--security-provenance", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_root = args.output_root or args.asset_root / "certifications"
    try:
        result = run_certification(
            config_path=args.config,
            asset_root=args.asset_root,
            output_root=output_root,
            secondary_label_audit_path=args.secondary_label_audit,
            security_provenance_path=args.security_provenance,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"certification_error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["certificate"]["status"] == "certified_research_sample" else 2


if __name__ == "__main__":
    raise SystemExit(main())
