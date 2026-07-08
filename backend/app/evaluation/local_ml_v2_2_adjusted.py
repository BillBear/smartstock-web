from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from app.evaluation.local_ml_trainer import daily_ranking_metrics, train_local_models
from app.evaluation.ml_splits import build_ml_split_plan


V22_ADJUSTED_FEATURE_SPECS: List[Dict[str, str]] = [
    {"name": "adj_return_5d_rank", "category": "adjusted_momentum", "description": "Adjusted 5-day return percentile rank."},
    {"name": "adj_return_20d_rank", "category": "adjusted_momentum", "description": "Adjusted 20-day return percentile rank."},
    {"name": "adj_return_60d_rank", "category": "adjusted_momentum", "description": "Adjusted 60-day return percentile rank."},
    {"name": "adj_return_60d_pct", "category": "adjusted_momentum", "description": "Adjusted 60-day return percentage."},
    {"name": "adj_momentum_accel_5_20", "category": "adjusted_momentum", "description": "Adjusted 5-day rank minus adjusted 20-day rank."},
    {"name": "adj_momentum_accel_20_60", "category": "adjusted_momentum", "description": "Adjusted 20-day rank minus adjusted 60-day rank."},
    {"name": "turnover_rate_rank", "category": "activity", "description": "Daily turnover percentile rank."},
    {"name": "turnover_rate_f_rank", "category": "activity", "description": "Daily free-float turnover percentile rank."},
    {"name": "volume_ratio_rank", "category": "activity", "description": "Daily volume ratio percentile rank."},
    {"name": "main_net_inflow_ratio_rank", "category": "moneyflow", "description": "Main moneyflow ratio percentile rank."},
    {"name": "limit_buyability_rank", "category": "tradability", "description": "Distance-to-limit buyability percentile rank."},
    {"name": "distance_to_up_limit_pct", "category": "tradability", "description": "Distance to涨停 percentage."},
    {"name": "return_20d_rank", "category": "legacy_momentum", "description": "Legacy 20-day return percentile rank."},
    {"name": "return_60d_rank", "category": "legacy_momentum", "description": "Legacy 60-day return percentile rank."},
    {"name": "amount_pct_rank", "category": "liquidity", "description": "Daily amount percentile rank."},
    {"name": "amount_ratio_5_20", "category": "liquidity", "description": "5-day amount average versus 20-day average."},
    {"name": "rsi", "category": "technical", "description": "RSI technical state."},
    {"name": "macd_hist", "category": "technical", "description": "MACD histogram."},
    {"name": "atr_14_pct", "category": "risk", "description": "14-day ATR percentage."},
    {"name": "volatility_20d", "category": "risk", "description": "20-day realized volatility."},
    {"name": "trend_slope_20d", "category": "trend", "description": "20-day trend slope."},
    {"name": "trend_r2_20d", "category": "trend", "description": "20-day trend fit quality."},
    {"name": "intraday_range_pct", "category": "risk", "description": "Current high-low range percentage."},
    {"name": "factor_total_score", "category": "legacy_context", "description": "Existing factor total score as context only."},
    {"name": "score", "category": "legacy_context", "description": "Existing SmartStock score as context only."},
]

V22_ADJUSTED_FEATURE_NAMES = [item["name"] for item in V22_ADJUSTED_FEATURE_SPECS]

FORBIDDEN_FEATURE_TOKENS = (
    "future_",
    "label_",
    "strong_",
    "tp_before",
    "sl_before",
    "max_floating_profit",
    "max_adverse",
    "path_max_drawdown",
    "return_3d_pct",
    "return_5d_pct",
    "return_10d_pct",
    "return_20d_pct",
)


def prepare_v22_adjusted_dataset(
    candidate_panel: pd.DataFrame,
    enhanced_panel: pd.DataFrame | None = None,
    label_col: str = "strong_10d",
    return_col: str = "return_10d_pct",
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    """Prepare a read-only candidate-level V2.2 ML dataset."""
    base = _normalize_panel(candidate_panel)
    if base.empty:
        return pd.DataFrame(), [], _base_report(0, [], {})
    enhanced = _normalize_panel(enhanced_panel)
    if not enhanced.empty:
        enhanced_columns = [
            column
            for column in enhanced.columns
            if column in {"symbol", "date"} or column in set(V22_ADJUSTED_FEATURE_NAMES)
        ]
        if len(enhanced_columns) > 2:
            slim = enhanced[enhanced_columns].drop_duplicates(["symbol", "date"], keep="last")
            overlap = [column for column in slim.columns if column not in {"symbol", "date"} and column in base.columns]
            if overlap:
                base = base.drop(columns=overlap)
            base = base.merge(slim, on=["symbol", "date"], how="left")

    dataset = base.sort_values(["date", "symbol"]).reset_index(drop=True)
    if label_col in dataset.columns:
        dataset[label_col] = pd.to_numeric(dataset[label_col], errors="coerce")
    if return_col in dataset.columns:
        dataset[return_col] = pd.to_numeric(dataset[return_col], errors="coerce")

    _attach_adjusted_acceleration_features(dataset)
    feature_names = _available_feature_names(dataset)
    for feature in feature_names:
        dataset[feature] = pd.to_numeric(dataset[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)

    missing_rates = {
        feature: round(float(dataset[feature].isna().mean()), 6)
        for feature in feature_names
        if feature in dataset.columns
    }
    report = _base_report(len(dataset), feature_names, missing_rates)
    report.update(
        {
            "date_count": int(dataset["date"].nunique()) if "date" in dataset.columns else 0,
            "symbol_count": int(dataset["symbol"].nunique()) if "symbol" in dataset.columns else 0,
            "label_col": label_col,
            "return_col": return_col,
            "label_non_null_count": int(dataset[label_col].notna().sum()) if label_col in dataset.columns else 0,
            "return_non_null_count": int(dataset[return_col].notna().sum()) if return_col in dataset.columns else 0,
        }
    )
    return dataset, feature_names, report


def evaluate_v22_dataset_quality(
    df: pd.DataFrame,
    feature_names: List[str],
    label_col: str,
    return_col: str,
    min_rows: int = 1000,
    min_dates: int = 30,
    min_symbols: int = 300,
    max_feature_missing_rate: float = 0.35,
) -> Dict[str, Any]:
    local = df.copy() if df is not None else pd.DataFrame()
    reasons: List[str] = []
    row_count = int(len(local))
    date_count = int(local["date"].nunique()) if "date" in local.columns else 0
    symbol_count = int(local["symbol"].nunique()) if "symbol" in local.columns else 0
    if row_count < int(min_rows):
        reasons.append("row_count_below_minimum")
    if date_count < int(min_dates):
        reasons.append("date_count_below_minimum")
    if symbol_count < int(min_symbols):
        reasons.append("symbol_count_below_minimum")
    if label_col not in local.columns:
        reasons.append("missing_label_column")
        label_rate = 0.0
        label_non_null_count = 0
        label_class_count = 0
    else:
        labels = pd.to_numeric(local[label_col], errors="coerce")
        label_non_null_count = int(labels.notna().sum())
        label_rate = round(float(labels.dropna().mean()), 6) if label_non_null_count else 0.0
        label_class_count = int(labels.dropna().astype(int).nunique()) if label_non_null_count else 0
        if label_non_null_count == 0:
            reasons.append("label_column_empty")
        if label_class_count < 2:
            reasons.append("label_has_single_class")
        if label_rate <= 0.01 or label_rate >= 0.99:
            reasons.append("label_rate_extreme")
    if return_col not in local.columns:
        reasons.append("missing_return_column")
        return_non_null_count = 0
    else:
        returns = pd.to_numeric(local[return_col], errors="coerce")
        return_non_null_count = int(returns.notna().sum())
        if return_non_null_count == 0:
            reasons.append("return_column_empty")

    forbidden = _forbidden_feature_names(feature_names)
    if forbidden:
        reasons.append("forbidden_feature_leakage")
    missing_features = [feature for feature in feature_names if feature not in local.columns]
    if missing_features:
        reasons.append("missing_feature_columns")
    feature_missing_rates = {}
    high_missing = []
    for feature in feature_names:
        if feature not in local.columns:
            continue
        values = pd.to_numeric(local[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
        missing_rate = float(values.isna().mean()) if len(values) else 1.0
        feature_missing_rates[feature] = round(missing_rate, 6)
        if missing_rate > float(max_feature_missing_rate):
            high_missing.append(feature)
    if high_missing:
        reasons.append("feature_missing_rate_above_threshold")
    return {
        "ready_for_training": not reasons,
        "production_ready": False,
        "production_enabled": False,
        "strategy_impact": False,
        "production_action": "do_not_change_strategy",
        "blocking_reasons": reasons,
        "row_count": row_count,
        "date_count": date_count,
        "symbol_count": symbol_count,
        "label_col": label_col,
        "return_col": return_col,
        "label_non_null_count": label_non_null_count,
        "return_non_null_count": return_non_null_count,
        "label_rate": label_rate,
        "label_class_count": label_class_count,
        "feature_count": len(feature_names),
        "forbidden_features": forbidden,
        "missing_features": missing_features,
        "high_missing_features": high_missing[:20],
        "feature_missing_rates": feature_missing_rates,
    }


def validate_v22_split_integrity(df: pd.DataFrame, split_plan: Dict[str, Any]) -> Dict[str, Any]:
    training_dates = set(str(item) for item in split_plan.get("training_dates") or [])
    training_symbols = set(str(item) for item in split_plan.get("training_symbols") or [])
    final_dates = set(str(item) for item in ((split_plan.get("final_holdout") or {}).get("dates") or []))
    holdout_symbols = set(str(item) for item in ((split_plan.get("stock_holdout") or {}).get("symbols") or []))
    training_final_overlap = training_dates & final_dates
    training_stock_overlap = training_symbols & holdout_symbols
    walk_reasons: List[str] = []
    for window in (split_plan.get("walk_forward") or {}).get("windows") or []:
        train_dates = set(str(item) for item in window.get("train_dates") or [])
        validation_dates = set(str(item) for item in window.get("validation_dates") or [])
        embargo_dates = set(str(item) for item in window.get("embargo_dates") or [])
        if train_dates & validation_dates:
            walk_reasons.append(f"window_{window.get('window')}_train_validation_overlap")
        if train_dates & embargo_dates:
            walk_reasons.append(f"window_{window.get('window')}_train_embargo_overlap")
    reasons = []
    if training_final_overlap:
        reasons.append("training_final_date_overlap")
    if training_stock_overlap:
        reasons.append("training_stock_holdout_symbol_overlap")
    reasons.extend(walk_reasons)
    return {
        "valid": not reasons,
        "blocking_reasons": reasons,
        "training_date_count": len(training_dates),
        "final_holdout_date_count": len(final_dates),
        "training_symbol_count": len(training_symbols),
        "stock_holdout_symbol_count": len(holdout_symbols),
        "training_final_date_overlap_count": len(training_final_overlap),
        "training_stock_holdout_symbol_overlap_count": len(training_stock_overlap),
        "walk_forward_window_count": len((split_plan.get("walk_forward") or {}).get("windows") or []),
    }


def run_v22_adjusted_experiment(
    candidate_panel: pd.DataFrame,
    enhanced_panel: pd.DataFrame | None,
    output_dir: str | Path,
    label_col: str = "strong_10d",
    return_col: str = "return_10d_pct",
    final_holdout_months: int = 1,
    stock_holdout_seed: int = 20260708,
    min_rows: int = 1000,
    min_dates: int = 30,
    min_symbols: int = 300,
    max_feature_missing_rate: float = 0.35,
) -> Dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    dataset, feature_names, dataset_report = prepare_v22_adjusted_dataset(candidate_panel, enhanced_panel, label_col, return_col)
    dataset.to_csv(root / "ml_v22_adjusted_dataset.csv", index=False)
    quality = evaluate_v22_dataset_quality(
        dataset,
        feature_names,
        label_col,
        return_col,
        min_rows=min_rows,
        min_dates=min_dates,
        min_symbols=min_symbols,
        max_feature_missing_rate=max_feature_missing_rate,
    )
    _write_json(root / "ml_v22_adjusted_quality.json", quality)
    baseline_metrics = _baseline_metrics(dataset, label_col, return_col)

    summary: Dict[str, Any] = {
        "experiment": "ml_v2_2_adjusted_momentum",
        "production_enabled": False,
        "strategy_impact": False,
        "production_action": "do_not_change_strategy",
        "dataset": dataset_report,
        "quality": quality,
        "feature_names": feature_names,
        "baseline_metrics": baseline_metrics,
    }

    if quality["ready_for_training"]:
        trainable = dataset.dropna(subset=[label_col, return_col]).copy()
        try:
            split_plan = build_ml_split_plan(
                trainable,
                final_holdout_months=final_holdout_months,
                stock_holdout_ratio=0.20,
                walk_forward_splits=4,
                label_horizon_days=10,
                stock_holdout_seed=stock_holdout_seed,
            )
        except ValueError as exc:
            summary["split_integrity"] = {"valid": False, "blocking_reasons": [str(exc)]}
            summary["training"] = {"status": "skipped", "reason": "split_planning_failed"}
            _write_json(root / "ml_v22_adjusted_split_integrity.json", summary["split_integrity"])
            pd.DataFrame().to_csv(root / "ml_v22_adjusted_predictions.csv", index=False)
        else:
            split_integrity = validate_v22_split_integrity(trainable, split_plan)
            summary["split_integrity"] = split_integrity
            _write_json(root / "ml_v22_adjusted_split_integrity.json", split_integrity)
            if split_integrity["valid"]:
                training = train_local_models(
                    trainable,
                    feature_names=feature_names,
                    label_col=label_col,
                    return_col=return_col,
                    split_plan=split_plan,
                    candidate_set="core_v2",
                    sample_weight_mode="date_stock_balanced",
                    model_metadata={
                        "experiment": "ml_v2_2_adjusted_momentum",
                        "production_enabled": False,
                        "strategy_impact": False,
                    },
                    prediction_output_path=root / "ml_v22_adjusted_predictions.csv",
                )
                summary["training"] = training
            else:
                summary["training"] = {"status": "skipped", "reason": "split_integrity_failed"}
                pd.DataFrame().to_csv(root / "ml_v22_adjusted_predictions.csv", index=False)
    else:
        summary["training"] = {"status": "skipped", "reason": "quality_gate_failed"}
        summary["split_integrity"] = {"valid": False, "blocking_reasons": ["quality_gate_failed"]}
        _write_json(root / "ml_v22_adjusted_split_integrity.json", summary["split_integrity"])
        pd.DataFrame().to_csv(root / "ml_v22_adjusted_predictions.csv", index=False)

    summary["report_markdown"] = render_v22_adjusted_report(summary)
    _write_json(root / "ml_v22_adjusted_summary.json", {key: value for key, value in summary.items() if key != "report_markdown"})
    (root / "ml_v22_adjusted_report.md").write_text(summary["report_markdown"], encoding="utf-8")
    return summary


def render_v22_adjusted_report(summary: Dict[str, Any]) -> str:
    quality = summary.get("quality") or {}
    training = summary.get("training") or {}
    best_model = training.get("best_model") if isinstance(training, dict) else None
    lines = [
        "# ML V2.2 Adjusted Momentum Experiment",
        "",
        f"production_enabled: `{summary.get('production_enabled')}`",
        f"strategy_impact: `{summary.get('strategy_impact')}`",
        f"production_action: `{summary.get('production_action')}`",
        "",
        "## Dataset Quality",
        "",
        f"- ready_for_training: `{quality.get('ready_for_training')}`",
        f"- production_ready: `{quality.get('production_ready')}`",
        f"- row_count: `{quality.get('row_count')}`",
        f"- date_count: `{quality.get('date_count')}`",
        f"- symbol_count: `{quality.get('symbol_count')}`",
        f"- label_rate: `{quality.get('label_rate')}`",
        f"- blocking_reasons: `{quality.get('blocking_reasons')}`",
        "",
        "## Baselines",
        "",
        "| Score | P@5 | NDCG@10 | TopK Return |",
        "|---|---:|---:|---:|",
    ]
    for name, metrics in (summary.get("baseline_metrics") or {}).items():
        lines.append(
            f"| `{name}` | {metrics.get('precision_at_5', 0.0)} | {metrics.get('ndcg_at_10', 0.0)} | {metrics.get('topk_return', 0.0)} |"
        )
    lines.extend(
        [
            "",
            "## Training",
            "",
            f"- status: `{training.get('status', 'trained') if isinstance(training, dict) else 'unknown'}`",
            f"- best_model: `{best_model}`",
        ]
    )
    if isinstance(training, dict) and best_model and (training.get("models") or {}).get(best_model):
        best = (training.get("models") or {}).get(best_model) or {}
        for split in ["final_holdout", "stock_holdout", "walk_forward"]:
            metrics = best.get(split) or {}
            lines.append(
                f"- {split}: P@5 `{metrics.get('precision_at_5')}`, NDCG@10 `{metrics.get('ndcg_at_10')}`, TopK return `{metrics.get('topk_return')}`"
            )
    lines.extend(
        [
            "",
            "This experiment is read-only. It does not change production stock selection, ranking, buy/sell, take-profit, stop-loss, or position sizing logic.",
        ]
    )
    return "\n".join(lines) + "\n"


def _normalize_panel(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "symbol" not in local.columns and "ts_code" in local.columns:
        local["symbol"] = local["ts_code"]
    if "date" not in local.columns and "trade_date" in local.columns:
        local["date"] = local["trade_date"]
    if "symbol" not in local.columns or "date" not in local.columns:
        return pd.DataFrame()
    local["symbol"] = local["symbol"].map(_normalize_symbol)
    local["date"] = pd.to_datetime(local["date"].astype(str), errors="coerce").dt.strftime("%Y-%m-%d")
    local = local[(local["symbol"] != "") & local["date"].notna()].copy()
    return local


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return text


def _attach_adjusted_acceleration_features(df: pd.DataFrame) -> None:
    if {"adj_return_5d_rank", "adj_return_20d_rank"}.issubset(df.columns):
        df["adj_momentum_accel_5_20"] = pd.to_numeric(df["adj_return_5d_rank"], errors="coerce") - pd.to_numeric(df["adj_return_20d_rank"], errors="coerce")
    if {"adj_return_20d_rank", "adj_return_60d_rank"}.issubset(df.columns):
        df["adj_momentum_accel_20_60"] = pd.to_numeric(df["adj_return_20d_rank"], errors="coerce") - pd.to_numeric(df["adj_return_60d_rank"], errors="coerce")


def _available_feature_names(df: pd.DataFrame) -> List[str]:
    available = []
    for feature in V22_ADJUSTED_FEATURE_NAMES:
        if feature in df.columns and feature not in set(available):
            available.append(feature)
    return [feature for feature in available if feature not in set(_forbidden_feature_names([feature]))]


def _forbidden_feature_names(feature_names: List[str]) -> List[str]:
    forbidden = []
    for feature in feature_names:
        lowered = str(feature).lower()
        if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
            forbidden.append(str(feature))
    return forbidden


def _base_report(row_count: int, feature_names: List[str], missing_rates: Dict[str, float]) -> Dict[str, Any]:
    return {
        "row_count": int(row_count),
        "feature_count": len(feature_names),
        "feature_names": feature_names,
        "feature_missing_rates": missing_rates,
        "production_enabled": False,
        "strategy_impact": False,
        "production_action": "do_not_change_strategy",
    }


def _baseline_metrics(df: pd.DataFrame, label_col: str, return_col: str) -> Dict[str, Any]:
    metrics = {}
    for score_col in ["return_60d_rank", "adj_return_60d_rank", "score"]:
        if score_col not in df.columns:
            continue
        metrics[score_col] = daily_ranking_metrics(
            df,
            label_col=label_col,
            score_col=score_col,
            return_col=return_col,
            date_col="date",
        )
    return metrics


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.ndarray,)):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Series):
        return value.tolist()
    return value
