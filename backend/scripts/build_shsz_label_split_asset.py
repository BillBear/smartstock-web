#!/usr/bin/env python3
"""Create a development-only label and split asset for a certified SH/SZ panel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.shsz_label_split_asset import build_shsz_label_split_asset  # noqa: E402


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    report = build_shsz_label_split_asset(
        panel_root=args.panel_root,
        output_dir=args.output_dir,
        code_commit=args.code_commit,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "dataset_id": report["output"]["dataset_id"],
                "output_dir": str(Path(args.output_dir).expanduser().resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", required=True, help="certified SH/SZ panel run directory")
    parser.add_argument("--output-dir", required=True, help="new non-existent development-label asset directory")
    parser.add_argument("--code-commit", required=True, help="label-builder code commit")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
