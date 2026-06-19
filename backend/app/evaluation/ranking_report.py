"""CSV/JSON report writer for ranking evaluation artifacts."""
from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

from app.evaluation.ranking_diagnostics import build_ranking_diagnostics, factor_correlations
from app.evaluation.ranking_metrics import evaluate_daily_ranking, rank_percentile_return_curve


REPORT_SCHEMA_VERSION = "1.0"


def build_ranking_report(
    candidate_rows: List[Dict[str, Any]],
    strategy_code: str,
    risk_level: str,
    start_date: str,
    end_date: str,
    horizons: List[int],
    top_k_values: List[int],
    output_dir: str,
    label_config: Dict[str, Any],
    coverage: Dict[str, Any],
    execution_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Write ranking evaluation artifacts and return summary payload."""
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [dict(row) for row in candidate_rows or []]
    horizons = [int(item) for item in horizons]
    k_values = _metric_k_values(top_k_values)
    daily_metrics = _daily_metrics(rows, horizons, k_values)
    percentile_curve = _percentile_curve(rows, horizons)
    diagnostics = {str(horizon): build_ranking_diagnostics(rows, horizon) for horizon in horizons}
    correlation_rows = []
    for horizon in horizons:
        correlation_rows.extend(factor_correlations(rows, horizon))

    artifact_paths = {
        "ranking_daily_metrics.csv": "ranking_daily_metrics.csv",
        "ranking_item_labels.csv": "ranking_item_labels.csv",
        "ranking_rank_percentile_curve.csv": "ranking_rank_percentile_curve.csv",
        "ranking_miss_samples.csv": "ranking_miss_samples.csv",
        "ranking_false_positive_samples.csv": "ranking_false_positive_samples.csv",
        "ranking_factor_correlations.csv": "ranking_factor_correlations.csv",
        "ranking_diagnostics.json": "ranking_diagnostics.json",
    }

    write_csv(out_dir / "ranking_daily_metrics.csv", daily_metrics)
    write_csv(out_dir / "ranking_item_labels.csv", rows)
    write_csv(out_dir / "ranking_rank_percentile_curve.csv", percentile_curve)
    write_csv(out_dir / "ranking_miss_samples.csv", _flatten_samples(diagnostics, "late_winner_samples", "late_winner"))
    write_csv(out_dir / "ranking_false_positive_samples.csv", _flatten_samples(diagnostics, "early_loser_samples", "early_loser"))
    write_csv(out_dir / "ranking_factor_correlations.csv", correlation_rows)
    _write_json(out_dir / "ranking_diagnostics.json", diagnostics)

    aggregate = _aggregate_metrics(daily_metrics, k_values)
    summary = {
        "ranking_report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "strategy_code": strategy_code,
        "risk_level": risk_level,
        "start_date": start_date,
        "end_date": end_date,
        "horizons": horizons,
        "top_k": [int(item) for item in top_k_values],
        "label_config": label_config,
        "execution_config": execution_config or {},
        "coverage": coverage,
        "candidate_row_count": len(rows),
        "metrics": aggregate,
        "diagnostics": diagnostics,
        "artifacts": artifact_paths,
    }
    _write_json(out_dir / "ranking_summary.json", summary)
    return summary


def write_csv(path: str | Path, rows: List[Dict[str, Any]]) -> None:
    """Write deterministic CSV with stable column order."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = _columns(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows or []:
            writer.writerow({key: _csv_value(row.get(key)) for key in columns})


def _daily_metrics(rows: List[Dict[str, Any]], horizons: List[int], k_values: List[int]) -> List[Dict[str, Any]]:
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(str(row.get("trade_date") or "unknown"), []).append(row)
    metrics = []
    for trade_date in sorted(by_date):
        date_rows = by_date[trade_date]
        for horizon in horizons:
            item = evaluate_daily_ranking(date_rows, horizon)
            _attach_dynamic_top_k_metrics(item, date_rows, horizon, k_values)
            item["trade_date"] = trade_date
            item["market_state_tag"] = _dominant_market_state(date_rows)
            metrics.append(item)
    return metrics


def _percentile_curve(rows: List[Dict[str, Any]], horizons: List[int]) -> List[Dict[str, Any]]:
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(str(row.get("trade_date") or "unknown"), []).append(row)
    curve = []
    for trade_date in sorted(by_date):
        for horizon in horizons:
            for item in rank_percentile_return_curve(by_date[trade_date], horizon):
                item["trade_date"] = trade_date
                curve.append(item)
    return curve


def _flatten_samples(diagnostics: Dict[str, Dict[str, Any]], key: str, sample_type: str) -> List[Dict[str, Any]]:
    rows = []
    for horizon, report in diagnostics.items():
        for sample in report.get(key) or []:
            rows.append({"horizon": int(horizon), "sample_type": sample_type, **sample})
    return rows


def _aggregate_metrics(rows: List[Dict[str, Any]], k_values: List[int]) -> Dict[str, Any]:
    if not rows:
        return {}
    metric_keys = ["recall_at_10", "ndcg_at_10", "mrr"]
    for k in k_values:
        metric_keys.append(f"precision_at_{k}")
        metric_keys.append(f"top_{k}_avg_return_pct")
    aggregate = {}
    for key in metric_keys:
        values = [float(row.get(key) or 0.0) for row in rows]
        aggregate[key] = round(mean(values), 6) if values else 0.0
    return aggregate


def _metric_k_values(top_k_values: List[int]) -> List[int]:
    required = {3, 5, 10}
    requested = {int(item) for item in top_k_values or []}
    return sorted(required | requested)


def _attach_dynamic_top_k_metrics(item: Dict[str, Any], rows: List[Dict[str, Any]], horizon: int, k_values: List[int]) -> None:
    return_key = f"return_{int(horizon)}d_pct"
    strong_key = f"strong_{int(horizon)}d"
    tradable = [
        row
        for row in sorted(rows or [], key=lambda row: (_rank_no(row), str(row.get("symbol") or "")))
        if str(row.get("tradability_status") or "tradable") == "tradable"
    ]
    for k in k_values:
        denominator = min(k, len(tradable))
        top_rows = [row for row in tradable if _rank_no(row) <= k]
        if denominator > 0:
            item[f"precision_at_{k}"] = round(sum(1 for row in top_rows if bool(row.get(strong_key))) / denominator, 6)
        else:
            item[f"precision_at_{k}"] = 0.0
        if top_rows:
            item[f"top_{k}_avg_return_pct"] = round(mean(float(row.get(return_key) or 0.0) for row in top_rows), 6)
        else:
            item[f"top_{k}_avg_return_pct"] = 0.0


def _dominant_market_state(rows: List[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for row in rows:
        state = str(row.get("market_state_tag") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    if not counts:
        return "unknown"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _rank_no(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("rank_no") or 999999)
    except (TypeError, ValueError):
        return 999999


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    keys = set()
    for row in rows or []:
        keys.update(row.keys())
    return sorted(keys)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[3]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"
