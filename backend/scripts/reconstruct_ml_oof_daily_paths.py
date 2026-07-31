"""CLI for research-only immutable OOF daily path reconstruction."""
from __future__ import annotations

import argparse
import json
from typing import Iterable

from app.evaluation.ml_oof_daily_path import run_oof_daily_path_reconstruction


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-root", required=True)
    parser.add_argument("--feature-asset-root", required=True)
    parser.add_argument("--panel-root", required=True)
    parser.add_argument("--candidate-run-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--code-commit", required=True)
    return parser.parse_args(argv)


def run(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_oof_daily_path_reconstruction(
        label_root=args.label_root,
        feature_asset_root=args.feature_asset_root,
        panel_root=args.panel_root,
        candidate_run_root=args.candidate_run_root,
        output_dir=args.output_dir,
        code_commit=args.code_commit,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "candidate_screen_status": report["candidate_screen_status"],
                "portfolio_metrics_available": report["portfolio_metrics_available"],
                "production_integration_allowed": report["production_integration_allowed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
