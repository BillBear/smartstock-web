#!/usr/bin/env python3
"""Run the sealed ML recovery acceptance baseline without production switches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.ml_recovery_acceptance import run_ml_recovery_acceptance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-root", required=True, help="sealed R1 development labels directory")
    parser.add_argument("--feature-asset-root", required=True, help="sealed R2 feature asset directory")
    parser.add_argument("--panel-root", required=True, help="certified SH/SZ panel directory")
    parser.add_argument("--output-dir", required=True, help="new local artifact directory")
    parser.add_argument("--code-commit", required=True, help="Git commit that defines the run")
    args = parser.parse_args()

    report = run_ml_recovery_acceptance(
        label_root=args.label_root,
        feature_asset_root=args.feature_asset_root,
        panel_root=args.panel_root,
        output_dir=args.output_dir,
        code_commit=args.code_commit,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "research_only": report["research_only"],
                "candidate_status": report["candidate_screen"]["status"],
                "production_integration_allowed": report["production_integration_allowed"],
                "output_dir": str(Path(args.output_dir).expanduser().resolve()),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
