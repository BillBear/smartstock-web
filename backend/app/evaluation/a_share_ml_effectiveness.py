from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd


LABEL_SPECS: Dict[str, Dict[str, Any]] = {
    "label_rank_top10_10d": {"primary_allowed": True, "kind": "relative_return"},
    "label_alpha_top20_10d": {"primary_allowed": True, "kind": "excess_return"},
    "label_profit_quality_10d": {"primary_allowed": True, "kind": "profit_quality"},
    "label_wave_quality_20d": {"primary_allowed": True, "kind": "wave_quality"},
    "label_tp_before_sl_10d": {"primary_allowed": False, "kind": "timing_auxiliary"},
}


FEATURE_GROUPS: Dict[str, List[str]] = {
    "amount_liquidity": [
        "amount_log",
        "amount_pct_rank",
        "amount_ma_3",
        "amount_ma_5",
        "amount_ma_10",
        "amount_ma_20",
        "amount_ratio_3_10",
        "amount_ratio_5_20",
        "amount_ratio_10_20",
        "amount_persistence_5d",
        "amount_persistence_10d",
    ],
    "turnover_activity": [
        "turnover_rate",
        "turnover_ma_3",
        "turnover_ma_5",
        "turnover_ma_10",
        "turnover_ma_20",
        "turnover_ratio_3_10",
        "turnover_ratio_5_20",
        "turnover_persistence_5d",
    ],
    "technical_basic": [
        "macd_hist",
        "macd_hist_delta_3d",
        "rsi",
        "rsi_delta_3d",
        "atr_14_pct",
        "intraday_range_pct",
    ],
    "trend_momentum": [
        "return_5d_pct",
        "return_10d_pct",
        "return_20d_pct",
        "return_60d_rank",
        "trend_slope_20d",
        "trend_r2_20d",
        "breakout_20d_count_5d",
    ],
    "ma_gap_ablation": ["ma20_gap_pct", "ma60_gap_pct", "ma_alignment"],
    "risk_reversal": [
        "volatility_20d",
        "large_down_day_count_20d",
        "pullback_from_20d_high_pct",
        "recovery_from_20d_low_pct",
    ],
    "regime_interaction": [
        "market_breadth_positive_rate",
        "market_median_return_5d",
        "market_amount_ratio_5_20",
        "hot_stock_rate_5d",
        "limit_up_pressure",
        "limit_down_pressure",
    ],
}


DEFAULT_BASELINES = [
    "random_daily_rank",
    "return_20d_rank_desc",
    "return_60d_rank_desc",
    "amount_pct_rank_desc",
    "amount_ratio_5_20_desc",
    "turnover_ratio_5_20_desc",
    "macd_hist_desc",
    "rsi_mid_range_prefer_45_to_65",
]


def build_profit_quality_labels(
    df: pd.DataFrame,
    min_abs_return_pct: float = 3.0,
    max_drawdown_pct: float = -6.0,
    wave_max_drawdown_pct: float = -10.0,
    min_wave_gain_pct: float = 8.0,
) -> pd.DataFrame:
    local = _normalize_frame(df)
    if local.empty:
        local["label_profit_quality_10d"] = []
        local["label_wave_quality_20d"] = []
        return local
    if "tradability_flag" not in local.columns:
        local["tradability_flag"] = True
    if "future_excess_return_10d_pct" not in local.columns and "future_return_10d_pct" in local.columns:
        daily_median = _num(local["future_return_10d_pct"]).groupby(local["date"]).transform("median")
        local["future_excess_return_10d_pct"] = _num(local["future_return_10d_pct"]) - daily_median

    required = ["future_return_10d_pct", "future_excess_return_10d_pct", "future_max_drawdown_10d_pct"]
    if all(column in local.columns for column in required):
        returns_10d = _num(local["future_return_10d_pct"])
        daily_median = returns_10d.groupby(local["date"]).transform("median")
        threshold = daily_median.apply(lambda value: max(float(value), float(min_abs_return_pct)))
        local["label_profit_quality_10d"] = (
            (returns_10d > threshold)
            & (_num(local["future_excess_return_10d_pct"]) > 0)
            & (_num(local["future_max_drawdown_10d_pct"]) >= float(max_drawdown_pct))
            & (local["tradability_flag"].astype(bool))
        ).astype(int)
    else:
        local["label_profit_quality_10d"] = 0

    wave_required = ["future_return_20d_pct", "future_max_drawdown_20d_pct"]
    max_gain_col = "future_max_gain_20d_pct" if "future_max_gain_20d_pct" in local.columns else "future_max_favorable_excursion_20d_pct"
    if all(column in local.columns for column in wave_required) and max_gain_col in local.columns:
        local["label_wave_quality_20d"] = 0
        for _, index in local.groupby("date").groups.items():
            rows = local.loc[index].copy()
            tradable = rows[rows["tradability_flag"].astype(bool) & _num(rows["future_return_20d_pct"]).notna()]
            if tradable.empty:
                continue
            top_count = max(1, int(math.ceil(len(tradable) * 0.20)))
            top_index = tradable.sort_values(["future_return_20d_pct", "symbol"], ascending=[False, True]).head(top_count).index
            passing = tradable[
                tradable.index.isin(top_index)
                & (_num(tradable["future_max_drawdown_20d_pct"]) >= float(wave_max_drawdown_pct))
                & (_num(tradable[max_gain_col]) >= float(min_wave_gain_pct))
            ]
            local.loc[passing.index, "label_wave_quality_20d"] = 1
    else:
        local["label_wave_quality_20d"] = 0
    return local


def present_feature_groups(df: pd.DataFrame) -> Dict[str, Dict[str, List[str]]]:
    columns = set(df.columns if df is not None else [])
    result: Dict[str, Dict[str, List[str]]] = {}
    for group, names in FEATURE_GROUPS.items():
        result[group] = {
            "present": [name for name in names if name in columns],
            "missing": [name for name in names if name not in columns],
        }
    return result


def add_a_share_audit_features(df: pd.DataFrame) -> pd.DataFrame:
    local = _normalize_frame(df)
    if local.empty:
        return local
    parts = []
    for _, group in local.groupby("symbol", sort=False):
        group = group.copy()
        amount = _num(group.get("amount", pd.Series(index=group.index, dtype=float)))
        if "amount_log" not in group.columns:
            group["amount_log"] = np.log1p(amount.clip(lower=0).fillna(0.0))
        for window in (3, 5, 10, 20):
            group[f"amount_ma_{window}"] = amount.rolling(window, min_periods=1).mean()
        group["amount_ratio_3_10"] = _safe_div(group["amount_ma_3"], group["amount_ma_10"], 1.0)
        group["amount_ratio_5_20"] = _safe_div(group["amount_ma_5"], group["amount_ma_20"], 1.0)
        group["amount_ratio_10_20"] = _safe_div(group["amount_ma_10"], group["amount_ma_20"], 1.0)
        group["amount_persistence_5d"] = (_safe_div(amount, group["amount_ma_20"], 1.0) >= 1.1).rolling(5, min_periods=1).sum()
        group["amount_persistence_10d"] = (_safe_div(amount, group["amount_ma_20"], 1.0) >= 1.1).rolling(10, min_periods=1).sum()
        if "turnover_rate" in group.columns:
            turnover = _num(group["turnover_rate"])
            for window in (3, 5, 10, 20):
                group[f"turnover_ma_{window}"] = turnover.rolling(window, min_periods=1).mean()
            group["turnover_ratio_3_10"] = _safe_div(group["turnover_ma_3"], group["turnover_ma_10"], 1.0)
            group["turnover_ratio_5_20"] = _safe_div(group["turnover_ma_5"], group["turnover_ma_20"], 1.0)
            group["turnover_persistence_5d"] = (_safe_div(turnover, group["turnover_ma_20"], 1.0) >= 1.1).rolling(5, min_periods=1).sum()
        group["macd_hist_delta_3d"] = _num(group.get("macd_hist", pd.Series(0.0, index=group.index))).diff(3)
        group["rsi_delta_3d"] = _num(group.get("rsi", pd.Series(50.0, index=group.index))).diff(3)
        parts.append(group)
    result = pd.concat(parts, ignore_index=True) if parts else local
    if "amount_pct_rank" not in result.columns and "amount" in result.columns:
        result["amount_pct_rank"] = result.groupby("date")["amount"].rank(pct=True).fillna(0.5)
    return result.replace([np.inf, -np.inf], np.nan)


def add_market_regime_tags(df: pd.DataFrame) -> pd.DataFrame:
    local = _normalize_frame(df)
    if local.empty:
        return local
    if "return_5d_pct" not in local.columns:
        local["return_5d_pct"] = 0.0
    if "amount_ratio_5_20" not in local.columns:
        local["amount_ratio_5_20"] = 1.0
    rows = []
    for date, group in local.groupby("date", sort=False):
        returns = _num(group["return_5d_pct"])
        amount_ratio = _num(group["amount_ratio_5_20"])
        breadth = float((returns > 0).mean()) if len(group) else 0.0
        median_return = float(returns.median()) if len(group) else 0.0
        market_amount_ratio = float(amount_ratio.median()) if len(group) else 1.0
        hot_rate = float((returns >= 8.0).mean()) if len(group) else 0.0
        if breadth >= 0.58 and median_return > 0:
            market_regime = "offensive"
        elif breadth <= 0.42 or median_return < -2.0:
            market_regime = "defensive"
        else:
            market_regime = "balanced"
        if market_amount_ratio >= 1.15:
            liquidity_regime = "liquidity_expansion"
        elif market_amount_ratio <= 0.85:
            liquidity_regime = "liquidity_contraction"
        else:
            liquidity_regime = "liquidity_neutral"
        item = group.copy()
        item["market_breadth_positive_rate"] = round(breadth, 6)
        item["market_median_return_5d"] = round(median_return, 6)
        item["market_amount_ratio_5_20"] = round(market_amount_ratio, 6)
        item["hot_stock_rate_5d"] = round(hot_rate, 6)
        item["market_regime"] = market_regime
        item["liquidity_regime"] = liquidity_regime
        rows.append(item)
    return pd.concat(rows, ignore_index=True) if rows else local


def bucket_feature_quality(
    df: pd.DataFrame,
    feature: str,
    label_col: str,
    return_col: str,
    quantiles: int = 5,
    date_col: str = "date",
    round_trip_cost_pct: float = 0.13,
) -> Dict[str, Any]:
    local = _prepare_metric_frame(df, [feature], label_col, return_col, date_col)
    if local.empty or feature not in local.columns:
        return _empty_bucket_report(feature, "missing_feature")
    bucketed = []
    q = max(2, int(quantiles or 5))
    for _, rows in local.groupby(date_col, sort=False):
        clean = rows.dropna(subset=[feature, label_col, return_col]).copy()
        if len(clean) < q * 2 or clean[feature].nunique(dropna=True) < 2:
            continue
        try:
            clean["_bucket"] = pd.qcut(clean[feature], q=q, labels=False, duplicates="drop")
        except Exception:
            continue
        bucketed.append(clean)
    if not bucketed:
        return _empty_bucket_report(feature, "insufficient_bucket_data")
    data = pd.concat(bucketed, ignore_index=True)
    buckets = []
    for bucket, rows in data.groupby("_bucket"):
        rows = rows.copy()
        buckets.append(
            {
                "bucket": int(bucket),
                "sample_count": int(len(rows)),
                "label_rate": _round(float(rows[label_col].mean())),
                "avg_return": _round(float(rows[return_col].mean())),
                "median_return": _round(float(rows[return_col].median())),
                "drawdown_avg": _round(float(_num(rows.get("future_max_drawdown_10d_pct", pd.Series(0.0, index=rows.index))).mean())),
                "min_value": _round(float(rows[feature].min())),
                "max_value": _round(float(rows[feature].max())),
            }
        )
    bucket_frame = pd.DataFrame(buckets).sort_values("bucket")
    monotonicity = _safe_corr(bucket_frame["bucket"], bucket_frame["avg_return"]) if len(bucket_frame) > 1 else 0.0
    daily_desc = _daily_rank_metrics(data, feature, label_col, return_col, date_col, ascending=False, round_trip_cost_pct=round_trip_cost_pct)
    base_rate = float(data[label_col].mean()) if len(data) else 0.0
    top_bucket = buckets[-1] if buckets else {"label_rate": 0.0}
    return {
        "feature": feature,
        "status": "ok",
        "quantiles": q,
        "sample_count": int(len(data)),
        "date_count": int(data[date_col].nunique()),
        "buckets": buckets,
        "monotonicity_score": _round(monotonicity),
        "stability_score": _round(_bucket_stability(data, feature, label_col, return_col, date_col)),
        "top_bucket_lift": _round(float(top_bucket["label_rate"]) - base_rate),
        "top5_return_when_sorted_by_feature": daily_desc["top5_return"],
        "top5_return_after_cost_when_sorted_by_feature": daily_desc["top5_return_after_cost"],
        "precision_at_5_when_sorted_by_feature": daily_desc["precision_at_5"],
        "ndcg_at_10_when_sorted_by_feature": daily_desc["ndcg_at_10"],
    }


def compare_no_model_baselines(
    df: pd.DataFrame,
    label_col: str,
    return_col: str,
    baselines: Iterable[str] | None = None,
    date_col: str = "date",
    round_trip_cost_pct: float = 0.13,
) -> Dict[str, Dict[str, Any]]:
    local = _normalize_frame(df)
    names = list(baselines or DEFAULT_BASELINES)
    result: Dict[str, Dict[str, Any]] = {}
    for name in names:
        score_col = f"__score_{name}"
        scored = local.copy()
        spec = _baseline_score(scored, name, score_col)
        if not spec["available"]:
            result[name] = {
                "status": "missing",
                "precision_at_5": 0.0,
                "ndcg_at_10": 0.0,
                "top5_return": 0.0,
                "top5_return_after_cost": 0.0,
                "date_count": int(scored[date_col].nunique()) if date_col in scored.columns else 0,
                "covered_date_count": 0,
                "missing_reason": spec["reason"],
            }
            continue
        metrics = _daily_rank_metrics(
            scored,
            score_col,
            label_col,
            return_col,
            date_col,
            ascending=spec.get("ascending", False),
            round_trip_cost_pct=round_trip_cost_pct,
        )
        metrics["status"] = "ok"
        metrics["missing_reason"] = ""
        result[name] = metrics
    return result


def label_quality_summary(
    df: pd.DataFrame,
    label_cols: Iterable[str],
    return_col: str,
    round_trip_cost_pct: float = 0.13,
) -> Dict[str, Dict[str, Any]]:
    local = _normalize_frame(df)
    result: Dict[str, Dict[str, Any]] = {}
    split_values = _split_values(local)
    for label in label_cols:
        if label not in local.columns:
            result[label] = {"status": "missing", "accepted": False, "missing_reason": "missing_label"}
            continue
        rows = []
        split_returns = {}
        accepted_views = 0
        for split_name, split_df in split_values.items():
            valid = split_df[[label, return_col]].copy()
            valid[label] = _num(valid[label]).fillna(0).astype(int)
            valid[return_col] = _num(valid[return_col])
            positives = valid[valid[label] == 1]
            avg = float(positives[return_col].mean()) if not positives.empty else 0.0
            after_cost = avg - float(round_trip_cost_pct) if not positives.empty else 0.0
            split_returns[split_name] = _round(after_cost)
            if after_cost > 0 and len(positives) >= 5:
                accepted_views += 1
            rows.append(
                {
                    "split": split_name,
                    "sample_count": int(len(valid)),
                    "positive_count": int(len(positives)),
                    "label_rate": _round(float(valid[label].mean())) if len(valid) else 0.0,
                    "avg_positive_return": _round(avg),
                    "avg_positive_return_after_cost": _round(after_cost),
                }
            )
        spec = LABEL_SPECS.get(label, {})
        result[label] = {
            "status": "ok",
            "primary_allowed": bool(spec.get("primary_allowed", False)),
            "kind": spec.get("kind", "unknown"),
            "accepted": bool(spec.get("primary_allowed", False)) and accepted_views >= min(2, len(split_values)),
            "accepted_view_count": int(accepted_views),
            "split_returns_after_cost": split_returns,
            "splits": rows,
        }
    return result


def feature_group_quality(
    df: pd.DataFrame,
    label_col: str,
    return_col: str,
    round_trip_cost_pct: float = 0.13,
) -> Dict[str, Dict[str, Any]]:
    groups = present_feature_groups(df)
    result: Dict[str, Dict[str, Any]] = {}
    for group, info in groups.items():
        feature_reports = [
            bucket_feature_quality(df, feature, label_col, return_col, round_trip_cost_pct=round_trip_cost_pct)
            for feature in info["present"]
        ]
        valid = [item for item in feature_reports if item.get("status") == "ok"]
        best = max(valid, key=lambda item: item.get("top5_return_after_cost_when_sorted_by_feature", -999999), default=None)
        best_after_cost = float(best.get("top5_return_after_cost_when_sorted_by_feature", 0.0)) if best else 0.0
        result[group] = {
            "status": "ok" if valid else "missing_or_insufficient",
            "present": info["present"],
            "missing": info["missing"],
            "feature_count": len(info["present"]),
            "best_feature": best.get("feature") if best else "",
            "best_top5_return_after_cost": _round(best_after_cost),
            "best_precision_at_5": _round(float(best.get("precision_at_5_when_sorted_by_feature", 0.0))) if best else 0.0,
            "accepted": bool(best and best_after_cost > 0 and float(best.get("top_bucket_lift", 0.0)) > 0),
            "feature_reports": feature_reports,
        }
    return result


def regime_breakdown(
    df: pd.DataFrame,
    label_col: str,
    return_col: str,
) -> List[Dict[str, Any]]:
    local = _prepare_metric_frame(df, ["market_regime", "liquidity_regime"], label_col, return_col, "date", require_numeric_features=False)
    if local.empty:
        return []
    rows = []
    for columns in [("market_regime",), ("liquidity_regime",), ("market_regime", "liquidity_regime")]:
        for key, group in local.groupby(list(columns), dropna=False):
            if not isinstance(key, tuple):
                key = (key,)
            item = {column: str(value) for column, value in zip(columns, key)}
            item.update(
                {
                    "sample_count": int(len(group)),
                    "date_count": int(group["date"].nunique()),
                    "label_rate": _round(float(_num(group[label_col]).mean())) if len(group) else 0.0,
                    "avg_return": _round(float(_num(group[return_col]).mean())) if len(group) else 0.0,
                }
            )
            rows.append(item)
    return rows


def run_effectiveness_audit(
    df: pd.DataFrame,
    label_col: str = "label_profit_quality_10d",
    return_col: str = "future_return_10d_pct",
    round_trip_cost_pct: float = 0.13,
) -> Dict[str, Any]:
    frame = add_a_share_audit_features(df)
    frame = build_profit_quality_labels(frame)
    frame = add_market_regime_tags(frame)
    labels = list(dict.fromkeys([*LABEL_SPECS.keys(), label_col]))
    label_quality = label_quality_summary(frame, labels, return_col, round_trip_cost_pct=round_trip_cost_pct)
    group_quality = feature_group_quality(frame, label_col, return_col, round_trip_cost_pct=round_trip_cost_pct)
    baselines = compare_no_model_baselines(frame, label_col, return_col, round_trip_cost_pct=round_trip_cost_pct)
    regimes = regime_breakdown(frame, label_col, return_col)
    feature_bucket_rows = _flatten_feature_buckets(group_quality)
    summary = {
        "status": "completed",
        "audit_type": "a_share_ml_effectiveness",
        "row_count": int(len(frame)),
        "symbol_count": int(frame["symbol"].nunique()) if "symbol" in frame.columns else 0,
        "date_count": int(frame["date"].nunique()) if "date" in frame.columns else 0,
        "round_trip_cost_pct": float(round_trip_cost_pct),
        "label_col": label_col,
        "return_col": return_col,
        "sample_scope": "local_700_symbol_panel" if int(frame["symbol"].nunique()) <= 1500 else "large_panel",
        "evidence_limitations": _evidence_limitations(frame),
        "label_quality": label_quality,
        "feature_group_quality": _compact_group_quality(group_quality),
        "feature_bucket_quality": feature_bucket_rows,
        "regime_breakdown": regimes,
        "baseline_comparison": baselines,
    }
    summary["decision"] = summarize_audit_decision(summary)
    summary["report_markdown"] = render_audit_markdown(summary)
    return summary


def summarize_audit_decision(summary: Dict[str, Any]) -> Dict[str, Any]:
    labels = summary.get("label_quality") or {}
    groups = summary.get("feature_group_quality") or {}
    baselines = summary.get("baseline_comparison") or {}
    allowed_labels = [
        label for label, item in labels.items() if item.get("accepted") and item.get("primary_allowed", True)
    ]
    rejected_labels = [label for label, item in labels.items() if not item.get("accepted")]
    accepted_groups = [name for name, item in groups.items() if item.get("accepted")]
    blocked_groups = [name for name, item in groups.items() if not item.get("accepted")]
    random_return = float((baselines.get("random_daily_rank") or {}).get("top5_return_after_cost") or 0.0)
    best_baseline_name = ""
    best_baseline_return = -999999.0
    for name, item in baselines.items():
        value = float(item.get("top5_return_after_cost") or 0.0)
        if value > best_baseline_return:
            best_baseline_return = value
            best_baseline_name = name
    if allowed_labels and len(accepted_groups) >= 2 and best_baseline_return > random_return:
        outcome = "proceed_to_v2_2_profit_quality_training"
    elif accepted_groups and not allowed_labels:
        outcome = "revise_labels_before_training"
    elif allowed_labels and not accepted_groups:
        outcome = "revise_features_before_training"
    elif best_baseline_return > max(0.0, random_return):
        outcome = "prefer_rule_baseline_over_ml_for_now"
    else:
        outcome = "insufficient_evidence_for_price_volume_ml"
    return {
        "outcome": outcome,
        "production_model_status": "paper_only",
        "v2_2_training_allowed": outcome == "proceed_to_v2_2_profit_quality_training",
        "allowed_primary_labels": allowed_labels,
        "rejected_labels": rejected_labels,
        "feature_groups_allowed": accepted_groups,
        "feature_groups_blocked": blocked_groups,
        "best_baseline": best_baseline_name,
        "best_baseline_top5_return_after_cost": _round(best_baseline_return),
        "random_top5_return_after_cost": _round(random_return),
    }


def write_audit_artifacts(summary: Dict[str, Any], output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "audit_summary.json"
    summary_json = {key: value for key, value in summary.items() if key != "report_markdown"}
    summary_path.write_text(json.dumps(summary_json, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(root / "label_quality.csv", _label_quality_rows(summary["label_quality"]))
    _write_csv(root / "feature_group_quality.csv", _feature_group_rows(summary["feature_group_quality"]))
    _write_csv(root / "feature_bucket_quality.csv", summary["feature_bucket_quality"])
    _write_csv(root / "regime_breakdown.csv", summary["regime_breakdown"])
    _write_csv(root / "baseline_comparison.csv", _dict_rows(summary["baseline_comparison"], "baseline"))
    report_path = root / "audit_report.md"
    report_path.write_text(summary["report_markdown"], encoding="utf-8")
    return {
        "audit_summary": str(summary_path),
        "label_quality": str(root / "label_quality.csv"),
        "feature_group_quality": str(root / "feature_group_quality.csv"),
        "feature_bucket_quality": str(root / "feature_bucket_quality.csv"),
        "regime_breakdown": str(root / "regime_breakdown.csv"),
        "baseline_comparison": str(root / "baseline_comparison.csv"),
        "audit_report": str(report_path),
    }


def render_audit_markdown(summary: Dict[str, Any]) -> str:
    decision = summary.get("decision") or {}
    baselines = summary.get("baseline_comparison") or {}
    groups = summary.get("feature_group_quality") or {}
    labels = summary.get("label_quality") or {}
    limitations = summary.get("evidence_limitations") or []
    best_baseline = decision.get("best_baseline") or ""
    random_return = (baselines.get("random_daily_rank") or {}).get("top5_return_after_cost", 0.0)
    best_return = decision.get("best_baseline_top5_return_after_cost", 0.0)
    amount_group = groups.get("amount_liquidity") or {}
    turnover_group = groups.get("turnover_activity") or {}
    technical_group = groups.get("technical_basic") or {}
    ma_group = groups.get("ma_gap_ablation") or {}
    lines = [
        "# A-Share ML Effectiveness Audit",
        "",
        f"status: `{summary.get('status')}`",
        f"sample_scope: `{summary.get('sample_scope')}`",
        f"row_count: `{summary.get('row_count')}`",
        f"symbol_count: `{summary.get('symbol_count')}`",
        f"date_count: `{summary.get('date_count')}`",
        f"round_trip_cost_pct: `{summary.get('round_trip_cost_pct')}`",
        f"decision: `{decision.get('outcome')}`",
        f"production_model_status: `{decision.get('production_model_status')}`",
        f"v2_2_training_allowed: `{decision.get('v2_2_training_allowed')}`",
        "",
        "## Hard Answers",
        "",
        f"- Do simple price/volume baselines beat random? `{best_return > random_return}`. Best baseline: `{best_baseline}` with after-cost Top5 return `{best_return}` versus random `{random_return}`.",
        f"- Which feature group has positive available-split Top-K return after explicit cost assumptions? `{', '.join(decision.get('feature_groups_allowed') or []) or 'none'}`.",
        f"- Do amount and turnover interval features add lift? amount_liquidity accepted=`{amount_group.get('accepted')}`, turnover_activity accepted=`{turnover_group.get('accepted')}`.",
        f"- Do MACD/RSI add lift outside offensive regimes? technical_basic accepted=`{technical_group.get('accepted')}`; regime-level causal lift is not claimed by this audit.",
        f"- Are MA gap features useful or mostly noisy? ma_gap_ablation accepted=`{ma_group.get('accepted')}`, best feature=`{ma_group.get('best_feature', '')}`.",
        f"- Which labels are profit-aligned? `{', '.join(decision.get('allowed_primary_labels') or []) or 'none'}`.",
        f"- Which claims are unverified because the current sample lacks required columns? `{', '.join(limitations) or 'none'}`.",
        f"- Does any evidence justify V2.2 training? `{decision.get('v2_2_training_allowed')}`.",
        "",
        "## Label Quality",
        "",
        "| Label | Accepted | Kind | Views |",
        "|---|---:|---|---:|",
    ]
    for label, item in labels.items():
        lines.append(f"| `{label}` | `{item.get('accepted')}` | `{item.get('kind', '')}` | {item.get('accepted_view_count', 0)} |")
    lines.extend(["", "## Feature Groups", "", "| Group | Accepted | Best Feature | Best After-Cost Top5 Return | Present | Missing |", "|---|---:|---|---:|---:|---:|"])
    for group, item in groups.items():
        lines.append(
            f"| `{group}` | `{item.get('accepted')}` | `{item.get('best_feature', '')}` | {item.get('best_top5_return_after_cost', 0.0)} | {len(item.get('present') or [])} | {len(item.get('missing') or [])} |"
        )
    lines.extend(["", "## Baselines", "", "| Baseline | Status | P@5 | NDCG@10 | Top5 Return | After Cost |", "|---|---|---:|---:|---:|---:|"])
    for baseline, item in baselines.items():
        lines.append(
            f"| `{baseline}` | `{item.get('status')}` | {item.get('precision_at_5', 0.0)} | {item.get('ndcg_at_10', 0.0)} | {item.get('top5_return', 0.0)} | {item.get('top5_return_after_cost', 0.0)} |"
        )
    lines.extend(["", "## Evidence Limits"])
    lines.extend([f"- `{item}`" for item in limitations] if limitations else ["- none"])
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "This audit is read-only evidence. It does not modify production stock selection, ranking, buy/sell, stop-loss, take-profit, or position sizing logic.",
        ]
    )
    return "\n".join(lines) + "\n"


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "date" in local.columns:
        local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        local = local[local["date"].notna()].copy()
    if "symbol" in local.columns:
        local["symbol"] = local["symbol"].astype(str).str.zfill(6)
    return local.sort_values([column for column in ["symbol", "date"] if column in local.columns]).reset_index(drop=True)


def _prepare_metric_frame(
    df: pd.DataFrame,
    features: Iterable[str],
    label_col: str,
    return_col: str,
    date_col: str,
    require_numeric_features: bool = True,
) -> pd.DataFrame:
    local = _normalize_frame(df)
    required = [date_col, label_col, return_col]
    if any(column not in local.columns for column in required):
        return pd.DataFrame()
    for column in [label_col, return_col]:
        local[column] = _num(local[column])
    if require_numeric_features:
        for feature in features:
            if feature not in local.columns:
                return pd.DataFrame()
            local[feature] = _num(local[feature])
        local = local.dropna(subset=[date_col, label_col, return_col, *features])
    return local.dropna(subset=[date_col, label_col, return_col])


def _baseline_score(df: pd.DataFrame, name: str, score_col: str) -> Dict[str, Any]:
    if name == "random_daily_rank":
        df[score_col] = [
            int(hashlib.sha256(f"{date}:{symbol}".encode("utf-8")).hexdigest()[:12], 16)
            for date, symbol in zip(df.get("date", ""), df.get("symbol", ""))
        ]
        return {"available": True, "ascending": False, "reason": ""}
    mapping = {
        "return_20d_rank_desc": "return_20d_rank",
        "return_60d_rank_desc": "return_60d_rank",
        "amount_pct_rank_desc": "amount_pct_rank",
        "amount_ratio_5_20_desc": "amount_ratio_5_20",
        "turnover_ratio_5_20_desc": "turnover_ratio_5_20",
        "macd_hist_desc": "macd_hist",
    }
    if name in mapping:
        column = mapping[name]
        if column not in df.columns:
            return {"available": False, "ascending": False, "reason": f"missing_{column}"}
        df[score_col] = _num(df[column])
        return {"available": True, "ascending": False, "reason": ""}
    if name == "rsi_mid_range_prefer_45_to_65":
        if "rsi" not in df.columns:
            return {"available": False, "ascending": False, "reason": "missing_rsi"}
        rsi = _num(df["rsi"])
        df[score_col] = -(rsi - 55.0).abs()
        return {"available": True, "ascending": False, "reason": ""}
    return {"available": False, "ascending": False, "reason": "unknown_baseline"}


def _daily_rank_metrics(
    df: pd.DataFrame,
    score_col: str,
    label_col: str,
    return_col: str,
    date_col: str,
    ascending: bool = False,
    round_trip_cost_pct: float = 0.13,
) -> Dict[str, Any]:
    local = _prepare_metric_frame(df, [score_col], label_col, return_col, date_col)
    if local.empty:
        return _empty_rank_metrics()
    metrics = {"precision_at_5": [], "ndcg_at_10": [], "top5_return": []}
    covered = 0
    for _, rows in local.groupby(date_col, sort=False):
        clean = rows.dropna(subset=[score_col, label_col, return_col])
        if clean.empty:
            continue
        covered += 1
        ordered = clean.sort_values([score_col, "symbol"], ascending=[ascending, True])
        labels = _num(ordered[label_col]).fillna(0).astype(int).to_numpy()
        returns = _num(ordered[return_col]).to_numpy(dtype=float)
        top5 = min(5, len(labels))
        metrics["precision_at_5"].append(float(labels[:top5].mean()) if top5 else 0.0)
        metrics["ndcg_at_10"].append(_ndcg_at_k(labels, 10))
        metrics["top5_return"].append(float(np.nanmean(returns[:top5])) if top5 else 0.0)
    if covered == 0:
        return _empty_rank_metrics()
    top5_return = _mean(metrics["top5_return"])
    return {
        "precision_at_5": _mean(metrics["precision_at_5"]),
        "ndcg_at_10": _mean(metrics["ndcg_at_10"]),
        "top5_return": top5_return,
        "top5_return_after_cost": _round(top5_return - float(round_trip_cost_pct)),
        "date_count": int(local[date_col].nunique()),
        "covered_date_count": int(covered),
    }


def _empty_rank_metrics() -> Dict[str, Any]:
    return {
        "precision_at_5": 0.0,
        "ndcg_at_10": 0.0,
        "top5_return": 0.0,
        "top5_return_after_cost": 0.0,
        "date_count": 0,
        "covered_date_count": 0,
    }


def _empty_bucket_report(feature: str, reason: str) -> Dict[str, Any]:
    return {
        "feature": feature,
        "status": reason,
        "quantiles": 0,
        "sample_count": 0,
        "date_count": 0,
        "buckets": [],
        "monotonicity_score": 0.0,
        "stability_score": 0.0,
        "top_bucket_lift": 0.0,
        "top5_return_when_sorted_by_feature": 0.0,
        "top5_return_after_cost_when_sorted_by_feature": 0.0,
        "precision_at_5_when_sorted_by_feature": 0.0,
        "ndcg_at_10_when_sorted_by_feature": 0.0,
    }


def _split_values(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    if "split" not in df.columns:
        return {"all": df}
    result: Dict[str, pd.DataFrame] = {}
    for split in ["final_holdout", "stock_holdout", "walk_forward", "train", "all"]:
        if split == "all":
            result[split] = df
        else:
            rows = df[df["split"].astype(str) == split]
            if not rows.empty:
                result[split] = rows
    if "walk_forward" not in result:
        train = df[df["split"].astype(str) == "train"] if "split" in df.columns else pd.DataFrame()
        if not train.empty:
            dates = sorted(train["date"].dropna().unique().tolist())
            tail_dates = set(dates[-max(1, min(60, len(dates) // 5)) :])
            result["walk_forward"] = train[train["date"].isin(tail_dates)]
    return result


def _evidence_limitations(df: pd.DataFrame) -> List[str]:
    limits = []
    if int(df["symbol"].nunique()) < 1500:
        limits.append("sample_is_700_symbol_local_panel_not_full_market")
    if "industry" not in df.columns and "theme" not in df.columns:
        limits.append("theme_or_industry_relative_strength_not_available_in_sample")
    if "turnover_rate" not in df.columns:
        limits.append("turnover_not_available_in_sample")
    if "split" not in df.columns:
        limits.append("split_specific_claims_unverified")
    return limits


def _compact_group_quality(groups: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    compact = {}
    for name, item in groups.items():
        compact[name] = {key: value for key, value in item.items() if key != "feature_reports"}
    return compact


def _flatten_feature_buckets(groups: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for group, item in groups.items():
        for report in item.get("feature_reports") or []:
            for bucket in report.get("buckets") or []:
                row = {"group": group, "feature": report.get("feature"), **bucket}
                rows.append(row)
    return rows


def _label_quality_rows(labels: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for label, item in labels.items():
        for split in item.get("splits") or []:
            rows.append({"label": label, "accepted": item.get("accepted"), "kind": item.get("kind"), **split})
        if not item.get("splits"):
            rows.append({"label": label, "accepted": item.get("accepted"), "kind": item.get("kind"), "status": item.get("status")})
    return rows


def _feature_group_rows(groups: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "group": group,
            "status": item.get("status"),
            "accepted": item.get("accepted"),
            "feature_count": item.get("feature_count"),
            "best_feature": item.get("best_feature"),
            "best_top5_return_after_cost": item.get("best_top5_return_after_cost"),
            "best_precision_at_5": item.get("best_precision_at_5"),
            "present_count": len(item.get("present") or []),
            "missing_count": len(item.get("missing") or []),
        }
        for group, item in groups.items()
    ]


def _dict_rows(items: Dict[str, Dict[str, Any]], name_key: str) -> List[Dict[str, Any]]:
    return [{name_key: name, **value} for name, value in items.items()]


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _bucket_stability(df: pd.DataFrame, feature: str, label_col: str, return_col: str, date_col: str) -> float:
    dates = sorted(df[date_col].dropna().unique().tolist())
    if len(dates) < 4:
        return 0.0
    midpoint = len(dates) // 2
    first = df[df[date_col].isin(dates[:midpoint])]
    second = df[df[date_col].isin(dates[midpoint:])]
    first_report = _daily_rank_metrics(first, feature, label_col, return_col, date_col)
    second_report = _daily_rank_metrics(second, feature, label_col, return_col, date_col)
    return min(first_report["top5_return"], second_report["top5_return"])


def _safe_div(left: pd.Series, right: pd.Series, default: float) -> pd.Series:
    return (left / right.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(default)


def _num(values: Any) -> pd.Series:
    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce")
    return pd.Series(values, dtype="float64")


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    try:
        value = pd.to_numeric(left, errors="coerce").corr(pd.to_numeric(right, errors="coerce"), method="spearman")
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _ndcg_at_k(labels: np.ndarray, k: int) -> float:
    top_k = min(int(k), len(labels))
    if top_k <= 0:
        return 0.0
    gains = labels[:top_k].astype(float)
    ideal = np.sort(labels.astype(float))[::-1][:top_k]
    dcg = _dcg(gains)
    idcg = _dcg(ideal)
    return float(dcg / idcg) if idcg else 0.0


def _dcg(gains: np.ndarray) -> float:
    return float(np.sum((2**gains - 1) / np.log2(np.arange(len(gains)) + 2)))


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return _round(float(np.nanmean(values)))


def _round(value: float) -> float:
    try:
        if not np.isfinite(value):
            return 0.0
        return round(float(value), 6)
    except Exception:
        return 0.0
