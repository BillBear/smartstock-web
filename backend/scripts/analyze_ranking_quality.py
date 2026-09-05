#!/usr/bin/env python3
"""Generate a read-only quality diagnosis from persisted ranking snapshots."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time
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
    SnapshotIntegrityError,
    build_ranking_quality_diagnosis,
    label_snapshot_rows,
    validate_snapshot_identity,
    validate_labeled_snapshot_sample,
    quarantine_ambiguous_dates,
)
from app.evaluation.ranking_quality_experiments import run_ranking_experiments
from app.evaluation.paper_trade_review import summarize_paper_trades


DEFAULT_DB_URL = "postgresql://smartstock@127.0.0.1:5432/smartstock"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("COACH_DB_URL", DEFAULT_DB_URL))
    parser.add_argument("--user-id", default="default")
    parser.add_argument("--strategy-code", default="trend_breakout")
    parser.add_argument("--risk-level", default="medium")
    parser.add_argument("--output-dir", default="runtime/strategy-quality/ranking-quality-v1-2")
    parser.add_argument("--report-path", default="runtime/strategy-quality/ranking-quality-v1-2/report.md")
    parser.add_argument("--input-json", type=Path, help="Replay an immutable observation without connecting to PostgreSQL")
    parser.add_argument("--env-file", type=Path, help="Read TUSHARE_TOKEN only; never source shell code")
    parser.add_argument("--quarantine-ambiguous-dates", action="store_true", help="Explicit whole-date isolation; never deduplicate or repair ranks")
    parser.add_argument("--history-cache-only", action="store_true")
    parser.add_argument("--capture-only", action="store_true", help="Freeze existing snapshots/config, no provider or candidate calls")
    parser.add_argument("--latest-date-only", action="store_true", help="Capture only the newest persisted date; does not generate today's signals")
    parser.add_argument("--bootstrap-iterations", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260830)
    args = parser.parse_args()
    if args.input_json and args.latest_date_only:
        parser.error("--latest-date-only cannot be combined with frozen --input-json")
    return args


def load_persisted_inputs(database_url: str, user_id: str, strategy_code: str, risk_level: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """Read authoritative candidate snapshots without initializing application state."""
    connection = psycopg2.connect(_psycopg_url(database_url))
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("BEGIN READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
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
            connection.rollback()
    finally:
        connection.close()

    latest_actions = {}
    for pick_id, action_type, created_at in actions:
        latest_actions.setdefault(str(pick_id or ""), {"action_type": action_type, "created_at": str(created_at)})
    snapshots = []
    for raw in snapshot_rows:
        row = dict(zip(snapshot_columns, raw))
        payload = _json_object(row.pop("snapshot_json"))
        for key, expected in (("trade_date", str(row.get("trade_date") or "")), ("symbol", row.get("symbol")), ("strategy_code", strategy_code), ("risk_level", risk_level), ("user_id", user_id)):
            if payload.get(key) is not None and str(payload[key]) != str(expected):
                raise ValueError(f"snapshot_relational_payload_mismatch:{key}")
            payload[key] = expected
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


def load_paper_trades(database_url: str, user_id: str) -> List[Dict[str, Any]]:
    connection = psycopg2.connect(_psycopg_url(database_url))
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("BEGIN READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            cursor.execute("SELECT id, symbol, side, price, qty, fee, pick_id, created_at FROM paper_trades WHERE user_id = %s ORDER BY created_at, id", (user_id,))
            columns = [item.name for item in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            connection.rollback()
            return rows
    finally:
        connection.close()


class ExplicitHistoryFetcher:
    """Research-only raw daily bars plus adjustment factors; no mixed-price fallback."""

    def __init__(self, token: str, cache_dir: Optional[Path] = None, cache_only: bool = False, pro=None):
        self.pro = pro
        if token and not cache_only and pro is None:
            import tushare
            self.pro = tushare.pro_api(token)
        self.cache_dir = cache_dir
        self.cache_only = cache_only

    def __call__(self, symbol: str, start_date: str, end_date: str):
        params = {"ts_code": _to_tushare_code(symbol), "start_date": start_date.replace("-", ""), "end_date": end_date.replace("-", "")}
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path and path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved["request"] != params or saved["rows_sha256"] != _content_hash(saved["rows"]):
                raise ValueError("history_cache_integrity_failure")
            return pd.DataFrame(saved["rows"]), "TuShare", None
        if self.cache_only or self.pro is None:
            return pd.DataFrame(), "unavailable", "history_cache_miss" if self.cache_only else "token_missing"
        try:
            frame = self.pro.daily(**params)
            if frame is None or frame.empty:
                return pd.DataFrame(), "TuShare", "daily_empty"
            factors = self.pro.adj_factor(**params, fields="trade_date,adj_factor")
            if factors is None or factors.empty:
                return pd.DataFrame(), "TuShare", "adjustment_factor_missing"
            if frame["trade_date"].duplicated().any() or factors["trade_date"].duplicated().any():
                return pd.DataFrame(), "TuShare", "duplicate_history_dates"
            frame = frame.merge(factors[["trade_date", "adj_factor"]], on="trade_date", how="left", validate="one_to_one")
            if frame["adj_factor"].isna().any() or (frame["adj_factor"] <= 0).any():
                return pd.DataFrame(), "TuShare", "adjustment_factor_missing"
            frame = frame.rename(columns={"trade_date": "date", "vol": "volume"}).sort_values("date")
            frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
            frame["volume"] = frame["volume"] * 100
            frame["amount"] = frame["amount"] * 1000
            rows = json.loads(frame.to_json(orient="records"))
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                saved = {"request": params, "source": "TuShare.daily+adj_factor", "retrieved_at": datetime.now(timezone.utc).isoformat(), "rows": rows, "rows_sha256": _content_hash(rows)}
                with path.open("x", encoding="utf-8") as handle:
                    json.dump(saved, handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
            return pd.DataFrame(rows), "TuShare", None
        except Exception as exc:
            return pd.DataFrame(), "unavailable", f"TuShare:{type(exc).__name__}"
        finally:
            time.sleep(0.35)


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def freeze_observation(directory: Path, payload: Dict[str, Any]) -> Dict[str, str]:
    """Append content-addressed observations; never change an older observation."""
    digest = _content_hash(payload)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.json"
    if path.exists():
        if _content_hash(json.loads(path.read_text(encoding="utf-8"))) != digest:
            raise ValueError("observation_hash_mismatch")
    else:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    return {"path": str(path), "sha256": digest, "hash_basis": "canonical_json"}


def write_artifacts(output_dir: Path, raw_labeled_rows: List[Dict[str, Any]], labeled_rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ranking_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(output_dir / "ranking_quality_labels.csv", labeled_rows)
    _write_csv(output_dir / "ranking_quality_raw_labels.csv", raw_labeled_rows)
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


def render_experiment_report(summary: Dict[str, Any]) -> str:
    """Render the corrected experiment report from frozen observations."""
    sample = summary["sample_validation"]
    label_coverage = summary["label_coverage"]
    experiments = summary["experiments"]
    lines = [
        "# SmartStock 波段排序比较 V1.2",
        "",
        "本报告仅对 PostgreSQL 已保存候选快照进行离线标签和排序比较。不修改生产候选、排序、ML 融合、action、executable、仓位、止盈止损或策略参数，也不构成投资建议。",
        "",
        "## 样本口径与完整性",
        "",
        f"- 身份：`user_id={summary['identity']['user_id']}`、`strategy_code={summary['identity']['strategy_code']}`、`risk_level={summary['identity']['risk_level']}`。",
        f"- PostgreSQL 原始日期数：{len(summary['inventory']['snapshot_dates'])}；原始候选：{summary['inventory']['snapshot_row_count']}；重复日期隔离后：{sample['raw_candidate_count']}；有效交易快照日期：{sample['valid_trading_snapshot_date_count']}；最终候选：{sample['final_candidate_count']}；唯一股票：{sample['unique_symbol_count']}。",
        f"- 标签来源：{_inline_counts(label_coverage.get('source_counts') or {})}；标签缺失率：{label_coverage.get('label_missing_rate', 0.0):.2%}。",
        "- 日期有效性：仅检查每只候选实际日 K 线是否存在等于 `trade_date` 的记录；未调用 trade_cal、未使用 weekday 推断。若同日所有候选都不存在日 K，则标记为 `non_trading_snapshot` 并排除。",
        f"- 重复键政策：{summary.get('quarantine', {}).get('policy', 'strict_stop')}；整日隔离仅在显式启用时生效，保留原始快照，不删除数据库记录、不修复排名。",
        f"- 冻结输入 canonical JSON SHA-256：`{summary.get('observation', {}).get('sha256')}`。",
        f"- 价格口径：{summary.get('adjustment_method')}。入场价仍为未复权实际开盘价；复权因子只参与未来收益标签。",
        "",
        "| 检查 | 结果 |",
        "|---|---|",
        f"| (trade_date, symbol) | {sample['duplicate_key_checks']['trade_date_symbol']['status']} |",
        f"| (trade_date, rank_no) | {sample['duplicate_key_checks']['trade_date_rank_no']['status']} |",
        f"| rank 1-5 count <= valid dates * 5 | {sample['rank_band_assertions']['rank_1_5_count']} <= {sample['rank_band_assertions']['rank_1_5_limit']} ({sample['rank_band_assertions']['status']}) |",
        f"| rank 1-10 count <= valid dates * 10 | {sample['rank_band_assertions']['rank_1_10_count']} <= {sample['rank_band_assertions']['rank_1_10_limit']} ({sample['rank_band_assertions']['status']}) |",
        "",
        "| 日期 | 候选数 | 候选集合 SHA-256 |",
        "|---|---:|---|",
    ]
    for item in sample.get("daily_candidate_set_hashes") or []:
        lines.append(f"| {item['trade_date']} | {item['candidate_count']} | `{item['candidate_set_hash']}` |")
    lines.extend(["", "| 排除日期 | 原因 | 与前一日期候选集合相同 |", "|---|---|---|"])
    for item in (summary.get("quarantine", {}).get("excluded_dates", []) + sample.get("excluded_dates", [])):
        lines.append(f"| {item['trade_date']} | {item['reason']} ({item['candidate_count']}条) | {item.get('same_candidate_set_as_previous_date', 'n/a')} |")
    if not sample.get("excluded_dates") and not summary.get("quarantine", {}).get("excluded_dates"):
        lines.append("| 无 | 无 | n/a |")

    lines.extend([
        "",
        "## 实验定义",
        "",
        "- Baseline：按已保存 `rank_no` 升序。",
        "- A：仅按 `dd_prob` 升序。",
        "- B：仅按 `risk_adjusted` 降序。",
        f"- C：保留当前 `rank_no` 顺序，只否决 `dd_prob > {_format_value((experiments['methodology']['experiment_c']).get('dd_prob_veto_threshold'))}`，不回填。阈值来源：{(experiments['methodology']['experiment_c']).get('threshold_source') or 'unavailable'}。",
        f"- 次日有效日K开盘代理入场；双边 commission={summary['execution_config']['commission']}、slippage={summary['execution_config']['slippage']}。尚未模拟最低佣金、税费、排队成交；不是实盘可执行收益。止盈/止损路径只作20日价格触及诊断，不代表T+1条件下能在入场当日卖出。",
        "- 5/10/20日分别比较；日期等权。表中收益为百分数，概率/比例为0—1；中位数为每日TopK中位数的均值，不是把个股行合并后的中位数。K槽位采用min(K,当日候选数)，候选不足K时不另行补充。",
        "- 不按标签是否存在改变顺序。C保留被否决的现金槽位，收益为0但不是股票盈利；未知标签不是现金。池相对指标要求原始同日候选池完整。",
        f"- `decision.executable`：{summary['decision_executable_interpretation']['scope']}。{summary['decision_executable_interpretation']['detail']}",
        "",
        "## 候选池基线与排序增益",
        "",
        "下表的候选池是同一分组内全部有效候选；`超额收益` = TopK 平均收益 - 候选池平均收益，`Lift@K` = TopK 正收益率 / 候选池正收益率。",
    ])
    _append_experiment_sections(lines, experiments)
    lines.extend([
        "",
        "## 日期级配对比较（10 日）",
        "",
        f"`平均差` = 实验每日Top5平均收益 - 当前排名每日Top5平均收益。Bootstrap采用10个已观察日期的移动块，少于3块不输出推断区间；这只是最低推断前提，不是有效性证明。当前有效日期{sample['valid_trading_snapshot_date_count']}个，各方案实际配对数见表，不能以个股行数代替独立样本数。",
        "",
        "| 标签来源 | 分组 | 实验 | 匹配日期 | 平均差 | 胜/负/平 | 95% CI | 改善日期 | 改善涉及唯一股票 |",
        "|---|---|---|---:|---:|---|---|---:|---:|",
    ])
    for source_name, source in (experiments.get("segments") or {}).items():
        for group_name, group in source.items():
            for name, experiment in (group.get("experiments") or {}).items():
                if name == "baseline_current_rank" or experiment.get("status") != "available":
                    continue
                paired = experiment.get("paired_comparison") or {}
                interval = paired.get("bootstrap_95pct_ci") or {}
                lines.append(
                    f"| {source_name} | {group_name} | {name} | {paired.get('matched_date_count', 0)} | "
                    f"{_format_value(paired.get('mean_daily_top5_return_difference'))} | "
                    f"{paired.get('win_date_count', 0)}/{paired.get('loss_date_count', 0)}/{paired.get('tie_date_count', 0)} | "
                    f"[{_format_value(interval.get('lower'))}, {_format_value(interval.get('upper'))}] | "
                    f"{len(paired.get('improvement_dates') or [])} | {paired.get('improvement_unique_symbol_count', 0)} |"
                )

    selection = experiments.get("shadow_selection") or {}
    lines.extend(["", "## Shadow 候选裁决", ""])
    lines.append(f"- 结论：`{selection.get('status')}`；selected={selection.get('selected')}。四项指标及TuShare方向均使用配对完整池日期，稳健性要求移除任一日期/股票贡献后改善仍为正；样本不足时不晋级。最多选择一个，固定A/B/C顺序，不事后按收益选优。")
    lines.extend(["", "| 方案 | 状态 | 条件 |", "|---|---|---|"])
    for name, candidate in (selection.get("candidates") or {}).items():
        criteria = candidate.get("criteria") or {}
        if criteria:
            detail = "; ".join(f"{key}={value}" for key, value in criteria.items())
        else:
            detail = candidate.get("reason") or "n/a"
        lines.append(f"| {name} | {candidate.get('status')} | {detail} |")
    lines.extend([
        "",
        "## 解释边界",
        "",
        "- 本次仅TuShare日线与复权因子，无AKShare fallback；all_sources与tushare_only一致不是第二份独立证据。",
        "- 本轮无法判断召回问题：持久化表只保留最终候选，未保留完整被拒绝股票池。",
        "- 固定 5/10/20 日标签不复现真实退出路径，不能据此判断实际持有或止盈止损规则。",
        "- 结果仅用于选择是否值得进行不改变线上行为的 Shadow 前向采集，不证明策略、回测或模型有效。",
    ])
    paper = summary.get("manual_paper_review") or {}
    lines.extend(["", "## 手工模拟交易复盘", "",
                  f"保存买入{paper.get('buy_count')}笔，卖出{paper.get('sell_count')}笔；匹配卖出事件{paper.get('matched_sale_event_count')}，完成持仓周期{paper.get('completed_position_episode_count')}。",
                  f"仅匹配已卖部分毛损益：{paper.get('recorded_gross_realized_pnl')}；同配置成本覆盖估计：{paper.get('estimated_cost_overlay_pnl')}；记录手续费全零：{paper.get('recorded_fees_all_zero')}。",
                  "这不是账户总收益，也不是系统策略回报：未平仓部分没有重新盯市，手工选股有选择偏差，历史成交价未经盘口核验。",
                  "", "| 卖出时间 | 股票 | 数量 | 加权成本 | 卖价 | 毛损益 | 估计扣费损益 |", "|---|---|---:|---:|---:|---:|---:|"])
    for sale in paper.get("sale_events", []):
        lines.append(f"| {sale['created_at']} | {sale['symbol']} | {sale['qty']} | {_format_value(sale['cost_price'])} | {_format_value(sale['sale_price'])} | {_format_value(sale['gross_pnl'])} | {_format_value(sale['estimated_cost_overlay_pnl'])} |")
    return "\n".join(lines) + "\n"


def render_integrity_failure_report(user_id: str, strategy_code: str, risk_level: str, diagnostics: Dict[str, Any]) -> str:
    """Record a reproducible hard stop without fabricating experiment metrics."""
    lines = [
        "# SmartStock 排名实验 V1.1：数据完整性阻塞",
        "",
        "本次离线排名实验未执行。PostgreSQL 权威候选快照在预检阶段违反主键唯一性，工具在调用历史行情、生成标签、排序或选择 Shadow 候选之前停止。没有去重、回填或参数调整。",
        "",
        "## 输入身份",
        "",
        f"- `user_id={user_id}`、`strategy_code={strategy_code}`、`risk_level={risk_level}`。",
        f"- 原始候选：{diagnostics.get('raw_candidate_count', 0)}；原始日期：{diagnostics.get('raw_date_count', 0)}。",
        "",
        "## 重复检查",
        "",
        "| 键 | 状态 | 重复项 |",
        "|---|---|---:|",
    ]
    for name, check in (diagnostics.get("duplicate_key_checks") or {}).items():
        lines.append(f"| {name} | {check.get('status')} | {len(check.get('duplicate_keys') or [])} |")
    lines.extend(["", "### 详细重复键", "", "| 键 | trade_date | symbol/rank_no | 行数 |", "|---|---|---|---:|"])
    for name, check in (diagnostics.get("duplicate_key_checks") or {}).items():
        for item in check.get("duplicate_keys") or []:
            identity = item.get("symbol") if "symbol" in item else item.get("rank_no")
            lines.append(f"| {name} | {item.get('trade_date')} | {identity} | {item.get('row_count')} |")
    lines.extend([
        "",
        "## 结论",
        "",
        "- `ranking_experiments_status = blocked_duplicate_snapshot_keys`。",
        "- 非交易日检查、候选集合 hash、标签来源敏感性、基线增益、A/B/C 实验、日期级 bootstrap、action 分组和 Shadow 裁决均为 unavailable；继续计算会把重复候选当作独立样本。",
        "- 应先以独立的数据修复任务解释并纠正 PostgreSQL 中同日重复 rank_no 的保存来源；该任务不能通过本地去重掩盖问题。",
        "- 本报告不证明策略、模型或回测有效。",
    ])
    return "\n".join(lines) + "\n"


def _append_experiment_sections(lines: List[str], experiments: Dict[str, Any]) -> None:
    for source_name, source in (experiments.get("segments") or {}).items():
        for group_name, group in source.items():
            lines.extend(["", f"### {source_name} / {group_name}", ""])
            if group.get("status") != "available":
                lines.append("该分组无可评估候选。")
                continue
            pool = group.get("candidate_pool") or {}
            lines.extend(["| 持有期 | 候选池平均收益 | 中位数 | 正收益率 | 严重亏损率 |", "|---|---:|---:|---:|---:|"])
            for horizon in (5, 10, 20):
                item = pool.get(str(horizon)) or {}
                lines.append(f"| {horizon}D | {_format_value(item.get('avg_return'))} | {_format_value(item.get('median_return'))} | {_format_value(item.get('positive_return_rate'))} | {_format_value(item.get('severe_loss_rate'))} |")
            lines.extend([
                "",
                "| 持有期 | 方案 | coverage | P@3 | P@5 | P@10 | NDCG@10 | MRR | Top3 avg/median/positive/severe/excess/lift | Top5 avg/median/positive/severe/excess/lift | Top10 avg/median/positive/severe/excess/lift | Spearman |",
                "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|",
            ])
            for horizon in (5, 10, 20):
                for name, experiment in (group.get("experiments") or {}).items():
                    if experiment.get("status") != "available":
                        lines.append(f"| {horizon}D | {name} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
                        continue
                    metric = (experiment.get("metrics") or {}).get(str(horizon)) or {}
                    top = metric.get("top_k") or {}
                    lines.append(
                        f"| {horizon}D | {name} | {_format_value((experiment.get('coverage') or {}).get('coverage'))} | "
                        f"{_format_value((metric.get('precision_at') or {}).get('3'))} | {_format_value((metric.get('precision_at') or {}).get('5'))} | {_format_value((metric.get('precision_at') or {}).get('10'))} | "
                        f"{_format_value(metric.get('ndcg_at_10'))} | {_format_value(metric.get('mrr'))} | {_format_top(top.get('3'))} | {_format_top(top.get('5'))} | {_format_top(top.get('10'))} | {_format_value(metric.get('spearman_rank_vs_future_return'))} |"
                    )
            lines.extend(["", "| 持有期 | 方案 | 排名组 | 股票数 | 均值 | 中位数 | 严重亏损率 |", "|---|---|---|---:|---:|---:|---:|"])
            for name, experiment in group.get("experiments", {}).items():
                for horizon, metric in experiment.get("metrics", {}).items():
                    for band in metric.get("rank_groups", []):
                        lines.append(f"| {horizon}D | {name} | {band['rank_group']} | {band['candidate_count']} | {_format_value(band['avg_return'])} | {_format_value(band['median_return'])} | {_format_value(band['severe_loss_rate'])} |")


def _format_top(value: Optional[Dict[str, Any]]) -> str:
    value = value or {}
    return "/".join(
        _format_value(value.get(key))
        for key in ("avg_return", "median_return", "positive_return_rate", "severe_loss_rate", "relative_candidate_pool_excess_return", "lift_at_k")
    )


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    report_path = Path(args.report_path).resolve()
    identity = {"user_id": args.user_id, "strategy_code": args.strategy_code, "risk_level": args.risk_level}
    if args.input_json:
        observation = json.loads(args.input_json.read_text(encoding="utf-8"))
        if args.input_json.stem != _content_hash(observation):
            raise SystemExit("observation_hash_mismatch")
        if observation["identity"] != identity:
            raise SystemExit("observation_identity_mismatch")
        snapshots, strategy_config, inventory = observation["snapshots"], observation["strategy_config"], observation["inventory"]
    else:
        snapshots, strategy_config, inventory = load_persisted_inputs(args.database_url, args.user_id, args.strategy_code, args.risk_level)
        if args.latest_date_only and snapshots:
            latest = max(item["trade_date"] for item in snapshots)
            snapshots = [item for item in snapshots if item["trade_date"] == latest]
            inventory = {"snapshot_row_count": len(snapshots), "snapshot_dates": [latest],
                         "market_snapshot_quality_counts": _count_values(snapshots, "market_snapshot_quality_status"),
                         "market_snapshot_source_counts": _count_values(snapshots, "market_snapshot_source")}
        observation = {"identity": identity, "snapshots": snapshots, "strategy_config": strategy_config, "inventory": inventory,
                       "captured_at": datetime.now(timezone.utc).isoformat(), "source": "PostgreSQL_READ_ONLY",
                       "usage": "persisted_signals_only_not_new_candidates",
                       "config_sha256": _content_hash(strategy_config),
                       "config_provenance": "current_saved_profile_not_proven_historical_asof"}
        observation["manual_paper_trades"] = load_paper_trades(args.database_url, args.user_id)
    if not snapshots:
        raise SystemExit("no persisted pick_snapshots matched the requested identity")
    observation_ref = freeze_observation(output_dir / "observations", observation)
    if args.capture_only:
        print(json.dumps({"observation": observation_ref, "inventory": inventory, "new_candidates_generated": False}, ensure_ascii=False))
        return 0
    quarantine = {"policy": "strict_stop", "excluded_dates": []}
    if args.quarantine_ambiguous_dates:
        snapshots, rejected, quarantine = quarantine_ambiguous_dates(snapshots)
        freeze_observation(output_dir / "quarantine", {"evidence": quarantine, "snapshots": rejected})
    try:
        validate_snapshot_identity(snapshots)
    except SnapshotIntegrityError as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "snapshot_integrity_failure.json").write_text(
            json.dumps(exc.diagnostics, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_integrity_failure_report(args.user_id, args.strategy_code, args.risk_level, exc.diagnostics), encoding="utf-8"
        )
        raise SystemExit(str(exc))
    execution_config = dict(DEFAULT_EXECUTION_CONFIG)
    execution_config.update({key: strategy_config[key] for key in execution_config if key in strategy_config})
    for saved, target in (("stop_profit_pct", "take_profit_pct"), ("stop_loss_pct", "stop_loss_pct")):
        if saved in strategy_config:
            execution_config[target] = strategy_config[saved]
    token = os.environ.get("TUSHARE_TOKEN", "")
    if args.env_file and not args.history_cache_only:
        from dotenv import dotenv_values
        token = str(dotenv_values(args.env_file).get("TUSHARE_TOKEN") or token)
    fetcher = ExplicitHistoryFetcher(token, cache_dir=output_dir / "history", cache_only=args.history_cache_only)
    raw_labeled_rows, label_coverage = label_snapshot_rows(snapshots, fetcher, execution_config=execution_config)
    try:
        labeled_rows, sample_validation = validate_labeled_snapshot_sample(raw_labeled_rows)
    except SnapshotIntegrityError as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "snapshot_integrity_failure.json").write_text(
            json.dumps(exc.diagnostics, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        raise SystemExit(str(exc))

    threshold, threshold_source = resolve_existing_dd_prob_veto_threshold(strategy_config, args.strategy_code, args.risk_level)
    diagnosis = build_ranking_quality_diagnosis(labeled_rows)
    experiments = run_ranking_experiments(
        labeled_rows,
        dd_prob_veto_threshold=threshold,
        threshold_source=threshold_source,
        bootstrap_iterations=max(1, int(args.bootstrap_iterations)),
        bootstrap_seed=int(args.bootstrap_seed),
    )
    summary = {
        "identity": {"user_id": args.user_id, "strategy_code": args.strategy_code, "risk_level": args.risk_level},
        "execution_config": execution_config,
        "strategy_config": strategy_config,
        "inventory": inventory,
        "label_coverage": label_coverage,
        "sample_validation": sample_validation,
        "diagnosis": diagnosis,
        "experiments": experiments,
        "observation": observation_ref,
        "quarantine": quarantine,
        "execution_limitations": ["next_bar_open_is_a_proxy_not_verified_fill", "no_automatic_orders", "current_saved_costs_not_verified_historical_costs", "commission_and_slippage_only_no_minimum_fee_or_tax_model", "forward_labels_are_not_a_portfolio_backtest"],
        "adjustment_method": "TuShare raw daily plus adj_factor anchored to entry; no AKShare fallback",
        "manual_paper_review": summarize_paper_trades(observation.get("manual_paper_trades", []), commission=execution_config["commission"], slippage=execution_config["slippage"]),
        "decision_executable_interpretation": {
            "scope": "candidate_level",
            "source": "CoachService._build_pick_decision",
            "detail": "executable is determined by each pick's action, total, up_prob, dd_prob, expected_edge_pct, and profit_factor_proxy. strategy health live_ready only affects real_money_allowed and mode.",
        },
    }
    write_artifacts(output_dir, raw_labeled_rows, labeled_rows, summary)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_experiment_report(summary), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "report_path": str(report_path), "sample_validation": sample_validation, "label_coverage": label_coverage}, ensure_ascii=False, sort_keys=True))
    return 0 if labeled_rows else 2


def _psycopg_url(value: str) -> str:
    return str(value or DEFAULT_DB_URL).replace("postgresql+psycopg2://", "postgresql://", 1)


def resolve_existing_dd_prob_veto_threshold(strategy_config: Dict[str, Any], strategy_code: str, risk_level: str) -> Tuple[Optional[float], Optional[str]]:
    """Return only a saved threshold or an explicit current production rule."""
    configured = _as_float((strategy_config or {}).get("dd_prob_veto_threshold"))
    if configured is not None:
        return configured, "strategy_profiles.config_json.dd_prob_veto_threshold"
    if str(strategy_code or "").strip().lower() == "trend_breakout" and str(risk_level or "").strip().lower() == "medium":
        return 0.30, "CoachService medium/trend_breakout buy_cond: dd_prob <= 0.30"
    return None, None


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        decoded = {}
    return decoded if isinstance(decoded, dict) else {}


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
