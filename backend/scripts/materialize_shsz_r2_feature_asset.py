#!/usr/bin/env python3
"""Build a research-only SH/SZ R2 feature asset from R1 inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.shsz_feature_asset import materialize_shsz_feature_asset  # noqa: E402


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", required=True, type=Path)
    parser.add_argument("--label-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--parity-dates", required=True, help="three comma-separated ISO development dates")
    parser.add_argument("--materialized-shard-count", type=int, default=16)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = materialize_shsz_feature_asset(
        panel_root=args.panel_root,
        label_root=args.label_root,
        output_dir=args.output_dir,
        code_commit=args.code_commit,
        parity_dates=tuple(value.strip() for value in args.parity_dates.split(",") if value.strip()),
        materialized_shard_count=args.materialized_shard_count,
    )
    print(json.dumps({"status": report["status"], "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
