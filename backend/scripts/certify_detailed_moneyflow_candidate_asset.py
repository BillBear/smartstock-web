#!/usr/bin/env python3
"""Certify an immutable detailed-moneyflow candidate asset without training it."""
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

from app.evaluation.full_market_ml.detailed_moneyflow_candidate_asset import (  # noqa: E402
    inspect_detailed_moneyflow_candidate_asset,
)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    output = Path(args.output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = inspect_detailed_moneyflow_candidate_asset(
        source_run_root=args.source_run_root,
        code_commit=args.code_commit,
        parity_dates=_parse_dates(args.parity_dates),
    )
    _write_output_atomically(output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "training_ready": report["training_ready"],
                "production_integration_allowed": report["production_integration_allowed"],
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
    parser.add_argument("--output-dir", required=True, help="new caller-owned candidate artifact directory")
    parser.add_argument("--code-commit", required=True, help="certifier code commit")
    parser.add_argument("--parity-dates", default="", help="optional comma-separated YYYY-MM-DD dates")
    return parser


def _parse_dates(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def _write_output_atomically(output: Path, report: Mapping[str, object]) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_json(temporary / "candidate_asset_manifest.json", report)
        _write_coverage_csv(temporary / "field_coverage.csv", report)
        _write_json(temporary / "parity_report.json", _mapping(report.get("parity"), "parity"))
        _write_json(
            temporary / "progress.json",
            {
                "status": "complete",
                "stage": "detailed_moneyflow_candidate_asset_certification",
                "candidate_status": report.get("status"),
                "training_ready": report.get("training_ready"),
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


def _write_coverage_csv(path: Path, report: Mapping[str, object]) -> None:
    coverage = _mapping(report.get("field_coverage"), "field_coverage")
    columns = (
        "field",
        "all_rows_coverage",
        "eligible_rows_coverage",
        "per_date_minimum_coverage",
        "per_date_median_coverage",
        "warmup_or_derived_null_count",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for field, entry in sorted(coverage.items()):
            if field.startswith("_"):
                continue
            detail = _mapping(entry, f"field_coverage.{field}")
            all_rows = _mapping(detail.get("all_rows"), f"field_coverage.{field}.all_rows")
            eligible_rows = _mapping(detail.get("eligible_rows"), f"field_coverage.{field}.eligible_rows")
            per_date = _mapping(detail.get("per_date_coverage"), f"field_coverage.{field}.per_date_coverage")
            writer.writerow(
                {
                    "field": field,
                    "all_rows_coverage": all_rows.get("coverage"),
                    "eligible_rows_coverage": eligible_rows.get("coverage"),
                    "per_date_minimum_coverage": per_date.get("minimum"),
                    "per_date_median_coverage": per_date.get("median"),
                    "warmup_or_derived_null_count": detail.get("warmup_or_derived_null_count"),
                }
            )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"candidate report has invalid {label}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
