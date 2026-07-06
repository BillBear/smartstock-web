from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

import pandas as pd


FORWARD_LABEL_COLUMNS = {
    "strong_3d",
    "strong_5d",
    "strong_10d",
    "strong_20d",
    "return_3d_pct",
    "return_5d_pct",
    "return_10d_pct",
    "return_20d_pct",
    "max_profit_3d_pct",
    "max_profit_5d_pct",
    "max_profit_10d_pct",
    "max_profit_20d_pct",
    "max_drawdown_3d_pct",
    "max_drawdown_5d_pct",
    "max_drawdown_10d_pct",
    "max_drawdown_20d_pct",
}


DEFAULT_RERANK_RULES = {
    "current_smartstock_rank": {
        "kind": "column",
        "column": "rank_no",
        "direction": "asc",
        "feature_columns": ["rank_no"],
    },
    "current_smartstock_score_desc": {
        "kind": "column",
        "column": "score",
        "direction": "desc",
        "feature_columns": ["score"],
    },
    "return_60d_rank_desc": {
        "kind": "column",
        "column": "return_60d_rank",
        "direction": "desc",
        "feature_columns": ["return_60d_rank"],
    },
    "return_20d_rank_desc": {
        "kind": "column",
        "column": "return_20d_rank",
        "direction": "desc",
        "feature_columns": ["return_20d_rank"],
    },
    "macd_hist_desc": {
        "kind": "column",
        "column": "macd_hist",
        "direction": "desc",
        "feature_columns": ["macd_hist"],
    },
    "amount_pct_rank_desc": {
        "kind": "column",
        "column": "amount_pct_rank",
        "direction": "desc",
        "feature_columns": ["amount_pct_rank"],
    },
    "combo_trend_macd": {
        "kind": "combo",
        "weights": {
            "return_60d_rank": 0.45,
            "return_20d_rank": 0.20,
            "macd_hist_pct_rank": 0.35,
        },
        "feature_columns": ["return_60d_rank", "return_20d_rank", "macd_hist"],
    },
    "combo_balanced": {
        "kind": "combo",
        "weights": {
            "return_60d_rank": 0.35,
            "return_20d_rank": 0.25,
            "macd_hist_pct_rank": 0.25,
            "amount_pct_rank": 0.15,
        },
        "feature_columns": ["return_60d_rank", "return_20d_rank", "macd_hist", "amount_pct_rank"],
    },
    "combo_macd_momentum": {
        "kind": "combo",
        "weights": {
            "macd_hist_pct_rank": 0.50,
            "return_60d_rank": 0.30,
            "return_20d_rank": 0.20,
        },
        "feature_columns": ["macd_hist", "return_60d_rank", "return_20d_rank"],
    },
}


def run_offline_rerank_experiment(
    candidate_features_df: pd.DataFrame,
    horizon: int = 10,
    train_ratio: float = 0.6,
    round_trip_cost_pct: float = 0.13,
    min_margin_pct: float = 0.30,
    min_total_dates: int = 4,
    min_test_dates: int = 2,
    rules: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Compare fixed, read-only rerank rules against the historical SmartStock order."""
    rule_specs = dict(rules or DEFAULT_RERANK_RULES)
    label_col = f"strong_{int(horizon)}d"
    return_col = f"return_{int(horizon)}d_pct"
    local = _normalize_candidate_features(candidate_features_df)
    eligible = _eligible_rows(local, label_col=label_col, return_col=return_col, horizon=horizon)
    dates = _date_values(eligible)
    split = _walk_forward_split(dates, train_ratio=train_ratio)
    feature_columns_used = _feature_columns_used(rule_specs)
    result: Dict[str, Any] = {
        "status": "completed",
        "audit_type": "offline_rerank_experiment",
        "production_evidence": False,
        "strategy_impact": False,
        "horizon": int(horizon),
        "label_col": label_col,
        "return_col": return_col,
        "round_trip_cost_pct": float(round_trip_cost_pct),
        "min_margin_pct": float(min_margin_pct),
        "sample": {
            "input_row_count": int(len(local)),
            "eligible_row_count": int(len(eligible)),
            "eligible_date_count": int(len(dates)),
            "eligible_symbol_count": int(eligible["symbol"].nunique()) if not eligible.empty else 0,
            "min_date": dates[0] if dates else "",
            "max_date": dates[-1] if dates else "",
        },
        "split": split,
        "feature_columns_used": feature_columns_used,
        "forbidden_forward_columns": sorted(FORWARD_LABEL_COLUMNS.intersection(feature_columns_used)),
        "rules": {},
    }
    if len(dates) < int(min_total_dates) or len(split.get("test_dates") or []) < int(min_test_dates):
        result["status"] = "insufficient_sample"
        result["decision"] = {
            "outcome": "insufficient_walk_forward_sample",
            "production_action": "do_not_change_strategy",
            "reason": "not_enough_complete_labeled_dates_for_walk_forward",
        }
        result["report_markdown"] = render_offline_rerank_markdown(result)
        return result

    for name, spec in rule_specs.items():
        result["rules"][name] = _evaluate_rule(
            eligible,
            name=name,
            spec=spec,
            label_col=label_col,
            return_col=return_col,
            round_trip_cost_pct=round_trip_cost_pct,
            train_dates=split["train_dates"],
            test_dates=split["test_dates"],
        )
    result["selected_rule"] = _select_best_rule(result["rules"])
    result["decision"] = _summarize_decision(result, min_margin_pct=min_margin_pct)
    result["report_markdown"] = render_offline_rerank_markdown(result)
    return result


def write_offline_rerank_artifacts(summary: Dict[str, Any], output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "offline_rerank_experiment.json"
    rule_path = root / "offline_rerank_rule_summary.csv"
    daily_path = root / "offline_rerank_daily_metrics.csv"
    report_path = root / "offline_rerank_experiment.md"
    serializable_summary = {key: value for key, value in summary.items() if key != "report_markdown"}
    summary_path.write_text(json.dumps(serializable_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(_rule_summary_rows(summary)).to_csv(rule_path, index=False)
    pd.DataFrame(_daily_metric_rows(summary)).to_csv(daily_path, index=False)
    report_path.write_text(summary.get("report_markdown") or render_offline_rerank_markdown(summary), encoding="utf-8")
    return {
        "summary": str(summary_path),
        "rule_summary": str(rule_path),
        "daily_metrics": str(daily_path),
        "report": str(report_path),
    }


def render_offline_rerank_markdown(summary: Dict[str, Any]) -> str:
    sample = summary.get("sample") or {}
    split = summary.get("split") or {}
    decision = summary.get("decision") or {}
    selected = summary.get("selected_rule") or {}
    lines = [
        "# Offline Rerank Experiment",
        "",
        f"status: `{summary.get('status')}`",
        f"horizon: `{summary.get('horizon')}`",
        f"label_col: `{summary.get('label_col')}`",
        f"return_col: `{summary.get('return_col')}`",
        f"round_trip_cost_pct: `{summary.get('round_trip_cost_pct')}`",
        f"production_evidence: `{summary.get('production_evidence')}`",
        f"strategy_impact: `{summary.get('strategy_impact')}`",
        f"decision: `{decision.get('outcome')}`",
        f"production_action: `{decision.get('production_action')}`",
        "",
        "## Sample",
        "",
        f"- input_row_count: `{sample.get('input_row_count')}`",
        f"- eligible_row_count: `{sample.get('eligible_row_count')}`",
        f"- eligible_date_count: `{sample.get('eligible_date_count')}`",
        f"- eligible_symbol_count: `{sample.get('eligible_symbol_count')}`",
        f"- date_range: `{sample.get('min_date')}` to `{sample.get('max_date')}`",
        f"- train_dates: `{len(split.get('train_dates') or [])}`",
        f"- test_dates: `{len(split.get('test_dates') or [])}`",
        "",
        "## Selected Rule",
        "",
        f"- name: `{selected.get('name', '')}`",
        f"- selected_from: `{selected.get('selected_from', '')}`",
        "",
        "## Rule Results",
        "",
        "| Rule | Status | Train P@5 | Train Top5 After Cost | Test P@5 | Test Top5 After Cost | Test NDCG@10 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for name, item in (summary.get("rules") or {}).items():
        train = item.get("train") or {}
        test = item.get("test") or {}
        lines.append(
            f"| `{name}` | `{item.get('status')}` | {train.get('precision_at_5', 0.0)} | {train.get('top5_return_after_cost', 0.0)} | {test.get('precision_at_5', 0.0)} | {test.get('top5_return_after_cost', 0.0)} | {test.get('ndcg_at_10', 0.0)} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This is an offline read-only rerank experiment on historical candidate rows.",
            "- It does not change production selection, ranking, buy/sell, take-profit, stop-loss, or position sizing logic.",
            "- Forward label columns are forbidden as rerank features.",
        ]
    )
    if summary.get("forbidden_forward_columns"):
        lines.extend(["", f"Forbidden forward columns found in feature list: `{summary.get('forbidden_forward_columns')}`"])
    return "\n".join(lines) + "\n"


def _evaluate_rule(
    df: pd.DataFrame,
    name: str,
    spec: Dict[str, Any],
    label_col: str,
    return_col: str,
    round_trip_cost_pct: float,
    train_dates: List[str],
    test_dates: List[str],
) -> Dict[str, Any]:
    forbidden = _rule_forbidden_columns(spec)
    if forbidden:
        empty = _empty_metrics()
        return {
            "status": "blocked",
            "missing_reason": "forbidden_forward_feature_" + "_".join(forbidden),
            "feature_columns": list(spec.get("feature_columns") or []),
            "all": empty,
            "train": empty,
            "test": empty,
            "daily_metrics": [],
        }
    scored, reason = _score_rule(df, spec, f"__rerank_score_{name}")
    if reason:
        empty = _empty_metrics()
        return {
            "status": "missing",
            "missing_reason": reason,
            "feature_columns": list(spec.get("feature_columns") or []),
            "all": empty,
            "train": empty,
            "test": empty,
            "daily_metrics": [],
        }
    score_col = f"__rerank_score_{name}"
    daily = _daily_metrics(scored, score_col=score_col, label_col=label_col, return_col=return_col)
    train_daily = [item for item in daily if item["trade_date"] in set(train_dates)]
    test_daily = [item for item in daily if item["trade_date"] in set(test_dates)]
    return {
        "status": "ok" if daily else "insufficient_labeled_rows",
        "missing_reason": "" if daily else "no_labeled_rows",
        "feature_columns": list(spec.get("feature_columns") or []),
        "all": _aggregate_metrics(daily, round_trip_cost_pct=round_trip_cost_pct),
        "train": _aggregate_metrics(train_daily, round_trip_cost_pct=round_trip_cost_pct),
        "test": _aggregate_metrics(test_daily, round_trip_cost_pct=round_trip_cost_pct),
        "daily_metrics": daily,
    }


def _score_rule(df: pd.DataFrame, spec: Dict[str, Any], score_col: str) -> Tuple[pd.DataFrame, str]:
    local = df.copy()
    kind = str(spec.get("kind") or "")
    if kind == "column":
        column = str(spec.get("column") or "")
        if column not in local.columns:
            return local, f"missing_{column}"
        score = _num(local[column])
        if spec.get("direction") == "asc":
            score = -score
        local[score_col] = score
        return local, ""
    if kind == "combo":
        weights = spec.get("weights") or {}
        missing = [column for column in _combo_base_columns(weights) if column not in local.columns]
        if missing:
            return local, "missing_" + "_".join(missing)
        local = _attach_combo_features(local)
        score = pd.Series(0.0, index=local.index)
        for column, weight in weights.items():
            if column not in local.columns:
                return local, f"missing_{column}"
            score = score + _num(local[column]).fillna(0.0) * float(weight)
        local[score_col] = score
        return local, ""
    return local, "unknown_rule_kind"


def _rule_forbidden_columns(spec: Dict[str, Any]) -> List[str]:
    columns = set(spec.get("feature_columns") or [])
    if spec.get("column"):
        columns.add(str(spec.get("column")))
    columns.update(str(column) for column in (spec.get("weights") or {}).keys())
    return sorted(columns.intersection(FORWARD_LABEL_COLUMNS))


def _attach_combo_features(df: pd.DataFrame) -> pd.DataFrame:
    local = df.copy()
    if "macd_hist" in local.columns and "macd_hist_pct_rank" not in local.columns:
        local["macd_hist_pct_rank"] = _date_pct_rank(local, "macd_hist")
    return local


def _combo_base_columns(weights: Dict[str, Any]) -> List[str]:
    columns = []
    for column in weights.keys():
        if column == "macd_hist_pct_rank":
            columns.append("macd_hist")
        else:
            columns.append(column)
    return columns


def _daily_metrics(df: pd.DataFrame, score_col: str, label_col: str, return_col: str) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    local = df.copy()
    local[score_col] = _num(local[score_col])
    local[label_col] = local[label_col].map(_to_bool)
    local[return_col] = _num(local[return_col])
    local = local[local[score_col].notna() & local[return_col].notna()].copy()
    if local.empty:
        return []
    daily: List[Dict[str, Any]] = []
    for date, rows in local.groupby("trade_date", sort=True):
        ordered = rows.sort_values([score_col, "symbol"], ascending=[False, True]).reset_index(drop=True)
        labels = ordered[label_col].astype(bool).tolist()
        returns = ordered[return_col].astype(float).tolist()
        strong_count = sum(1 for value in labels if value)
        daily.append(
            {
                "trade_date": str(date),
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
    return daily


def _aggregate_metrics(daily: List[Dict[str, Any]], round_trip_cost_pct: float) -> Dict[str, Any]:
    if not daily:
        return _empty_metrics()
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
        "date_count": int(len(daily)),
        "row_count": int(sum(item["candidate_count"] for item in daily)),
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
        "row_count": 0,
    }


def _select_best_rule(rules: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    candidates = []
    for name, item in rules.items():
        if item.get("status") != "ok":
            continue
        train = item.get("train") or {}
        candidates.append(
            (
                float(train.get("top5_return_after_cost") or 0.0),
                float(train.get("ndcg_at_10") or 0.0),
                float(train.get("precision_at_5") or 0.0),
                name,
            )
        )
    if not candidates:
        return {"name": "", "selected_from": "train", "reason": "no_available_rule"}
    best = sorted(candidates, key=lambda item: (-item[0], -item[1], -item[2], item[3]))[0]
    return {
        "name": best[3],
        "selected_from": "train",
        "train_top5_return_after_cost": _round(best[0]),
        "train_ndcg_at_10": _round(best[1]),
        "train_precision_at_5": _round(best[2]),
    }


def _summarize_decision(summary: Dict[str, Any], min_margin_pct: float) -> Dict[str, Any]:
    selected_name = (summary.get("selected_rule") or {}).get("name") or ""
    rules = summary.get("rules") or {}
    current = rules.get("current_smartstock_rank") or {}
    selected = rules.get(selected_name) or {}
    current_test = current.get("test") or {}
    selected_test = selected.get("test") or {}
    if not selected_name:
        return {
            "outcome": "no_available_rerank_rule",
            "production_action": "do_not_change_strategy",
            "reason": "all_rules_missing_or_unlabeled",
        }
    margin = _round(float(selected_test.get("top5_return_after_cost") or 0.0) - float(current_test.get("top5_return_after_cost") or 0.0))
    if margin >= float(min_margin_pct):
        outcome = "fixed_rerank_beats_current_on_holdout"
    elif -margin >= float(min_margin_pct):
        outcome = "current_rank_beats_fixed_rerank_on_holdout"
    else:
        outcome = "inconclusive_holdout_margin"
    return {
        "outcome": outcome,
        "production_action": "do_not_change_strategy",
        "selected_rule": selected_name,
        "current_test_top5_return_after_cost": current_test.get("top5_return_after_cost", 0.0),
        "selected_test_top5_return_after_cost": selected_test.get("top5_return_after_cost", 0.0),
        "selected_minus_current_test_pct": margin,
        "required_margin_pct": float(min_margin_pct),
        "reason": "offline_candidate_panel_only_not_production_evidence",
    }


def _normalize_candidate_features(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "trade_date" not in local.columns and "date" in local.columns:
        local["trade_date"] = local["date"]
    if "trade_date" not in local.columns or "symbol" not in local.columns:
        return pd.DataFrame()
    local["trade_date"] = pd.to_datetime(local["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local = local[local["trade_date"].notna()].copy()
    local["symbol"] = local["symbol"].map(_normalize_symbol)
    local = local[local["symbol"] != ""].copy()
    return local.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _eligible_rows(df: pd.DataFrame, label_col: str, return_col: str, horizon: int) -> pd.DataFrame:
    if df.empty or any(column not in df.columns for column in ["trade_date", "symbol", label_col, return_col]):
        return pd.DataFrame()
    local = df.copy()
    local[return_col] = _num(local[return_col])
    local = local[local[return_col].notna()].copy()
    local = local[local.apply(lambda row: _is_tradable(row) and _has_complete_horizon(row, horizon), axis=1)].copy()
    if "has_60d_lookback" in local.columns:
        local = local[local["has_60d_lookback"].map(_to_bool)].copy()
    return local.reset_index(drop=True)


def _walk_forward_split(dates: List[str], train_ratio: float) -> Dict[str, Any]:
    if len(dates) < 2:
        return {"train_dates": dates, "test_dates": [], "train_ratio": float(train_ratio)}
    ratio = min(max(float(train_ratio), 0.1), 0.9)
    split_index = int(len(dates) * ratio)
    split_index = max(1, min(len(dates) - 1, split_index))
    return {
        "train_dates": dates[:split_index],
        "test_dates": dates[split_index:],
        "train_ratio": ratio,
        "split_index": split_index,
    }


def _feature_columns_used(rules: Dict[str, Dict[str, Any]]) -> List[str]:
    columns = []
    for spec in rules.values():
        columns.extend(spec.get("feature_columns") or [])
    return sorted(set(columns))


def _date_pct_rank(df: pd.DataFrame, column: str) -> pd.Series:
    values = _num(df[column])
    return values.groupby(df["trade_date"]).rank(method="average", pct=True)


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


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return text


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


def _mean(values: List[float]) -> float:
    return _round(mean(values)) if values else 0.0


def _num(values: Any) -> pd.Series:
    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce")
    return pd.Series(values, dtype="float64")


def _date_values(df: pd.DataFrame) -> List[str]:
    if df is None or df.empty or "trade_date" not in df.columns:
        return []
    return sorted(str(value) for value in df["trade_date"].dropna().unique().tolist())


def _round(value: float) -> float:
    try:
        if not math.isfinite(float(value)):
            return 0.0
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _rule_summary_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for name, item in (summary.get("rules") or {}).items():
        for subset in ["all", "train", "test"]:
            metrics = item.get(subset) or {}
            rows.append(
                {
                    "rule": name,
                    "subset": subset,
                    "status": item.get("status"),
                    "missing_reason": item.get("missing_reason", ""),
                    **metrics,
                }
            )
    return rows


def _daily_metric_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    train_dates = set((summary.get("split") or {}).get("train_dates") or [])
    test_dates = set((summary.get("split") or {}).get("test_dates") or [])
    rows = []
    for name, item in (summary.get("rules") or {}).items():
        for daily in item.get("daily_metrics") or []:
            date = daily.get("trade_date")
            subset = "train" if date in train_dates else "test" if date in test_dates else "unknown"
            rows.append({"rule": name, "subset": subset, **daily})
    return rows
