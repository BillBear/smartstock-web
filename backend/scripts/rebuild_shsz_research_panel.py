#!/usr/bin/env python3
"""Build an immutable SH/SZ-only research panel from certified raw data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.shsz_panel_rebuild import rebuild_shsz_research_panel  # noqa: E402


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    report = rebuild_shsz_research_panel(
        source_run_root=args.source_run_root,
        universe_contract_path=args.universe_contract,
        output_dir=args.output_dir,
        code_commit=args.code_commit,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "research_ready": report["research_ready"],
                "output_dir": str(Path(args.output_dir).expanduser().resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-root", required=True, help="immutable full-market raw source run")
    parser.add_argument("--universe-contract", required=True, help="certified SH/SZ universe_contract.json")
    parser.add_argument("--output-dir", required=True, help="new non-existent SH/SZ derived run directory")
    parser.add_argument("--code-commit", required=True, help="rebuild code commit")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
