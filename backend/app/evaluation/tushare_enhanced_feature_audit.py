from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from app.evaluation.offline_rerank_experiment import run_offline_rerank_experiment


DEFAULT_ENDPOINTS = [
    "daily_basic",
    "adj_factor",
    "trade_cal",
    "stk_limit",
    "suspend_d",
    "index_daily",
    "index_dailybasic",
    "moneyflow_hsgt",
    "moneyflow",
]

BASELINE_RULE = "return_60d_rank_desc"

ENHANCED_RERANK_RULES = {
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
    BASELINE_RULE: {
        "kind": "column",
        "column": "return_60d_rank",
        "direction": "desc",
        "feature_columns": ["return_60d_rank"],
    },
    "adj_return_60d_rank_desc": {
        "kind": "column",
        "column": "adj_return_60d_rank",
        "direction": "desc",
        "feature_columns": ["adj_return_60d_rank"],
    },
    "turnover_rate_rank_desc": {
        "kind": "column",
        "column": "turnover_rate_rank",
        "direction": "desc",
        "feature_columns": ["turnover_rate_rank"],
    },
    "volume_ratio_rank_desc": {
        "kind": "column",
        "column": "volume_ratio_rank",
        "direction": "desc",
        "feature_columns": ["volume_ratio_rank"],
    },
    "moneyflow_strength_desc": {
        "kind": "column",
        "column": "main_net_inflow_ratio_rank",
        "direction": "desc",
        "feature_columns": ["main_net_inflow_ratio_rank"],
    },
    "turnover_momentum_combo": {
        "kind": "combo",
        "weights": {
            "adj_return_60d_rank": 0.45,
            "turnover_rate_rank": 0.35,
            "volume_ratio_rank": 0.20,
        },
        "feature_columns": ["adj_return_60d_rank", "turnover_rate_rank", "volume_ratio_rank"],
    },
    "limit_aware_momentum_combo": {
        "kind": "combo",
        "weights": {
            "adj_return_60d_rank": 0.50,
            "turnover_rate_rank": 0.25,
            "limit_buyability_rank": 0.25,
        },
        "feature_columns": ["adj_return_60d_rank", "turnover_rate_rank", "limit_buyability_rank"],
    },
}

ENHANCED_RULE_NAMES = {
    "adj_return_60d_rank_desc",
    "turnover_rate_rank_desc",
    "volume_ratio_rank_desc",
    "moneyflow_strength_desc",
    "turnover_momentum_combo",
    "limit_aware_momentum_combo",
}


def audit_tushare_endpoint_availability(
    client: Any,
    sample_date: str,
    sample_ts_code: str = "000001.SZ",
    endpoints: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Probe TuShare-like client methods without raising endpoint errors."""
    normalized_date = _normalize_date(sample_date)
    trade_date = normalized_date.replace("-", "")
    summary: Dict[str, Any] = {
        "audit_type": "tushare_endpoint_availability",
        "sample_date": normalized_date,
        "sample_ts_code": sample_ts_code,
        "endpoints": {},
    }
    for endpoint in list(endpoints or DEFAULT_ENDPOINTS):
        method = getattr(client, endpoint, None)
        if method is None:
            summary["endpoints"][endpoint] = {
                "status": "missing_method",
                "row_count": 0,
                "columns": [],
                "error": "",
            }
            continue
        try:
            df = method(trade_date=trade_date, ts_code=sample_ts_code)
        except Exception as exc:  # endpoint probes must not interrupt audits
            summary["endpoints"][endpoint] = {
                "status": "error",
                "row_count": 0,
                "columns": [],
                "error": str(exc),
            }
            continue
        frame = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df or [])
        summary["endpoints"][endpoint] = {
            "status": "empty" if frame.empty else "available",
            "row_count": int(len(frame)),
            "columns": [str(column) for column in frame.columns],
            "error": "",
        }
    return summary


def build_tushare_enhanced_feature_panel(
    base_panel: pd.DataFrame,
    daily_basic_panel: pd.DataFrame | None = None,
    adj_factor_panel: pd.DataFrame | None = None,
    stk_limit_panel: pd.DataFrame | None = None,
    suspend_panel: pd.DataFrame | None = None,
    index_panel: pd.DataFrame | None = None,
    moneyflow_panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a read-only pre-signal feature panel from optional TuShare panels."""
    panel = _normalize_symbol_date_panel(base_panel)
    if panel.empty:
        return panel
    panel = _merge_optional_panel(
        panel,
        daily_basic_panel,
        [
            "turnover_rate",
            "turnover_rate_f",
            "volume_ratio",
            "pe",
            "pe_ttm",
            "pb",
            "ps",
            "ps_ttm",
            "dv_ratio",
            "dv_ttm",
            "total_share",
            "float_share",
            "free_share",
            "total_mv",
            "circ_mv",
        ],
    )
    panel = _merge_optional_panel(panel, adj_factor_panel, ["adj_factor"])
    panel = _merge_optional_panel(panel, stk_limit_panel, ["up_limit", "down_limit"])
    panel = _merge_suspend_flags(panel, suspend_panel)
    panel = _merge_optional_panel(
        panel,
        moneyflow_panel,
        [
            "net_mf_amount",
            "buy_lg_amount",
            "buy_elg_amount",
            "sell_lg_amount",
            "sell_elg_amount",
        ],
    )
    panel = _attach_index_context(panel, index_panel)
    panel = _attach_daily_basic_features(panel)
    panel = _attach_adjusted_return_features(panel)
    panel = _attach_limit_features(panel)
    panel = _attach_moneyflow_features(panel)
    return panel.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def run_tushare_enhanced_feature_audit(
    feature_panel: pd.DataFrame,
    horizon: int = 10,
    train_ratio: float = 0.6,
    round_trip_cost_pct: float = 0.13,
    min_margin_pct: float = 0.30,
    min_total_dates: int = 4,
    min_test_dates: int = 2,
) -> Dict[str, Any]:
    """Compare enhanced TuShare rules against the current hard rule benchmark."""
    prepared = _prepare_audit_panel(feature_panel)
    summary = run_offline_rerank_experiment(
        prepared,
        horizon=horizon,
        train_ratio=train_ratio,
        round_trip_cost_pct=round_trip_cost_pct,
        min_margin_pct=min_margin_pct,
        min_total_dates=min_total_dates,
        min_test_dates=min_test_dates,
        rules=ENHANCED_RERANK_RULES,
    )
    best_enhanced = _select_best_enhanced_rule(summary.get("rules") or {})
    summary["audit_type"] = "tushare_enhanced_feature_audit"
    summary["production_evidence"] = False
    summary["strategy_impact"] = False
    summary["production_action"] = "do_not_change_strategy"
    summary["baseline_rule"] = BASELINE_RULE
    summary["best_enhanced_rule"] = best_enhanced.get("name", "")
    summary["ml_v2_2_gate"] = _evaluate_ml_v22_gate(
        summary.get("rules") or {},
        baseline_rule=BASELINE_RULE,
        candidate_rule=best_enhanced.get("name", ""),
        min_margin_pct=min_margin_pct,
    )
    summary["decision"] = {
        "outcome": "enhanced_feature_gate_passed" if summary["ml_v2_2_gate"]["allowed"] else "enhanced_feature_gate_blocked",
        "production_action": "do_not_change_strategy",
        "reason": "read_only_feature_audit_not_production_evidence",
    }
    summary["report_markdown"] = render_tushare_enhanced_feature_markdown(summary)
    return summary


def write_tushare_enhanced_feature_artifacts(
    summary: Dict[str, Any],
    feature_panel: pd.DataFrame,
    output_dir: str | Path,
) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "tushare_enhanced_feature_audit.json"
    panel_path = root / "tushare_enhanced_feature_panel.csv"
    rule_path = root / "tushare_enhanced_rule_summary.csv"
    report_path = root / "tushare_enhanced_feature_audit.md"
    serializable = {key: value for key, value in summary.items() if key != "report_markdown"}
    summary_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    feature_panel.to_csv(panel_path, index=False)
    pd.DataFrame(_rule_summary_rows(summary)).to_csv(rule_path, index=False)
    report_path.write_text(summary.get("report_markdown") or render_tushare_enhanced_feature_markdown(summary), encoding="utf-8")
    return {
        "summary": str(summary_path),
        "feature_panel": str(panel_path),
        "rule_summary": str(rule_path),
        "report": str(report_path),
    }


def _normalize_date(value: Any) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _normalize_symbol_date_panel(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    local = df.copy()
    if "symbol" not in local.columns and "ts_code" in local.columns:
        local["symbol"] = local["ts_code"]
    if "trade_date" not in local.columns and "date" in local.columns:
        local["trade_date"] = local["date"]
    if "symbol" not in local.columns or "trade_date" not in local.columns:
        return pd.DataFrame()
    local["symbol"] = local["symbol"].map(_normalize_symbol)
    local["trade_date"] = local["trade_date"].map(_normalize_date)
    local = local[(local["symbol"] != "") & (local["trade_date"] != "")].copy()
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


def _merge_optional_panel(panel: pd.DataFrame, optional: pd.DataFrame | None, columns: List[str]) -> pd.DataFrame:
    other = _normalize_symbol_date_panel(optional)
    if other.empty:
        for column in columns:
            if column not in panel.columns:
                panel[column] = pd.NA
        return panel
    keep = ["symbol", "trade_date"] + [column for column in columns if column in other.columns]
    if len(keep) <= 2:
        return panel
    slim = other[keep].drop_duplicates(["symbol", "trade_date"], keep="last")
    overlapping = [column for column in keep[2:] if column in panel.columns]
    if overlapping:
        panel = panel.drop(columns=overlapping)
    return panel.merge(slim, on=["symbol", "trade_date"], how="left")


def _merge_suspend_flags(panel: pd.DataFrame, suspend_panel: pd.DataFrame | None) -> pd.DataFrame:
    other = _normalize_symbol_date_panel(suspend_panel)
    if other.empty:
        panel["suspend_risk_flag"] = False
        return panel
    flags = other[["symbol", "trade_date"]].drop_duplicates().copy()
    flags["suspend_risk_flag"] = True
    merged = panel.merge(flags, on=["symbol", "trade_date"], how="left")
    merged["suspend_risk_flag"] = merged["suspend_risk_flag"].eq(True)
    return merged


def _attach_daily_basic_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    for column in [
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_mv",
        "circ_mv",
        "free_share",
    ]:
        if column in local.columns:
            local[column] = _num(local[column])
    for column in ["turnover_rate", "turnover_rate_f", "volume_ratio", "pe_ttm", "pb", "total_mv", "circ_mv"]:
        if column in local.columns:
            local[f"{column}_rank"] = _date_pct_rank(local, column)
    if "turnover_rate" in local.columns:
        grouped = local.sort_values(["symbol", "trade_date"]).groupby("symbol")["turnover_rate"]
        avg_5 = grouped.transform(lambda values: values.rolling(5, min_periods=1).mean())
        avg_20 = grouped.transform(lambda values: values.rolling(20, min_periods=1).mean())
        local["turnover_ratio_5_20"] = avg_5 / avg_20.replace(0, pd.NA)
        local["turnover_persistence_5d"] = grouped.transform(lambda values: values.diff().gt(0).rolling(5, min_periods=1).sum())
    return local


def _attach_adjusted_return_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    if "close" not in local.columns:
        return local
    local["close"] = _num(local["close"])
    if "adj_factor" in local.columns:
        local["adj_factor"] = _num(local["adj_factor"]).fillna(1.0)
    else:
        local["adj_factor"] = 1.0
    local = local.sort_values(["symbol", "trade_date"]).copy()
    local["adj_close"] = local["close"] * local["adj_factor"]
    grouped = local.groupby("symbol")["adj_close"]
    for horizon in [5, 20, 60]:
        column = f"adj_return_{horizon}d_pct"
        local[column] = grouped.pct_change(horizon) * 100.0
        local[f"adj_return_{horizon}d_rank"] = _date_pct_rank(local, column)
    return local


def _attach_limit_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    if not {"close", "up_limit", "down_limit"}.issubset(local.columns):
        local["distance_to_up_limit_pct"] = pd.NA
        local["distance_to_down_limit_pct"] = pd.NA
        local["hit_limit_up_today"] = False
        return local
    close = _num(local["close"])
    up = _num(local["up_limit"])
    down = _num(local["down_limit"])
    local["distance_to_up_limit_pct"] = ((up - close) / close.replace(0, pd.NA)) * 100.0
    local["distance_to_down_limit_pct"] = ((close - down) / close.replace(0, pd.NA)) * 100.0
    local["hit_limit_up_today"] = close.ge(up * 0.999)
    local["near_limit_up_3pct"] = local["distance_to_up_limit_pct"].le(3.0)
    local["limit_buyability_rank"] = _date_pct_rank(local, "distance_to_up_limit_pct")
    return local


def _attach_moneyflow_features(panel: pd.DataFrame) -> pd.DataFrame:
    local = panel.copy()
    for column in ["net_mf_amount", "buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"]:
        if column in local.columns:
            local[column] = _num(local[column])
            local[f"{column}_rank"] = _date_pct_rank(local, column)
    if {"net_mf_amount", "buy_lg_amount", "buy_elg_amount"}.issubset(local.columns):
        positive = local["buy_lg_amount"].fillna(0.0) + local["buy_elg_amount"].fillna(0.0)
        local["main_net_inflow_ratio"] = local["net_mf_amount"] / positive.replace(0, pd.NA)
        local["main_net_inflow_ratio_rank"] = _date_pct_rank(local, "main_net_inflow_ratio")
    return local


def _attach_index_context(panel: pd.DataFrame, index_panel: pd.DataFrame | None) -> pd.DataFrame:
    if index_panel is None or index_panel.empty:
        return panel
    local_index = index_panel.copy()
    if "trade_date" not in local_index.columns:
        return panel
    local_index["trade_date"] = local_index["trade_date"].map(_normalize_date)
    market_columns = [column for column in ["index_return_5d", "index_return_20d", "index_volatility_20d"] if column in local_index.columns]
    if not market_columns:
        return panel
    context = local_index[["trade_date"] + market_columns].drop_duplicates("trade_date", keep="last")
    return panel.merge(context, on="trade_date", how="left")


def _date_pct_rank(df: pd.DataFrame, column: str) -> pd.Series:
    if "trade_date" not in df.columns or column not in df.columns:
        return pd.Series(pd.NA, index=df.index)
    values = _num(df[column])
    return values.groupby(df["trade_date"]).rank(method="average", pct=True)


def _num(values: Any) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")


def _prepare_audit_panel(feature_panel: pd.DataFrame | None) -> pd.DataFrame:
    if feature_panel is None or feature_panel.empty:
        return pd.DataFrame()
    local = feature_panel.copy()
    if "limit_buyability_rank" not in local.columns and "distance_to_up_limit_pct" in local.columns:
        local["limit_buyability_rank"] = _date_pct_rank(local, "distance_to_up_limit_pct")
    return local


def _select_best_enhanced_rule(rules: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    candidates = []
    for name in sorted(ENHANCED_RULE_NAMES):
        item = rules.get(name) or {}
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
        return {"name": "", "reason": "no_available_enhanced_rule"}
    best = sorted(candidates, key=lambda item: (-item[0], -item[1], -item[2], item[3]))[0]
    return {
        "name": best[3],
        "train_top5_return_after_cost": _round(best[0]),
        "train_ndcg_at_10": _round(best[1]),
        "train_precision_at_5": _round(best[2]),
    }


def _evaluate_ml_v22_gate(
    rules: Dict[str, Dict[str, Any]],
    baseline_rule: str,
    candidate_rule: str,
    min_margin_pct: float,
) -> Dict[str, Any]:
    baseline = rules.get(baseline_rule) or {}
    candidate = rules.get(candidate_rule) or {}
    baseline_test = baseline.get("test") or {}
    candidate_test = candidate.get("test") or {}
    margin = _round(float(candidate_test.get("top5_return_after_cost") or 0.0) - float(baseline_test.get("top5_return_after_cost") or 0.0))
    ndcg_delta = _round(float(candidate_test.get("ndcg_at_10") or 0.0) - float(baseline_test.get("ndcg_at_10") or 0.0))
    reasons: List[str] = []
    if not candidate_rule or candidate.get("status") != "ok":
        reasons.append("no_available_enhanced_rule")
    if margin < float(min_margin_pct):
        reasons.append("top5_after_cost_margin_below_required")
    if ndcg_delta < 0:
        reasons.append("ndcg_at_10_worse_than_return_60d_baseline")
    return {
        "allowed": not reasons,
        "production_action": "do_not_change_strategy",
        "baseline_rule": baseline_rule,
        "candidate_rule": candidate_rule,
        "required_top5_after_cost_margin_pct": float(min_margin_pct),
        "top5_after_cost_margin_pct": margin,
        "ndcg_at_10_delta": ndcg_delta,
        "baseline_test_top5_return_after_cost": baseline_test.get("top5_return_after_cost", 0.0),
        "candidate_test_top5_return_after_cost": candidate_test.get("top5_return_after_cost", 0.0),
        "baseline_test_ndcg_at_10": baseline_test.get("ndcg_at_10", 0.0),
        "candidate_test_ndcg_at_10": candidate_test.get("ndcg_at_10", 0.0),
        "blocking_reasons": reasons,
    }


def render_tushare_enhanced_feature_markdown(summary: Dict[str, Any]) -> str:
    gate = summary.get("ml_v2_2_gate") or {}
    sample = summary.get("sample") or {}
    lines = [
        "# TuShare Enhanced Feature Audit",
        "",
        f"status: `{summary.get('status')}`",
        f"production_evidence: `{summary.get('production_evidence')}`",
        f"strategy_impact: `{summary.get('strategy_impact')}`",
        f"production_action: `{summary.get('production_action')}`",
        f"baseline_rule: `{summary.get('baseline_rule')}`",
        f"best_enhanced_rule: `{summary.get('best_enhanced_rule')}`",
        f"ml_v2_2_allowed: `{gate.get('allowed')}`",
        "",
        "## Sample",
        "",
        f"- eligible_date_count: `{sample.get('eligible_date_count')}`",
        f"- eligible_row_count: `{sample.get('eligible_row_count')}`",
        f"- eligible_symbol_count: `{sample.get('eligible_symbol_count')}`",
        "",
        "## ML V2.2 Gate",
        "",
        f"- top5_after_cost_margin_pct: `{gate.get('top5_after_cost_margin_pct')}`",
        f"- required_margin_pct: `{gate.get('required_top5_after_cost_margin_pct')}`",
        f"- ndcg_at_10_delta: `{gate.get('ndcg_at_10_delta')}`",
        f"- blocking_reasons: `{gate.get('blocking_reasons')}`",
        "",
        "## Rule Results",
        "",
        "| Rule | Status | Test P@5 | Test Top5 After Cost | Test NDCG@10 |",
        "|---|---|---:|---:|---:|",
    ]
    for name, item in (summary.get("rules") or {}).items():
        test = item.get("test") or {}
        lines.append(
            f"| `{name}` | `{item.get('status')}` | {test.get('precision_at_5', 0.0)} | {test.get('top5_return_after_cost', 0.0)} | {test.get('ndcg_at_10', 0.0)} |"
        )
    lines.extend(
        [
            "",
            "This audit is read-only. It does not modify production selection, ranking, buy/sell, take-profit, stop-loss, or position sizing logic.",
        ]
    )
    return "\n".join(lines) + "\n"


def _rule_summary_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
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


def _round(value: Any, digits: int = 6) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(number):
        return 0.0
    return round(number, digits)
