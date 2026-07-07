from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from app.evaluation.offline_rerank_experiment import run_offline_rerank_experiment


POLICIES = {
    "momentum_macd_v1": {
        "return_60d_rank": 0.45,
        "return_20d_rank": 0.25,
        "macd_hist_rank": 0.30,
    },
    "balanced_liquidity_v1": {
        "return_60d_rank": 0.35,
        "return_20d_rank": 0.20,
        "macd_hist_rank": 0.25,
        "amount_rank": 0.20,
    },
}


def score_rerank_policy(df: pd.DataFrame, policy_name: str) -> pd.DataFrame:
    if policy_name not in POLICIES:
        raise ValueError(f"unknown policy: {policy_name}")
    local = _prepare_policy_features(df)
    score = _policy_score(local, policy_name)
    local["rerank_score"] = score
    local.attrs["feature_columns_used"] = list(POLICIES[policy_name].keys())
    return local.sort_values(["rerank_score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def run_rerank_policy_experiment(
    candidate_features_df: pd.DataFrame,
    policies: Iterable[str] | None = None,
    horizon: int = 10,
    train_ratio: float = 0.6,
    round_trip_cost_pct: float = 0.13,
    min_margin_pct: float = 0.30,
) -> Dict[str, Any]:
    selected_policies = list(policies or POLICIES.keys())
    local = _prepare_policy_features(candidate_features_df)
    rules: Dict[str, Dict[str, Any]] = {
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
    }
    for policy_name in selected_policies:
        if policy_name not in POLICIES:
            raise ValueError(f"unknown policy: {policy_name}")
        score_col = f"policy_{policy_name}_score"
        local[score_col] = _policy_score(local, policy_name)
        rules[f"policy_{policy_name}"] = {
            "kind": "column",
            "column": score_col,
            "direction": "desc",
            "feature_columns": list(POLICIES[policy_name].keys()),
        }
    summary = run_offline_rerank_experiment(
        local,
        horizon=horizon,
        train_ratio=train_ratio,
        round_trip_cost_pct=round_trip_cost_pct,
        min_margin_pct=min_margin_pct,
        rules=rules,
    )
    summary["audit_type"] = "rerank_policy_experiment"
    summary["policy_names"] = selected_policies
    summary["production_evidence"] = False
    summary["strategy_impact"] = False
    return summary


def write_rerank_policy_artifacts(summary: Dict[str, Any], output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "rerank_policy_experiment.json"
    rule_path = root / "rerank_policy_rule_summary.csv"
    report_path = root / "rerank_policy_experiment.md"
    serializable = {key: value for key, value in summary.items() if key != "report_markdown"}
    summary_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(_rule_rows(summary)).to_csv(rule_path, index=False)
    report_path.write_text(_render_markdown(summary), encoding="utf-8")
    return {"summary": str(summary_path), "rule_summary": str(rule_path), "report": str(report_path)}


def _prepare_policy_features(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "symbol" in local.columns:
        local["symbol"] = local["symbol"].map(_normalize_symbol)
    if "trade_date" in local.columns:
        local["trade_date"] = pd.to_datetime(local["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "macd_hist_rank" not in local.columns and "macd_hist" in local.columns:
        local["macd_hist_rank"] = _rank(local, "macd_hist")
    if "amount_rank" not in local.columns and "amount_pct_rank" in local.columns:
        local["amount_rank"] = pd.to_numeric(local["amount_pct_rank"], errors="coerce")
    if "amount_rank" not in local.columns and "amount" in local.columns:
        local["amount_rank"] = _rank(local, "amount")
    return local


def _policy_score(df: pd.DataFrame, policy_name: str) -> pd.Series:
    score = pd.Series(0.0, index=df.index)
    for column, weight in POLICIES[policy_name].items():
        if column not in df.columns:
            values = pd.Series(0.0, index=df.index)
        else:
            values = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
        score = score + values * float(weight)
    return score


def _rank(df: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(df[column], errors="coerce")
    if "trade_date" in df.columns:
        return values.groupby(df["trade_date"]).rank(pct=True, method="average")
    return values.rank(pct=True, method="average")


def _rule_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for name, item in (summary.get("rules") or {}).items():
        for subset in ["all", "train", "test"]:
            metrics = item.get(subset) or {}
            rows.append({"rule": name, "subset": subset, "status": item.get("status"), **metrics})
    return rows


def _render_markdown(summary: Dict[str, Any]) -> str:
    decision = summary.get("decision") or {}
    selected = summary.get("selected_rule") or {}
    lines = [
        "# Rerank Policy Experiment",
        "",
        f"status: `{summary.get('status')}`",
        f"decision: `{decision.get('outcome')}`",
        f"production_evidence: `{summary.get('production_evidence')}`",
        f"strategy_impact: `{summary.get('strategy_impact')}`",
        f"selected_rule: `{selected.get('name', '')}`",
        "",
        "| Rule | Train P@5 | Train Top5 After Cost | Test P@5 | Test Top5 After Cost |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, item in (summary.get("rules") or {}).items():
        train = item.get("train") or {}
        test = item.get("test") or {}
        lines.append(
            f"| `{name}` | {train.get('precision_at_5', 0.0)} | {train.get('top5_return_after_cost', 0.0)} | {test.get('precision_at_5', 0.0)} | {test.get('top5_return_after_cost', 0.0)} |"
        )
    lines.extend(["", "This experiment is read-only and does not modify production ranking."])
    return "\n".join(lines) + "\n"


def _normalize_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0].isdigit():
        text = text.split(".", 1)[0]
    if text.isdigit():
        return text.zfill(6)
    return text
