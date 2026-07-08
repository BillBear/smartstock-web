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
    parser = argparse.ArgumentParser(description="Run read-only ML V2.2 adjusted momentum experiment.")
    parser.add_argument("--candidate-csv", required=True)
    parser.add_argument("--enhanced-csv", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label-col", default="strong_10d")
    parser.add_argument("--return-col", default="return_10d_pct")
    parser.add_argument("--final-holdout-months", type=int, default=1)
    parser.add_argument("--stock-holdout-seed", type=int, default=20260708)
    parser.add_argument("--min-rows", type=int, default=1000)
    parser.add_argument("--min-dates", type=int, default=30)
    parser.add_argument("--min-symbols", type=int, default=300)
    parser.add_argument("--max-feature-missing-rate", type=float, default=0.35)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.local_ml_v2_2_adjusted import run_v22_adjusted_experiment

    args = parse_args(argv)
    candidate = _read_csv(Path(args.candidate_csv))
    enhanced = _read_csv(Path(args.enhanced_csv)) if args.enhanced_csv else None
    summary = run_v22_adjusted_experiment(
        candidate,
        enhanced,
        output_dir=Path(args.output_dir),
        label_col=args.label_col,
        return_col=args.return_col,
        final_holdout_months=args.final_holdout_months,
        stock_holdout_seed=args.stock_holdout_seed,
        min_rows=args.min_rows,
        min_dates=args.min_dates,
        min_symbols=args.min_symbols,
        max_feature_missing_rate=args.max_feature_missing_rate,
    )
    print(
        json.dumps(
            {
                "output_dir": str(Path(args.output_dir)),
                "production_enabled": bool(summary.get("production_enabled")),
                "strategy_impact": bool(summary.get("strategy_impact")),
                "quality_ready_for_training": bool((summary.get("quality") or {}).get("ready_for_training")),
                "training_status": (summary.get("training") or {}).get("status", "trained"),
                "summary_path": str(Path(args.output_dir) / "ml_v22_adjusted_summary.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return pd.read_csv(path)


if __name__ == "__main__":
    raise SystemExit(main())
