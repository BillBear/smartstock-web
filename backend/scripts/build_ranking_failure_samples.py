#!/usr/bin/env python3
"""Build reviewable ranking failure samples from controlled OOF artifacts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.failure_analysis import build_failure_samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument(
        "--baseline", action="append", dest="baselines", default=[]
    )
    args = parser.parse_args(argv)
    baselines = tuple(args.baselines or ("amount_descending", "adjusted_return_20d"))
    artifact_root = args.run_root / "artifacts"
    predictions = pd.read_parquet(
        artifact_root / "baseline-oof" / "baseline_predictions.parquet"
    )
    samples, summary = build_failure_samples(predictions, baselines=baselines)
    controlled = json.loads(
        (artifact_root / "controlled-evaluation" / "controlled_report.json").read_text(
            encoding="utf-8"
        )
    )
    summary["untradeable_entry_counts"] = {
        quadrant: {
            baseline: {
                gate: int(metrics[gate]["untradeable_entry_count"])
                for gate in ("raw", "same_risk_gated")
            }
            for baseline, metrics in comparisons.items()
        }
        for quadrant, comparisons in controlled["portfolios"].items()
    }
    output_root = artifact_root / "controlled-evaluation"
    csv_path = output_root / "failure_samples.csv"
    json_path = output_root / "failure_sample_summary.json"
    samples.to_csv(csv_path, index=False)
    _write_json_atomic(json_path, summary)
    print(
        json.dumps(
            {"csv": str(csv_path), "json": str(json_path), "row_count": len(samples)},
            sort_keys=True,
        )
    )
    return 0


def _write_json_atomic(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
