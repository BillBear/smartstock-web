#!/usr/bin/env python3
"""Generate a read-only quality diagnosis from persisted ranking snapshots."""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import psycopg2

# Direct script execution sets sys.path to backend/scripts, not backend.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.ranking_quality_diagnosis import (
    DEFAULT_EXECUTION_CONFIG,
    FACTOR_FIELDS,
    build_ranking_quality_diagnosis,
    label_snapshot_rows,
)
from app.services.akshare_service import AKShareService
from app.services.tushare_service import TuShareService


DEFAULT_DB_URL = "postgresql://smartstock@127.0.0.1:5432/smartstock"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("COACH_DB_URL", DEFAULT_DB_URL))
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--strategy-code", default="trend_breakout")
    parser.add_argument("--risk-level", default="medium")
    parser.add_argument("--output-dir", default="runtime/strategy-quality/ranking-quality-v1")
    parser.add_argument("--report-path", default="docs/strategy-evidence/ranking-quality/2026-08-30-current-ranking-diagnosis.md")
    return parser.parse_args()


def load_persisted_inputs(database_url: str, user_id: str, strategy_code: str, risk_level: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """Read authoritative candidate snapshots without initializing application state."""
    connection = psycopg2.connect(_psycopg_url(database_url))
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("BEGIN READ ONLY")
            cursor.execute(
                """
                SELECT
                    ps.pick_id,
                    ps.trade_date,
                    ps.symbol,
                    ps.name,
                    ps.snapshot_json,
                    ms.source,
                    ms.snapshot_count,
                    ms.quality_status,
                    ms.created_at
                FROM pick_snapshots ps
                LEFT JOIN LATERAL (
                    SELECT source, snapshot_count, quality_status, created_at
                    FROM market_snapshots
                    WHERE trade_date = ps.trade_date
                    ORDER BY created_at DESC
                    LIMIT 1
                ) ms ON TRUE
                WHERE ps.user_id = %s
                  AND ps.strategy_code = %s
                  AND ps.risk_level = %s
                ORDER BY ps.trade_date, ps.pick_id
                """,
                (user_id, strategy_code, risk_level),
            )
            snapshot_rows = cursor.fetchall()
            snapshot_columns = [item.name for item in cursor.description]

            cursor.execute(
                """
                SELECT config_json
                FROM strategy_profiles
                WHERE user_id = %s AND strategy_code = %s
                ORDER BY is_active DESC, updated_at DESC
                LIMIT 1
                """,
                (user_id, strategy_code),
            )
            config_result = cursor.fetchone()

            cursor.execute(
                """
                SELECT pick_id, action_type, created_at
                FROM pick_actions
                WHERE user_id = %s
                ORDER BY id DESC
                """,
                (user_id,),
            )
            actions = cursor.fetchall()
            connection.commit()
    finally:
        connection.close()

    latest_actions = {}
    for pick_id, action_type, created_at in actions:
        latest_actions.setdefault(str(pick_id or ""), {"action_type": action_type, "created_at": str(created_at)})
    snapshots = []
    for raw in snapshot_rows:
        row = dict(zip(snapshot_columns, raw))
        payload = _json_object(row.pop("snapshot_json"))
        payload.setdefault("pick_id", row.get("pick_id"))
        payload.setdefault("trade_date", str(row.get("trade_date") or ""))
        payload.setdefault("symbol", row.get("symbol"))
        payload.setdefault("name", row.get("name") or row.get("symbol"))
        payload["market_snapshot_source"] = row.get("source")
        payload["market_snapshot_count"] = row.get("snapshot_count")
        payload["market_snapshot_quality_status"] = row.get("quality_status")
        payload["market_snapshot_created_at"] = str(row.get("created_at") or "") or None
        payload["actual_action"] = latest_actions.get(str(payload.get("pick_id") or ""))
        snapshots.append(payload)

    strategy_config = _json_object(config_result[0]) if config_result else {}
    inventory = {
        "snapshot_row_count": len(snapshots),
        "snapshot_dates": sorted({str(item.get("trade_date") or "") for item in snapshots if item.get("trade_date")}),
        "market_snapshot_quality_counts": _count_values(snapshots, "market_snapshot_quality_status"),
        "market_snapshot_source_counts": _count_values(snapshots, "market_snapshot_source"),
    }
    return snapshots, strategy_config, inventory


class ExplicitHistoryFetcher:
    """Use the application's existing explicit-range history interfaces with provenance."""

    def __init__(self, token: str):
        self.tushare = TuShareService(token) if token else None
        self.akshare = AKShareService()

    def __call__(self, symbol: str, start_date: str, end_date: str):
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        failure_types: List[str] = []
        if self.tushare:
            try:
                frame = self.tushare.get_history_data(_to_tushare_code(symbol), start_date=start, end_date=end)
                if frame is not None and not frame.empty:
                    return frame, "TuShare"
                failure_types.append("TuShare:empty")
            except Exception as exc:  # source failure is recorded, never substituted with mock data
                failure_types.append(f"TuShare:{type(exc).__name__}")
        else:
            failure_types.append("TuShare:token_missing")
        try:
            frame = self.akshare.get_history_data_range(symbol, start_date=start_date, end_date=end_date)
            if frame is not None and not frame.empty:
                return frame, "AKShare"
            failure_types.append("AKShare:empty")
        except Exception as exc:
            failure_types.append(f"AKShare:{type(exc).__name__}")
        return pd.DataFrame(), "unavailable", ";".join(failure_types)


def write_artifacts(output_dir: Path, labeled_rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ranking_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(output_dir / "ranking_quality_labels.csv", labeled_rows)
    _write_csv(output_dir / "ranking_quality_error_samples.csv", _flatten_error_samples(summary.get("diagnosis", {}).get("error_samples") or {}))


def render_report(summary: Dict[str, Any]) -> str:
    diagnosis = summary["diagnosis"]
    coverage = summary["coverage"]
    ranking = diagnosis["ranking_quality"]
    metrics = ranking.get("macro_daily_metrics") or {}
    lines = [
        "# 当前选股排名质量诊断 V1",
        "",
        "本报告仅复盘 PostgreSQL 中已保存的候选快照和其后实际日 K 线标签，不改变候选、排序、模型、交易闸门或策略参数，也不构成投资建议。",
        "",
        "## 输入与口径",
        "",
        f"- 权威快照：PostgreSQL，`user_id={summary['identity']['user_id']}`、`strategy_code={summary['identity']['strategy_code']}`、`risk_level={summary['identity']['risk_level']}`。",
        f"- 快照：{summary['inventory']['snapshot_row_count']} 条，{len(summary['inventory']['snapshot_dates'])} 个有候选日期；日期范围 {summary['inventory']['snapshot_dates'][0] if summary['inventory']['snapshot_dates'] else 'n/a'} 至 {summary['inventory']['snapshot_dates'][-1] if summary['inventory']['snapshot_dates'] else 'n/a'}。",
        "- 入场：每只股票严格取选股日期之后第一根有效日 K 线开盘价；没有后续 bar 的记录排除，不使用交易日历或 weekday 推断。",
        f"- 成本：买入和卖出各计 commission={summary['execution_config']['commission']:.4f}、slippage={summary['execution_config']['slippage']:.4f}；收益为双边成本后的收盘净收益。",
        f"- 风控路径：沿用保存策略配置的止盈 {summary['execution_config']['take_profit_pct']:.2f}% 与止损 {summary['execution_config']['stop_loss_pct']:.2f}%；同日双触发保守地按止损优先。",
        f"- 历史行情来源：{_inline_counts(coverage.get('source_counts') or {})}；标签缺失率 {coverage.get('label_missing_rate', 0.0):.2%}，缺失原因：{_inline_counts(coverage.get('missing_reason_counts') or {})}。",
        "",
        "## 排名质量（10 日，按日等权）",
        "",
        "`Precision@K` 的相关性定义为净未来 10 日收益大于 0；NDCG 使用正收益作为增益，MRR 为首个正收益候选的倒数排名。",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
    ]
    for key in ("precision_at_3", "precision_at_5", "precision_at_10", "ndcg_at_10", "mrr", "top_3_avg_return", "top_3_median_return", "top_3_positive_return_rate", "top_3_severe_loss_rate", "top_5_avg_return", "top_10_avg_return"):
        lines.append(f"| {key} | {_format_value(metrics.get(key))} |")
    lines.extend(["", "| 排名组 | 样本 | 平均净收益 | 中位数 | 正收益率 | 严重亏损率 |", "|---|---:|---:|---:|---:|---:|"])
    for group in ranking.get("rank_groups") or []:
        lines.append(f"| {group['rank_group']} | {group['row_count']} | {_format_value(group['avg_return'])} | {_format_value(group['median_return'])} | {_format_value(group['positive_return_rate'])} | {_format_value(group['severe_loss_rate'])} |")
    lines.extend([
        "",
        f"- Spearman(rank_no, future_return_10d)：{_format_value(ranking.get('spearman_rank_vs_future_return'))}（排名数值越小越好，因此负值才是有利方向）。",
        f"- 分组单调性：{json.dumps(ranking.get('monotonic_rank_groups'), ensure_ascii=False)}。",
        "",
        "## 错误样本（最多 20 条/类）",
        "",
    ])
    for title, samples in (diagnosis.get("error_samples") or {}).items():
        lines.extend([f"### {title}", "", "| 日期 | 股票 | 排名 | 10 日净收益 | action | executable |", "|---|---|---:|---:|---|---|"])
        for item in samples:
            lines.append(f"| {item.get('trade_date')} | {item.get('symbol')} {item.get('name') or ''} | {item.get('rank_no')} | {_format_value(item.get('future_return_10d'))} | {item.get('action') or ''} | {item.get('decision_executable')} |")
        if not samples:
            lines.append("| 无可用样本 |  |  |  |  |  |")
        lines.append("")
    lines.extend(["## 因子与市场状态", "", "| 因子 | 缺失率 | 5D Spearman | 10D Spearman | 20D Spearman |", "|---|---:|---:|---:|---:|"])
    for factor, value in (diagnosis.get("factor_analysis") or {}).items():
        horizons = value.get("horizons") or {}
        lines.append(f"| {factor} | {_format_value(value.get('missing_rate'))} | {_format_value((horizons.get('5') or {}).get('spearman'))} | {_format_value((horizons.get('10') or {}).get('spearman'))} | {_format_value((horizons.get('20') or {}).get('spearman'))} |")
    lines.extend([
        "",
        "完整分位数组收益和按市场状态的方向检查见忽略的运行产物 `runtime/strategy-quality/ranking-quality-v1/ranking_quality_summary.json`。若候选快照未持久化市场状态，报告会明确标为无法判断，而不以市场日期推断替代。",
        "",
        "## 弱模型反事实",
        "",
        "| 排名口径 | 状态 | Precision@3 | Precision@5 | Precision@10 | NDCG@10 | MRR |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    counterfactual = diagnosis["counterfactual"]
    for label, item in (
        ("A. 当前最终排名", counterfactual["current_final_rank"]),
        ("B-proxy. raw_total", counterfactual["raw_total_proxy_rank"]),
        ("C. up_prob - dd_prob", counterfactual["up_minus_dd_rank"]),
    ):
        metric_values = (item.get("metrics") or {}).get("macro_daily_metrics") or {}
        lines.append(
            f"| {label} | {item.get('status')} | {_format_value(metric_values.get('precision_at_3'))} | "
            f"{_format_value(metric_values.get('precision_at_5'))} | {_format_value(metric_values.get('precision_at_10'))} | "
            f"{_format_value(metric_values.get('ndcg_at_10'))} | {_format_value(metric_values.get('mrr'))} |"
        )
    lines.extend([
        "",
        f"- 无模型规则分排名：{counterfactual['no_model_rule_rank']['status']}。原因：{counterfactual['no_model_rule_rank']['reason']}",
        f"- 缺失字段：{', '.join(counterfactual['no_model_rule_rank']['missing_fields'])}。",
        f"- `raw_total` 排名只作为 proxy：{counterfactual['raw_total_proxy_rank']['status']}，不得解读为弱模型已被排除。",
        f"- model_probability 覆盖率：{counterfactual['no_model_rule_rank']['model_probability_coverage']:.2%}；因此不能据此判断弱模型改善或拖累排序。",
        "",
        "## 漏斗判断",
        "",
    ])
    for name, finding in (diagnosis.get("funnel_assessment") or {}).items():
        lines.append(f"- **{name}：{finding['finding']}**。{finding['evidence']}")
    lines.extend([
        "",
        "## 下一轮单变量实验建议",
        "",
        "1. 仅新增 pre-model 规则分、ML delta 和最终分的 shadow 持久化，验证弱模型影响，不改变任何线上排序。",
        "2. 仅在离线影子评估中将排序键替换为 `raw_total`，其余候选、闸门和持有期固定，比较 10 日 NDCG@10。",
        "3. 仅在离线影子评估中改变 `decision.executable` 的买入闸门，排序与持有期固定，比较被拦截正收益候选与新增亏损。",
        "",
        "本诊断证明的是现有快照与后续标签的关联，不证明策略、模型或回测有效。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    snapshots, strategy_config, inventory = load_persisted_inputs(args.database_url, args.user_id, args.strategy_code, args.risk_level)
    if not snapshots:
        raise SystemExit("no persisted pick_snapshots matched the requested identity")
    execution_config = dict(DEFAULT_EXECUTION_CONFIG)
    execution_config.update({key: strategy_config[key] for key in execution_config if key in strategy_config})
    fetcher = ExplicitHistoryFetcher(os.environ.get("TUSHARE_TOKEN", ""))
    labeled_rows, coverage = label_snapshot_rows(snapshots, fetcher, execution_config=execution_config)
    diagnosis = build_ranking_quality_diagnosis(labeled_rows)
    summary = {
        "identity": {"user_id": args.user_id, "strategy_code": args.strategy_code, "risk_level": args.risk_level},
        "execution_config": execution_config,
        "strategy_config": strategy_config,
        "inventory": inventory,
        "coverage": coverage,
        "diagnosis": diagnosis,
    }
    output_dir = Path(args.output_dir).resolve()
    write_artifacts(output_dir, labeled_rows, summary)
    report_path = Path(args.report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "report_path": str(report_path), "coverage": coverage}, ensure_ascii=False, sort_keys=True))
    return 0


def _psycopg_url(value: str) -> str:
    return str(value or DEFAULT_DB_URL).replace("postgresql+psycopg2://", "postgresql://", 1)


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        decoded = {}
    return decoded if isinstance(decoded, dict) else {}


def _count_values(rows: Iterable[Dict[str, Any]], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "missing")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _to_tushare_code(symbol: str) -> str:
    symbol = str(symbol or "").strip()
    return f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ"


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    columns = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def _flatten_error_samples(samples: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [{"sample_type": name, **row} for name, items in samples.items() for row in items]


def _inline_counts(counts: Dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "无"


def _format_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
