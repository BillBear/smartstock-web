#!/usr/bin/env python3
"""Run the read-only, development-only SH/SZ market-state baseline audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.shsz_market_state_audit import run_shsz_market_state_audit  # noqa: E402


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-root", required=True, type=Path)
    parser.add_argument("--feature-asset-root", required=True, type=Path)
    parser.add_argument("--panel-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=1_000)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_shsz_market_state_audit(
        label_root=args.label_root,
        feature_asset_root=args.feature_asset_root,
        panel_root=args.panel_root,
        output_dir=args.output_dir,
        code_commit=args.code_commit,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "research_status": report["candidate_screen"]["status"],
                "production_integration_allowed": False,
                "output_dir": str(args.output_dir.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
