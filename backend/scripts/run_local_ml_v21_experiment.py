from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

import pandas as pd


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run Local Core ML V2.1 label/feature/weight/seed experiments.")
    parser.add_argument("--sample-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--labels", default="label_rank_top10_10d,label_alpha_top20_10d,label_trade_quality_10d,label_tp_before_sl_10d")
    parser.add_argument("--feature-groups", default="v2_full,v2_no_redundant,v2_tree_core")
    parser.add_argument("--weight-modes", default="none,date_stock_balanced")
    parser.add_argument("--stock-holdout-seeds", default="20260704,20260705,20260706")
    parser.add_argument("--max-experiments", type=int, default=0)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.local_ml_v2 import V2_FEATURE_NAMES
    from app.evaluation.local_ml_v2_1 import (
        build_v21_experiment_grid,
        feature_names_for_group,
        summarize_v21_results,
        write_v21_reports,
    )
    from app.evaluation.local_ml_trainer import train_local_models
    from app.evaluation.ml_splits import build_ml_split_plan

    args = parse_args(argv)
    frame = _read_sample(Path(args.sample_path))
    labels = _csv(args.labels)
    feature_groups = _csv(args.feature_groups)
    weight_modes = _csv(args.weight_modes)
    seeds = [int(item) for item in _csv(args.stock_holdout_seeds)]
    grid = build_v21_experiment_grid(labels, feature_groups, weight_modes, seeds)
    if args.max_experiments and args.max_experiments > 0:
        grid = grid[: int(args.max_experiments)]

    results = []
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for experiment in grid:
        label_col = experiment["label_col"]
        feature_names = feature_names_for_group(experiment["feature_group"], V2_FEATURE_NAMES)
        missing = [column for column in [label_col, "future_return_10d_pct", *feature_names] if column not in frame.columns]
        if missing:
            results.append({**experiment, "status": "skipped", "reason": f"missing_columns:{','.join(missing[:5])}"})
            continue
        local = frame[frame[label_col].notna()].copy()
        split_plan = build_ml_split_plan(
            local,
            final_holdout_months=3,
            stock_holdout_ratio=0.20,
            walk_forward_splits=5,
            label_horizon_days=10,
            stock_holdout_seed=experiment["stock_holdout_seed"],
        )
        comparison = train_local_models(
            local,
            feature_names=feature_names,
            label_col=label_col,
            return_col="future_return_10d_pct",
            split_plan=split_plan,
            candidate_set="core_v2",
            sample_weight_mode=experiment["sample_weight_mode"],
        )
        best = comparison["models"][comparison["best_model"]]
        results.append(
            {
                **experiment,
                "status": "trained",
                "best_model": comparison["best_model"],
                "feature_count": len(feature_names),
                "metrics": {
                    "final_holdout": best.get("final_holdout") or {},
                    "stock_holdout": best.get("stock_holdout") or {},
                    "walk_forward": best.get("walk_forward") or {},
                },
                "models": comparison.get("models") or {},
            }
        )

    summary = summarize_v21_results(results)
    paths = write_v21_reports(summary, output_dir)
    print(json.dumps({"output_dir": str(output_dir), **paths, "production_ready": summary["production_ready"], "experiment_count": summary["experiment_count"]}, ensure_ascii=False))
    return 0


def _read_sample(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _csv(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
