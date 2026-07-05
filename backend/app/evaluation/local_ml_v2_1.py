from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from app.evaluation.local_ml_v2 import V2_FEATURE_NAMES


V21_LABELS = [
    "label_rank_top10_10d",
    "label_alpha_top20_10d",
    "label_trade_quality_10d",
    "label_tp_before_sl_10d",
]

REDUNDANT_DROP_FEATURES = {
    "amount_log",
    "return_60d_pct",
    "ma20_gap_pct",
    "volatility_20d",
    "return_10d_pct",
}

TREE_CORE_FEATURES = [
    "atr_14_pct",
    "return_60d_rank",
    "recovery_from_20d_low_pct",
    "intraday_range_pct",
    "ma60_gap_pct",
    "trend_slope_20d",
    "return_20d_rank",
    "amount_pct_rank",
    "rsi",
]


def feature_names_for_group(group: str, base_features: Iterable[str] | None = None) -> List[str]:
    features = list(base_features or V2_FEATURE_NAMES)
    group_key = str(group or "v2_full")
    if group_key == "v2_full":
        return features
    if group_key == "v2_no_redundant":
        return [feature for feature in features if feature not in REDUNDANT_DROP_FEATURES]
    if group_key == "v2_tree_core":
        return [feature for feature in TREE_CORE_FEATURES if feature in set(features)]
    raise ValueError(f"Unknown V2.1 feature group: {group}")


def build_v21_experiment_grid(
    labels: Iterable[str] | None = None,
    feature_groups: Iterable[str] | None = None,
    weight_modes: Iterable[str] | None = None,
    stock_holdout_seeds: Iterable[int] | None = None,
) -> List[Dict[str, Any]]:
    labels = list(labels or V21_LABELS)
    feature_groups = list(feature_groups or ["v2_full", "v2_no_redundant", "v2_tree_core"])
    weight_modes = list(weight_modes or ["none", "date_stock_balanced"])
    stock_holdout_seeds = [int(seed) for seed in (stock_holdout_seeds or [20260704, 20260705, 20260706])]
    experiments: List[Dict[str, Any]] = []
    for label in labels:
        for feature_group in feature_groups:
            for weight_mode in weight_modes:
                for seed in stock_holdout_seeds:
                    experiments.append(
                        {
                            "experiment_id": f"{label}__{feature_group}__{weight_mode}__seed{seed}",
                            "label_col": label,
                            "feature_group": feature_group,
                            "sample_weight_mode": weight_mode,
                            "stock_holdout_seed": seed,
                        }
                    )
    return experiments


def summarize_v21_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {
            "experiment_count": 0,
            "production_ready": False,
            "blocking_reasons": ["no_experiment_results"],
            "best_experiment": None,
            "results": [],
        }
    ranked = sorted(results, key=_result_score, reverse=True)
    best = ranked[0]
    blocking = []
    labels = {str(item.get("label_col")) for item in results if item.get("status") != "skipped"}
    feature_groups = {str(item.get("feature_group")) for item in results if item.get("status") != "skipped"}
    weight_modes = {str(item.get("sample_weight_mode")) for item in results if item.get("status") != "skipped"}
    seeds = {str(item.get("stock_holdout_seed")) for item in results if item.get("status") != "skipped"}
    if len(labels) < 4 or len(feature_groups) < 2 or len(weight_modes) < 2 or len(seeds) < 3:
        blocking.append("incomplete_v21_matrix")
    if _metric(best, "stock_holdout", "topk_return") <= 0 or _metric(best, "walk_forward", "topk_return") <= 0:
        blocking.append("stock_or_walk_forward_return_not_positive")
    if min(
        _metric(best, "final_holdout", "precision_at_5"),
        _metric(best, "stock_holdout", "precision_at_5"),
        _metric(best, "walk_forward", "precision_at_5"),
    ) < 0.20:
        blocking.append("precision_at_5_not_consistently_above_0_20")
    if _metric(best, "stock_holdout", "ndcg_at_10") <= 0.18:
        blocking.append("stock_holdout_ndcg_too_weak")
    return {
        "experiment_count": len(results),
        "production_ready": not blocking,
        "blocking_reasons": blocking,
        "best_experiment": best,
        "top_experiments": ranked[:10],
        "results": results,
    }


def write_v21_reports(summary: Dict[str, Any], output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "v21_experiment_summary.json"
    md_path = root / "v21_experiment_summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_summary_markdown(summary), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _result_score(result: Dict[str, Any]) -> tuple:
    stock_return = _metric(result, "stock_holdout", "topk_return")
    walk_return = _metric(result, "walk_forward", "topk_return")
    return_positive = 1 if stock_return > 0 and walk_return > 0 else 0
    return (
        return_positive,
        min(
            _metric(result, "final_holdout", "precision_at_5"),
            _metric(result, "stock_holdout", "precision_at_5"),
            _metric(result, "walk_forward", "precision_at_5"),
        ),
        stock_return + walk_return,
        stock_return,
        walk_return,
        _metric(result, "final_holdout", "precision_at_5"),
    )


def _metric(result: Dict[str, Any], split: str, key: str) -> float:
    try:
        return float(((result.get("metrics") or {}).get(split) or {}).get(key) or 0.0)
    except Exception:
        return 0.0


def _summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Local Core ML V2.1 Experiment Summary",
        "",
        f"production_ready: `{summary.get('production_ready')}`",
        f"experiment_count: `{summary.get('experiment_count')}`",
        "",
        "## Blocking Reasons",
    ]
    blocking = summary.get("blocking_reasons") or []
    lines.extend([f"- `{item}`" for item in blocking] if blocking else ["- none"])
    lines.extend(["", "## Top Experiments", "", "| Rank | Experiment | Model | Final P@5 | Stock P@5 | Walk P@5 | Stock Ret | Walk Ret |", "|---:|---|---|---:|---:|---:|---:|---:|"])
    for index, item in enumerate(summary.get("top_experiments") or [], start=1):
        lines.append(
            "| {rank} | `{exp}` | `{model}` | {final_p5} | {stock_p5} | {walk_p5} | {stock_ret} | {walk_ret} |".format(
                rank=index,
                exp=item.get("experiment_id"),
                model=item.get("best_model"),
                final_p5=_metric(item, "final_holdout", "precision_at_5"),
                stock_p5=_metric(item, "stock_holdout", "precision_at_5"),
                walk_p5=_metric(item, "walk_forward", "precision_at_5"),
                stock_ret=_metric(item, "stock_holdout", "topk_return"),
                walk_ret=_metric(item, "walk_forward", "topk_return"),
            )
        )
    return "\n".join(lines) + "\n"
