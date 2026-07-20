#!/usr/bin/env python3
"""Certify the immutable SH/SZ-only research universe from raw partitions."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.shsz_research_universe import certify_shsz_research_universe  # noqa: E402


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    output = Path(args.output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = certify_shsz_research_universe(source_run_root=args.source_run_root, code_commit=args.code_commit)
    _write_output_atomically(output, report)
    print(json.dumps({"status": report["status"], "research_ready": report["research_ready"], "output_dir": str(output)}, ensure_ascii=False, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-root", required=True, help="immutable all-market source run")
    parser.add_argument("--output-dir", required=True, help="new caller-owned contract output directory")
    parser.add_argument("--code-commit", required=True, help="certifier code commit")
    return parser


def _write_output_atomically(output: Path, report: Mapping[str, object]) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_json(temporary / "universe_contract.json", report)
        _write_daily_coverage(temporary / "daily_coverage.csv", report.get("daily_coverage"))
        _write_json(
            temporary / "progress.json",
            {
                "status": "complete",
                "stage": "shsz_research_universe_certification",
                "universe_status": report.get("status"),
                "research_ready": report.get("research_ready"),
                "production_integration_allowed": report.get("production_integration_allowed"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_daily_coverage(path: Path, value: object) -> None:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ValueError("report daily_coverage must be a list of mappings")
    columns = (
        "trade_date",
        "historical_expected_count",
        "raw_shsz_daily_count",
        "daily_observed_count",
        "daily_historical_coverage",
        "unresolved_daily_master_count",
        "missing_daily_symbol_count",
        "detailed_moneyflow_covered_count",
        "missing_moneyflow_symbol_count",
        "null_detailed_moneyflow_count",
        "detailed_moneyflow_coverage",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in value:
            writer.writerow({column: row.get(column) for column in columns})


if __name__ == "__main__":
    raise SystemExit(main())
