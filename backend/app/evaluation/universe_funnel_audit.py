from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


def audit_universe_funnel(
    universe_df: pd.DataFrame,
    candidates_df: pd.DataFrame,
    horizon: int = 10,
    top_rank_cutoff: int = 10,
) -> Dict[str, Any]:
    """Audit read-only full-market-to-candidate funnel outcomes."""
    universe = _normalize_universe(universe_df, horizon=horizon)
    candidates = _normalize_candidates(candidates_df)
    if universe.empty:
        items = pd.DataFrame()
        return {"summary": _summary(items, horizon=horizon, top_rank_cutoff=top_rank_cutoff), "items": items}
    candidate_keys = candidates[["trade_date", "symbol", "rank_no"]].drop_duplicates(["trade_date", "symbol"], keep="last") if not candidates.empty else pd.DataFrame(columns=["trade_date", "symbol", "rank_no"])
    items = universe.merge(candidate_keys, on=["trade_date", "symbol"], how="left")
    items["in_candidate"] = items["rank_no"].notna()
    items["candidate_rank_no"] = pd.to_numeric(items["rank_no"], errors="coerce")
    items["kept_final"] = items["in_candidate"].astype(bool)
    classified = [_classify(row, horizon=horizon, top_rank_cutoff=top_rank_cutoff) for _, row in items.iterrows()]
    items["last_layer"] = [item["last_layer"] for item in classified]
    items["failure_type"] = [item["failure_type"] for item in classified]
    items["reason"] = [item["reason"] for item in classified]
    items = items.drop(columns=["rank_no"], errors="ignore")
    ordered_columns = [
        "trade_date",
        "symbol",
        "name",
        f"strong_{horizon}d",
        f"return_{horizon}d_pct",
        "in_candidate",
        "candidate_rank_no",
        "last_layer",
        "kept_final",
        "failure_type",
        "reason",
        *[column for column in items.columns if column not in {
            "trade_date",
            "symbol",
            "name",
            f"strong_{horizon}d",
            f"return_{horizon}d_pct",
            "in_candidate",
            "candidate_rank_no",
            "last_layer",
            "kept_final",
            "failure_type",
            "reason",
        }],
    ]
    items = items.loc[:, list(dict.fromkeys([column for column in ordered_columns if column in items.columns]))]
    return {"summary": _summary(items, horizon=horizon, top_rank_cutoff=top_rank_cutoff), "items": items}


def build_universe_from_feature_and_label_panels(feature_panel: pd.DataFrame, label_panel: pd.DataFrame) -> pd.DataFrame:
    features = _normalize_panel(feature_panel)
    labels = _normalize_panel(label_panel)
    if features.empty:
        return labels
    if labels.empty:
        return features
    suffix_labels = [column for column in labels.columns if column not in {"trade_date", "symbol"} and column in features.columns]
    labels = labels.drop(columns=suffix_labels, errors="ignore")
    return features.merge(labels, on=["trade_date", "symbol"], how="inner")


def write_universe_funnel_artifacts(report: Dict[str, Any], output_dir: str | Path) -> Dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "universe_funnel_summary.json"
    items_path = root / "universe_funnel_items.csv"
    report_path = root / "universe_funnel_report.md"
    items = report.get("items")
    if not isinstance(items, pd.DataFrame):
        items = pd.DataFrame()
    summary = report.get("summary") or {}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    items.to_csv(items_path, index=False)
    report_path.write_text(render_universe_funnel_markdown(summary), encoding="utf-8")
    return {"summary": str(summary_path), "items": str(items_path), "report": str(report_path)}


def render_universe_funnel_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Universe Funnel Audit",
        "",
        f"status: `{summary.get('status')}`",
        f"horizon: `{summary.get('horizon')}`",
        f"top_rank_cutoff: `{summary.get('top_rank_cutoff')}`",
        f"universe_row_count: `{summary.get('universe_row_count')}`",
        f"candidate_row_count: `{summary.get('candidate_row_count')}`",
        f"strong_stock_count: `{summary.get('strong_stock_count')}`",
        f"strong_stock_recall_rate: `{summary.get('strong_stock_recall_rate')}`",
        f"recall_miss_strong_stock_count: `{summary.get('recall_miss_strong_stock_count')}`",
        f"ranking_late_strong_stock_count: `{summary.get('ranking_late_strong_stock_count')}`",
        f"top_rank_weak_stock_count: `{summary.get('top_rank_weak_stock_count')}`",
        f"unexplained_rejection_count: `{summary.get('unexplained_rejection_count')}`",
        "",
        "This audit is read-only. It does not regenerate candidates or change production strategy output.",
    ]
    return "\n".join(lines) + "\n"


def _classify(row: pd.Series, horizon: int, top_rank_cutoff: int) -> Dict[str, str]:
    strong = _to_bool(row.get(f"strong_{horizon}d"))
    in_candidate = _to_bool(row.get("in_candidate"))
    rank = _safe_float(row.get("candidate_rank_no"))
    if strong and not in_candidate:
        return {
            "last_layer": "full_market",
            "failure_type": "recall_miss_strong_stock",
            "reason": "future_strong_stock_not_in_candidate_pool",
        }
    if strong and in_candidate and math.isfinite(rank) and rank > int(top_rank_cutoff):
        return {
            "last_layer": "candidate_pool",
            "failure_type": "ranking_late_strong_stock",
            "reason": "future_strong_stock_ranked_below_top_cutoff",
        }
    if in_candidate and math.isfinite(rank) and rank <= int(top_rank_cutoff) and not strong:
        return {
            "last_layer": "candidate_pool",
            "failure_type": "top_rank_weak_stock",
            "reason": "top_ranked_candidate_not_future_strong",
        }
    return {
        "last_layer": "final_output" if in_candidate else "full_market",
        "failure_type": "none",
        "reason": "no_funnel_failure_detected",
    }


def _summary(items: pd.DataFrame, horizon: int, top_rank_cutoff: int) -> Dict[str, Any]:
    if items is None or items.empty:
        return {
            "status": "empty",
            "horizon": int(horizon),
            "top_rank_cutoff": int(top_rank_cutoff),
            "universe_row_count": 0,
            "candidate_row_count": 0,
            "strong_stock_count": 0,
            "strong_stock_recall_rate": 0.0,
            "recall_miss_strong_stock_count": 0,
            "ranking_late_strong_stock_count": 0,
            "top_rank_weak_stock_count": 0,
            "unexplained_rejection_count": 0,
        }
    strong_col = f"strong_{horizon}d"
    strong = items[strong_col].map(_to_bool) if strong_col in items.columns else pd.Series(False, index=items.index)
    candidate = items["in_candidate"].map(_to_bool) if "in_candidate" in items.columns else pd.Series(False, index=items.index)
    strong_count = int(strong.sum())
    recalled_strong = int((strong & candidate).sum())
    failure_counts = items["failure_type"].value_counts().to_dict() if "failure_type" in items.columns else {}
    return {
        "status": "completed",
        "horizon": int(horizon),
        "top_rank_cutoff": int(top_rank_cutoff),
        "universe_row_count": int(len(items)),
        "candidate_row_count": int(candidate.sum()),
        "date_count": int(items["trade_date"].nunique()) if "trade_date" in items.columns else 0,
        "strong_stock_count": strong_count,
        "strong_stock_recall_rate": _round(recalled_strong / strong_count) if strong_count else 0.0,
        "recall_miss_strong_stock_count": int(failure_counts.get("recall_miss_strong_stock", 0)),
        "ranking_late_strong_stock_count": int(failure_counts.get("ranking_late_strong_stock", 0)),
        "top_rank_weak_stock_count": int(failure_counts.get("top_rank_weak_stock", 0)),
        "unexplained_rejection_count": int(((~candidate) & (~strong)).sum()),
    }


def _normalize_universe(df: pd.DataFrame | None, horizon: int) -> pd.DataFrame:
    local = _normalize_panel(df)
    if local.empty:
        return local
    strong_col = f"strong_{horizon}d"
    return_col = f"return_{horizon}d_pct"
    if strong_col not in local.columns:
        local[strong_col] = False
    if return_col not in local.columns:
        local[return_col] = pd.NA
    return local


def _normalize_candidates(df: pd.DataFrame | None) -> pd.DataFrame:
    local = _normalize_panel(df)
    if local.empty:
        return local
    if "rank_no" not in local.columns:
        local["rank_no"] = pd.NA
    local["rank_no"] = pd.to_numeric(local["rank_no"], errors="coerce")
    return local


def _normalize_panel(df: pd.DataFrame | None) -> pd.DataFrame:
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


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _round(value: float) -> float:
    try:
        if not math.isfinite(float(value)):
            return 0.0
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0
