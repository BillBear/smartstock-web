from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd


DEFAULT_RULE_BASELINES = [
    "current_smartstock_rank",
    "current_smartstock_score_desc",
    "return_60d_rank_desc",
    "return_20d_rank_desc",
    "amount_pct_rank_desc",
    "amount_ratio_5_20_desc",
    "macd_hist_desc",
    "rsi_mid_range_prefer_45_to_65",
]

DEFAULT_RULE_FEATURE_COLUMNS = [
    "return_60d_rank",
    "return_20d_rank",
    "amount_pct_rank",
    "amount_ratio_5_20",
    "macd_hist",
    "rsi",
]


def join_rule_features(
    candidate_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    candidate_date_col: str = "trade_date",
    feature_date_col: str = "date",
    feature_cols: Iterable[str] | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Join read-only rule features onto historical SmartStock candidate labels."""
    candidates = _normalize_candidate_frame(candidate_df, candidate_date_col)
    features = _normalize_feature_frame(feature_df, feature_date_col)
    requested_features = list(feature_cols or DEFAULT_RULE_FEATURE_COLUMNS)
    available_features = [column for column in requested_features if column in features.columns]
    missing_features = [column for column in requested_features if column not in features.columns]

    if candidates.empty:
        return candidates, _coverage_summary(candidates, candidates, available_features, missing_features)
    if features.empty or not available_features:
        joined = candidates.copy()
        return joined, _coverage_summary(candidates, joined.iloc[0:0], available_features, missing_features)

    feature_keys = features[["date", "symbol", *available_features]].drop_duplicates(["date", "symbol"], keep="last")
    joined = candidates.merge(
        feature_keys,
        left_on=["trade_date", "symbol"],
        right_on=["date", "symbol"],
        how="left",
        indicator="__feature_join_status",
    )
    joined_rows = joined[joined["__feature_join_status"] == "both"].copy()
    return joined.drop(columns=["date"], errors="ignore"), _coverage_summary(
        candidates,
        joined_rows,
        available_features,
        missing_features,
    )


def run_rule_baseline_comparison(
    candidate_df: pd.DataFrame,
    feature_df: pd.DataFrame | None = None,
    horizon: int = 10,
    baselines: Iterable[str] | None = None,
    round_trip_cost_pct: float = 0.13,
    min_margin_pct: float = 0.30,
) -> Dict[str, Any]:
    joined, coverage = join_rule_features(candidate_df, feature_df if feature_df is not None else pd.DataFrame())
    metric_frame = _comparison_frame(joined)
    baseline_names = list(baselines or DEFAULT_RULE_BASELINES)
    label_col = f"strong_{int(horizon)}d"
    return_col = f"return_{int(horizon)}d_pct"
    comparison = compare_rule_baselines(
        metric_frame,
        label_col=label_col,
        return_col=return_col,
        horizon=horizon,
        baselines=baseline_names,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    summary = {
        "status": "completed",
        "audit_type": "rule_baseline_comparison",
        "production_evidence": False,
        "strategy_impact": False,
        "horizon": int(horizon),
        "label_col": label_col,
        "return_col": return_col,
        "round_trip_cost_pct": float(round_trip_cost_pct),
        "min_margin_pct": float(min_margin_pct),
        "comparison_sample_scope": "joined_feature_overlap" if metric_frame is not joined else "candidate_rows",
        "coverage": coverage,
        "baseline_comparison": comparison,
    }
    summary["decision"] = summarize_rule_comparison(summary)
    summary["report_markdown"] = render_rule_comparison_markdown(summary)
    return summary


def compare_rule_baselines(
    df: pd.DataFrame,
    label_col: str,
    return_col: str,
    horizon: int,
    baselines: Iterable[str],
    round_trip_cost_pct: float = 0.13,
) -> Dict[str, Dict[str, Any]]:
    local = _normalize_candidate_frame(df, "trade_date")
    result: Dict[str, Dict[str, Any]] = {}
    for name in baselines:
        scored = local.copy()
        score_col = f"__score_{name}"
        spec = _score_baseline(scored, name, score_col)
        if not spec["available"]:
            result[name] = {
                "status": "missing",
                "missing_reason": spec["reason"],
                **_empty_metrics(),
            }
            continue
        metrics = _daily_metrics(
            scored,
            score_col=score_col,
            label_col=label_col,
            return_col=return_col,
            horizon=horizon,
            ascending=bool(spec.get("ascending", False)),
            round_trip_cost_pct=round_trip_cost_pct,
        )
        metrics["status"] = "ok" if metrics["covered_date_count"] else "insufficient_labeled_rows"
        metrics["missing_reason"] = "" if metrics["covered_date_count"] else "no_labeled_rows"
        result[name] = metrics
    return result


def summarize_rule_comparison(summary: Dict[str, Any]) -> Dict[str, Any]:
    comparison = summary.get("baseline_comparison") or {}
    current = comparison.get("current_smartstock_rank") or {}
    return_60d = comparison.get("return_60d_rank_desc") or {}
    min_margin = float(summary.get("min_margin_pct") or 0.30)
    if return_60d.get("status") != "ok":
        return {
            "outcome": "blocked_missing_return_60d_rank",
            "production_action": "do_not_change_strategy",
            "reason": return_60d.get("missing_reason") or "return_60d_rank_desc_missing_or_unlabeled",
        }
    current_return = float(current.get("top5_return_after_cost") or 0.0)
    rule_return = float(return_60d.get("top5_return_after_cost") or 0.0)
    margin = round(rule_return - current_return, 6)
    if margin >= min_margin:
        outcome = "current_rank_lags_return_60d_baseline"
    elif -margin >= min_margin:
        outcome = "current_rank_beats_return_60d_baseline"
    else:
        outcome = "inconclusive_small_margin"
    return {
        "outcome": outcome,
        "production_action": "do_not_change_strategy",
        "current_top5_return_after_cost": current_return,
        "return_60d_top5_return_after_cost": rule_return,
        "return_60d_minus_current_pct": margin,
        "required_margin_pct": min_margin,
    }


def write_rule_comparison_artifacts(summary: Dict[str, Any], output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "rule_baseline_comparison.json"
    csv_path = root / "baseline_comparison.csv"
    daily_path = root / "baseline_daily_metrics.csv"
    report_path = root / "rule_baseline_comparison.md"
    serializable_summary = {key: value for key, value in summary.items() if key != "report_markdown"}
    summary_path.write_text(json.dumps(serializable_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(_baseline_rows(summary.get("baseline_comparison") or {})).to_csv(csv_path, index=False)
    pd.DataFrame(_daily_rows(summary.get("baseline_comparison") or {})).to_csv(daily_path, index=False)
    report_path.write_text(summary.get("report_markdown") or render_rule_comparison_markdown(summary), encoding="utf-8")
    return {
        "summary": str(summary_path),
        "baseline_comparison": str(csv_path),
        "daily_metrics": str(daily_path),
        "report": str(report_path),
    }


def render_rule_comparison_markdown(summary: Dict[str, Any]) -> str:
    coverage = summary.get("coverage") or {}
    decision = summary.get("decision") or {}
    comparison = summary.get("baseline_comparison") or {}
    lines = [
        "# Rule Baseline Comparison",
        "",
        f"status: `{summary.get('status')}`",
        f"horizon: `{summary.get('horizon')}`",
        f"label_col: `{summary.get('label_col')}`",
        f"return_col: `{summary.get('return_col')}`",
        f"round_trip_cost_pct: `{summary.get('round_trip_cost_pct')}`",
        f"production_evidence: `{summary.get('production_evidence')}`",
        f"strategy_impact: `{summary.get('strategy_impact')}`",
        f"comparison_sample_scope: `{summary.get('comparison_sample_scope')}`",
        f"decision: `{decision.get('outcome')}`",
        "",
        "## Coverage",
        "",
        f"- candidate_row_count: `{coverage.get('candidate_row_count')}`",
        f"- candidate_date_count: `{coverage.get('candidate_date_count')}`",
        f"- joined_row_count: `{coverage.get('joined_row_count')}`",
        f"- joined_date_count: `{coverage.get('joined_date_count')}`",
        f"- joined_row_coverage: `{coverage.get('joined_row_coverage')}`",
        f"- joined_date_range: `{coverage.get('joined_min_date')}` to `{coverage.get('joined_max_date')}`",
        f"- missing_features: `{', '.join(coverage.get('missing_features') or []) or 'none'}`",
        "",
        "## Baselines",
        "",
        "| Baseline | Status | P@3 | P@5 | P@10 | Recall@10 | NDCG@10 | MRR | Top5 Return | After Cost |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in comparison.items():
        lines.append(
            f"| `{name}` | `{item.get('status')}` | {item.get('precision_at_3', 0.0)} | {item.get('precision_at_5', 0.0)} | {item.get('precision_at_10', 0.0)} | {item.get('recall_at_10', 0.0)} | {item.get('ndcg_at_10', 0.0)} | {item.get('mrr', 0.0)} | {item.get('top5_return', 0.0)} | {item.get('top5_return_after_cost', 0.0)} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- outcome: `{decision.get('outcome')}`",
            f"- return_60d_minus_current_pct: `{decision.get('return_60d_minus_current_pct', '')}`",
            f"- production_action: `{decision.get('production_action')}`",
            "",
            "This report is read-only evidence. It does not modify production stock selection, ranking, buy/sell, take-profit, stop-loss, or position sizing logic.",
        ]
    )
    return "\n".join(lines) + "\n"


def _coverage_summary(
    candidates: pd.DataFrame,
    joined_rows: pd.DataFrame,
    available_features: List[str],
    missing_features: List[str],
) -> Dict[str, Any]:
    candidate_dates = _date_values(candidates, "trade_date")
    joined_dates = _date_values(joined_rows, "trade_date")
    candidate_count = int(len(candidates))
    joined_count = int(len(joined_rows))
    return {
        "candidate_row_count": candidate_count,
        "candidate_date_count": int(len(candidate_dates)),
        "candidate_min_date": candidate_dates[0] if candidate_dates else "",
        "candidate_max_date": candidate_dates[-1] if candidate_dates else "",
        "joined_row_count": joined_count,
        "joined_date_count": int(len(joined_dates)),
        "joined_min_date": joined_dates[0] if joined_dates else "",
        "joined_max_date": joined_dates[-1] if joined_dates else "",
        "joined_row_coverage": _round(joined_count / candidate_count) if candidate_count else 0.0,
        "joined_date_coverage": _round(len(joined_dates) / len(candidate_dates)) if candidate_dates else 0.0,
        "available_features": available_features,
        "missing_features": missing_features,
    }


def _comparison_frame(joined: pd.DataFrame) -> pd.DataFrame:
    if joined is None or joined.empty or "__feature_join_status" not in joined.columns:
        return joined
    overlap = joined[joined["__feature_join_status"] == "both"].copy()
    return overlap if not overlap.empty else joined.iloc[0:0].copy()


def _normalize_candidate_frame(df: pd.DataFrame | None, date_col: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if date_col != "trade_date" and date_col in local.columns:
        local["trade_date"] = local[date_col]
    if "trade_date" in local.columns:
        local["trade_date"] = pd.to_datetime(local["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        local = local[local["trade_date"].notna()].copy()
    if "symbol" in local.columns:
        local["symbol"] = local["symbol"].map(_normalize_symbol)
    return local.reset_index(drop=True)


def _normalize_feature_frame(df: pd.DataFrame | None, date_col: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if date_col != "date" and date_col in local.columns:
        local["date"] = local[date_col]
    if "date" in local.columns:
        local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        local = local[local["date"].notna()].copy()
    if "symbol" in local.columns:
        local["symbol"] = local["symbol"].map(_normalize_symbol)
    return local.reset_index(drop=True)


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return text


def _score_baseline(df: pd.DataFrame, name: str, score_col: str) -> Dict[str, Any]:
    if name == "current_smartstock_rank":
        if "rank_no" not in df.columns:
            return {"available": False, "reason": "missing_rank_no", "ascending": False}
        df[score_col] = -_num(df["rank_no"])
        return {"available": True, "reason": "", "ascending": False}
    mapping = {
        "current_smartstock_score_desc": "score",
        "return_60d_rank_desc": "return_60d_rank",
        "return_20d_rank_desc": "return_20d_rank",
        "amount_pct_rank_desc": "amount_pct_rank",
        "amount_ratio_5_20_desc": "amount_ratio_5_20",
        "macd_hist_desc": "macd_hist",
    }
    if name in mapping:
        column = mapping[name]
        if column not in df.columns:
            return {"available": False, "reason": f"missing_{column}", "ascending": False}
        df[score_col] = _num(df[column])
        return {"available": True, "reason": "", "ascending": False}
    if name == "rsi_mid_range_prefer_45_to_65":
        if "rsi" not in df.columns:
            return {"available": False, "reason": "missing_rsi", "ascending": False}
        df[score_col] = -(_num(df["rsi"]) - 55.0).abs()
        return {"available": True, "reason": "", "ascending": False}
    return {"available": False, "reason": "unknown_baseline", "ascending": False}


def _daily_metrics(
    df: pd.DataFrame,
    score_col: str,
    label_col: str,
    return_col: str,
    horizon: int,
    ascending: bool,
    round_trip_cost_pct: float,
) -> Dict[str, Any]:
    if df.empty or any(column not in df.columns for column in ["trade_date", "symbol", score_col, label_col, return_col]):
        return _empty_metrics()
    local = df.copy()
    local[score_col] = _num(local[score_col])
    local[return_col] = _num(local[return_col])
    local[label_col] = local[label_col].map(_to_bool)
    local = local[
        local[score_col].notna()
        & local[return_col].notna()
        & local.apply(lambda row: _is_tradable(row) and _has_complete_horizon(row, horizon), axis=1)
    ].copy()
    if local.empty:
        return _empty_metrics()
    daily: List[Dict[str, Any]] = []
    for date, rows in local.groupby("trade_date", sort=True):
        ordered = rows.sort_values([score_col, "symbol"], ascending=[ascending, True]).reset_index(drop=True)
        labels = ordered[label_col].astype(bool).tolist()
        returns = ordered[return_col].astype(float).tolist()
        strong_count = sum(1 for value in labels if value)
        daily.append(
            {
                "trade_date": date,
                "candidate_count": int(len(ordered)),
                "strong_count": int(strong_count),
                "precision_at_3": _precision(labels, 3),
                "precision_at_5": _precision(labels, 5),
                "precision_at_10": _precision(labels, 10),
                "recall_at_10": _round(sum(1 for value in labels[:10] if value) / strong_count) if strong_count else 0.0,
                "ndcg_at_10": _ndcg_from_returns(returns, 10),
                "mrr": _mrr(labels),
                "top3_return": _avg_top_k(returns, 3),
                "top5_return": _avg_top_k(returns, 5),
                "top10_return": _avg_top_k(returns, 10),
            }
        )
    top5_return = _mean([item["top5_return"] for item in daily])
    return {
        "precision_at_3": _mean([item["precision_at_3"] for item in daily]),
        "precision_at_5": _mean([item["precision_at_5"] for item in daily]),
        "precision_at_10": _mean([item["precision_at_10"] for item in daily]),
        "recall_at_10": _mean([item["recall_at_10"] for item in daily]),
        "ndcg_at_10": _mean([item["ndcg_at_10"] for item in daily]),
        "mrr": _mean([item["mrr"] for item in daily]),
        "top3_return": _mean([item["top3_return"] for item in daily]),
        "top5_return": top5_return,
        "top10_return": _mean([item["top10_return"] for item in daily]),
        "top5_return_after_cost": _round(top5_return - float(round_trip_cost_pct)),
        "date_count": int(local["trade_date"].nunique()),
        "covered_date_count": int(len(daily)),
        "row_count": int(len(local)),
        "daily_metrics": daily,
    }


def _empty_metrics() -> Dict[str, Any]:
    return {
        "precision_at_3": 0.0,
        "precision_at_5": 0.0,
        "precision_at_10": 0.0,
        "recall_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "mrr": 0.0,
        "top3_return": 0.0,
        "top5_return": 0.0,
        "top10_return": 0.0,
        "top5_return_after_cost": 0.0,
        "date_count": 0,
        "covered_date_count": 0,
        "row_count": 0,
        "daily_metrics": [],
    }


def _is_tradable(row: pd.Series) -> bool:
    return str(row.get("tradability_status") or "tradable") == "tradable"


def _has_complete_horizon(row: pd.Series, horizon: int) -> bool:
    value = row.get("incomplete_horizons")
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return True
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "[]":
            return True
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [item.strip() for item in text.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        parsed = value
    else:
        parsed = []
    try:
        return int(horizon) not in {int(item) for item in parsed}
    except (TypeError, ValueError):
        return True


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _precision(labels: List[bool], k: int) -> float:
    top = labels[: min(int(k), len(labels))]
    return _round(sum(1 for value in top if value) / len(top)) if top else 0.0


def _mrr(labels: List[bool]) -> float:
    for index, value in enumerate(labels, start=1):
        if value:
            return _round(1.0 / index)
    return 0.0


def _ndcg_from_returns(returns: List[float], k: int) -> float:
    top = returns[: min(int(k), len(returns))]
    if not top:
        return 0.0
    gains = [_gain(value) for value in top]
    ideal = sorted((_gain(value) for value in returns), reverse=True)[: len(top)]
    idcg = _dcg(ideal)
    return _round(_dcg(gains) / idcg) if idcg else 0.0


def _gain(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return min(max(number, 0.0), 60.0)


def _dcg(gains: List[float]) -> float:
    return sum(gain / math.log2(index + 1) for index, gain in enumerate(gains, start=1))


def _avg_top_k(values: List[float], k: int) -> float:
    top = values[: min(int(k), len(values))]
    return _round(mean(top)) if top else 0.0


def _date_values(df: pd.DataFrame, column: str) -> List[str]:
    if df is None or df.empty or column not in df.columns:
        return []
    return sorted(str(value) for value in df[column].dropna().unique().tolist())


def _num(values: Any) -> pd.Series:
    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce")
    return pd.Series(values, dtype="float64")


def _mean(values: List[float]) -> float:
    return _round(mean(values)) if values else 0.0


def _round(value: float) -> float:
    try:
        if not math.isfinite(float(value)):
            return 0.0
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _baseline_rows(items: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for name, item in items.items():
        rows.append({key: value for key, value in {"baseline": name, **item}.items() if key != "daily_metrics"})
    return rows


def _daily_rows(items: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for name, item in items.items():
        for daily in item.get("daily_metrics") or []:
            rows.append({"baseline": name, **daily})
    return rows
