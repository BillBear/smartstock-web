from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run read-only A-share ML effectiveness audit.")
    parser.add_argument("--sample-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label-col", default="label_profit_quality_10d")
    parser.add_argument("--return-col", default="future_return_10d_pct")
    parser.add_argument("--round-trip-cost-pct", type=float, default=0.13)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.a_share_ml_effectiveness import run_effectiveness_audit, write_audit_artifacts

    args = parse_args(argv)
    frame = _read_sample(Path(args.sample_path))
    summary = run_effectiveness_audit(
        frame,
        label_col=args.label_col,
        return_col=args.return_col,
        round_trip_cost_pct=float(args.round_trip_cost_pct),
    )
    paths = write_audit_artifacts(summary, args.output_dir)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "row_count": summary["row_count"],
                "symbol_count": summary["symbol_count"],
                "date_count": summary["date_count"],
                "decision": summary["decision"]["outcome"],
                "v2_2_training_allowed": summary["decision"]["v2_2_training_allowed"],
                "output_dir": str(args.output_dir),
                "artifacts": paths,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_sample(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


if __name__ == "__main__":
    raise SystemExit(main())
