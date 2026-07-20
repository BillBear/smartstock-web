#!/usr/bin/env python3
"""Write a read-only detailed-moneyflow coverage forensics report."""
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

from app.evaluation.full_market_ml.moneyflow_coverage_forensics import audit_moneyflow_coverage  # noqa: E402


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    output = Path(args.output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = audit_moneyflow_coverage(source_run_root=args.source_run_root, code_commit=args.code_commit)
    _write_output_atomically(output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "full_universe_detailed_coverage": report["full_universe_detailed_coverage"],
                "output_dir": str(output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-root", required=True, help="immutable full-market source run")
    parser.add_argument("--output-dir", required=True, help="new caller-owned forensics output directory")
    parser.add_argument("--code-commit", required=True, help="forensics code commit")
    return parser


def _write_output_atomically(output: Path, report: Mapping[str, object]) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_json(temporary / "coverage_forensics_report.json", report)
        _write_daily_coverage_csv(temporary / "daily_coverage.csv", _list_of_mappings(report.get("daily_coverage"), "daily_coverage"))
        _write_board_summary_csv(temporary / "board_cause_summary.csv", _mapping(report.get("board_cause_counts"), "board_cause_counts"))
        _write_json(
            temporary / "progress.json",
            {
                "status": "complete",
                "stage": "moneyflow_coverage_forensics",
                "forensics_status": report.get("status"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_daily_coverage_csv(path: Path, rows: list[Mapping[str, object]]) -> None:
    columns = (
        "trade_date",
        "daily_count",
        "covered",
        "missing_moneyflow_partition",
        "missing_moneyflow_symbol",
        "null_detailed_field",
        "detailed_moneyflow_coverage",
        "moneyflow_partition_present",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_board_summary_csv(path: Path, counts: Mapping[str, object]) -> None:
    columns = ("board", "covered", "missing_moneyflow_partition", "missing_moneyflow_symbol", "null_detailed_field")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for board, entry in sorted(counts.items()):
            values = _mapping(entry, f"board_cause_counts.{board}")
            writer.writerow({"board": board, **{column: values.get(column, 0) for column in columns if column != "board"}})


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"forensics report has invalid {label}")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"forensics report has invalid {label}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
