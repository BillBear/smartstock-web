#!/usr/bin/env python3
"""Write a bounded, read-only TuShare training-field lineage report."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.tushare_training_field_lineage_audit import (  # noqa: E402
    audit_tushare_training_field_lineage,
)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    output = Path(args.output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = audit_tushare_training_field_lineage(
        raw_root=args.raw_root,
        dataset_root=args.dataset_root,
        matrix_root=args.matrix_root,
        sample_dates=_parse_dates(args.sample_dates),
    )
    _write_output_atomically(output, report)
    print(
        json.dumps(
            {
                "overall_verdict": report["overall_verdict"],
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
    parser.add_argument("--raw-root", required=True, help="immutable TuShare raw asset root")
    parser.add_argument("--dataset-root", required=True, help="immutable full-market dataset root")
    parser.add_argument("--matrix-root", required=True, help="immutable feature-matrix root")
    parser.add_argument("--sample-dates", required=True, help="comma-separated YYYY-MM-DD trade dates")
    parser.add_argument("--output-dir", required=True, help="new caller-owned artifact directory")
    return parser


def _parse_dates(value: str) -> tuple[str, ...]:
    dates = tuple(item.strip() for item in str(value).split(",") if item.strip())
    if not dates:
        raise ValueError("sample-dates cannot be empty")
    return dates


def _write_output_atomically(output: Path, report: dict[str, object]) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_json(temporary / "lineage_report.json", report)
        _write_coverage_csv(temporary / "field_coverage.csv", report)
        os.replace(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_coverage_csv(path: Path, report: dict[str, object]) -> None:
    stages = report.get("stages", {})
    if not isinstance(stages, dict):
        raise ValueError("lineage report has invalid stages")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("stage", "field", "coverage", "non_null_count", "missing_from_schema"),
        )
        writer.writeheader()
        for stage_name, stage in sorted(stages.items()):
            if not isinstance(stage, dict):
                continue
            coverage = stage.get("field_coverage", {})
            counts = stage.get("non_null_counts", {})
            missing = set(stage.get("missing_columns", []))
            if not isinstance(coverage, dict) or not isinstance(counts, dict):
                continue
            for field in sorted(coverage):
                writer.writerow(
                    {
                        "stage": stage_name,
                        "field": field,
                        "coverage": coverage[field],
                        "non_null_count": counts.get(field, 0),
                        "missing_from_schema": field in missing,
                    }
                )


if __name__ == "__main__":
    raise SystemExit(main())
