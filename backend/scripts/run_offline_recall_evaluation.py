#!/usr/bin/env python3
"""Generate offline recall experiment ranking reports without changing production strategy."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.offline_recall_candidates import generate_offline_recall_rows
from app.evaluation.ranking_fixtures import smoke_fixture_rows
from app.evaluation.ranking_labels import DEFAULT_STRONG_LABEL_CONFIG
from app.evaluation.ranking_latest import annotate_ranking_evidence_readiness
from app.evaluation.ranking_replay import RankingReplayService, attach_forward_labels
from app.evaluation.ranking_report import build_ranking_report
from app.evaluation.market_snapshot_history import MarketSnapshotHistoryProvider
from app.evaluation.recall_experiments import DEFAULT_EXPERIMENTS, build_recall_experiment_report, write_recall_experiment_report


DEFAULT_VARIANT_KEYS = [
    "recall_220_deep_150",
    "recall_300_deep_300",
    "recall_500_deep_500",
    "multi_channel_union",
]


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline SmartStock recall experiment evaluations.")
    parser.add_argument("--strategy-code", required=True)
    parser.add_argument("--risk-level", required=True, choices=("low", "medium", "high"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--horizons", default="3,5,10,20")
    parser.add_argument("--top-k", default="3,5,10")
    parser.add_argument("--commission", type=float, default=0.0003)
    parser.add_argument("--slippage", type=float, default=0.001)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--experiment-key", action="append", default=[])
    parser.add_argument("--include-baseline", action="store_true")
    parser.add_argument("--max-rows-per-day", type=int, default=None)
    parser.add_argument("--min-market-snapshot-count", type=int, default=1)
    parser.add_argument("--fixture", choices=("smoke",), default=None)
    args = parser.parse_args(argv)
    start = _parse_date(parser, "start-date", args.start_date)
    end = _parse_date(parser, "end-date", args.end_date)
    if start > end:
        parser.error("start-date must be on or before end-date")
    args.horizons = _parse_int_list(parser, "horizons", args.horizons)
    args.top_k = _parse_int_list(parser, "top-k", args.top_k)
    if args.commission < 0:
        parser.error("commission must be greater than or equal to 0")
    if args.slippage < 0:
        parser.error("slippage must be greater than or equal to 0")
    valid_keys = {item["key"] for item in DEFAULT_EXPERIMENTS}
    keys = args.experiment_key or list(DEFAULT_VARIANT_KEYS)
    unknown = [key for key in keys if key not in valid_keys or key == "baseline"]
    if unknown:
        parser.error(f"unknown or unsupported experiment-key: {', '.join(unknown)}")
    args.experiment_key = keys
    return args


def run(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    label_config = dict(DEFAULT_STRONG_LABEL_CONFIG)
    label_config["horizons"] = list(args.horizons)
    execution_config = {
        "commission": float(args.commission),
        "slippage": float(args.slippage),
        "fixture": args.fixture,
        "candidate_source": "offline_recall_market_snapshots" if args.fixture is None else "fixture_smoke",
    }

    if args.fixture == "smoke":
        if args.include_baseline:
            _write_smoke_report("baseline", args, output_root, label_config, execution_config)
        for key in args.experiment_key:
            _write_smoke_report(key, args, output_root, label_config, execution_config)
            print(f"generated {key}: fixture smoke")
    else:
        load_local_env()
        from app.main import coach_store, data_source_manager

        history_manager = build_history_manager(
            store=coach_store,
            data_source_manager=data_source_manager,
            start_date=args.start_date,
            end_date=args.end_date,
            label_config=label_config,
            min_market_snapshot_count=args.min_market_snapshot_count,
        )
        if args.include_baseline:
            _write_baseline_report(args, output_root, label_config, execution_config, coach_store, history_manager)
        for key in args.experiment_key:
            _write_offline_variant_report(args, key, output_root, label_config, execution_config, coach_store, history_manager)
            print(f"generated {key}: offline market snapshots")

    comparison = build_recall_experiment_report(output_root)
    write_recall_experiment_report(comparison, output_root / "recall_experiment_report.json")
    _write_markdown_report(comparison, output_root / "recall_experiment_report.md")
    print(f"comparison_status: {comparison.get('status')}")
    print(f"production_switch_ready: {comparison.get('production_switch_ready')}")
    print(f"output_root: {output_root}")
    return 0


def load_local_env(env_file: Optional[Path] = None) -> Optional[Path]:
    """Load shared local secrets without printing values.

    Worktrees do not necessarily contain `backend/.env`, so local research
    scripts need the same shared secret lookup used by start.sh.
    """
    path = Path(env_file).expanduser().resolve() if env_file else _default_local_env_file()
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if value and not os.environ.get(key):
            os.environ[key] = value
    return path


def _default_local_env_file() -> Path:
    explicit = os.environ.get("SMARTSTOCK_LOCAL_ENV_FILE")
    if explicit:
        return Path(explicit).expanduser().resolve()
    repo_root = BACKEND_ROOT.parent
    parts = list(repo_root.parts)
    if ".worktrees" in parts:
        workspace = Path(*parts[: parts.index(".worktrees")])
    else:
        workspace = repo_root.parent
    return workspace / ".local-secrets" / "smartstock.env"


class CachedHistoryRangeManager:
    """Cache explicit history ranges per symbol for offline labeling.

    The ranking labeler asks for one forward window per candidate row. Offline
    recall experiments can produce thousands of rows with repeated symbols, so
    this wrapper fetches one broad, explicit range per symbol and serves slices
    to the read-only labeler.
    """

    def __init__(self, source, start_date: str, end_date: str):
        self.source = source
        self.start_date = _normalize_date_text(start_date) or str(start_date)
        self.end_date = _normalize_date_text(end_date) or str(end_date)
        self._cache = {}
        self.fetch_count = 0

    def get_history_data_range(self, symbol, start_date: str, end_date: str):
        normalized_symbol = str(symbol or "")
        if normalized_symbol not in self._cache:
            if not hasattr(self.source, "get_history_data_range"):
                raise RuntimeError("explicit_history_range_unavailable")
            history = self.source.get_history_data_range(
                normalized_symbol,
                start_date=self.start_date,
                end_date=self.end_date,
            )
            self._cache[normalized_symbol] = self._normalize_history_dates(history)
            self.fetch_count += 1
        return self._slice_history(self._cache[normalized_symbol], start_date=start_date, end_date=end_date)

    @staticmethod
    def _normalize_history_dates(history):
        if history is None:
            return pd.DataFrame()
        rows = history.copy()
        if "date" in rows.columns:
            rows["date"] = rows["date"].map(_normalize_date_text)
            rows = rows.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return rows

    @staticmethod
    def _slice_history(history, start_date: str, end_date: str):
        if history is None or history.empty or "date" not in history.columns:
            return pd.DataFrame() if history is None else history.copy()
        start = _normalize_date_text(start_date) or str(start_date)
        end = _normalize_date_text(end_date) or str(end_date)
        rows = history[(history["date"] >= start) & (history["date"] <= end)]
        return rows.reset_index(drop=True)


def build_history_manager(
    store,
    data_source_manager,
    start_date: str,
    end_date: str,
    label_config: dict,
    min_market_snapshot_count: int = 1,
):
    remote_history = CachedHistoryRangeManager(
        data_source_manager,
        start_date=start_date,
        end_date=_label_cache_end_date(end_date, label_config),
    )
    return MarketSnapshotHistoryProvider(
        store=store,
        fallback=remote_history,
        min_count=max(1, int(min_market_snapshot_count or 1)),
    )


def _label_cache_end_date(end_date: str, label_config: dict) -> str:
    parsed_end = _parse_iso_date(end_date)
    horizons = [int(item) for item in label_config.get("horizons") or DEFAULT_STRONG_LABEL_CONFIG["horizons"]]
    max_horizon = max(horizons or [20])
    calendar_days = int(label_config.get("history_window_calendar_days") or max(14, max_horizon * 5 + 10))
    return (parsed_end + timedelta(days=calendar_days)).isoformat()


def _write_smoke_report(key: str, args: argparse.Namespace, output_root: Path, label_config: dict, execution_config: dict) -> None:
    rows, coverage = smoke_fixture_rows(args.horizons)
    rows = [{**row, "experiment_key": key, "source": f"offline_recall:{key}"} for row in rows]
    coverage = {**coverage, "fixture": "smoke"}
    summary = _build_and_annotate_report(key, rows, coverage, args, output_root, label_config, execution_config)
    summary["fixture"] = "smoke"
    summary["production_evidence"] = False
    summary["evidence_type"] = "smoke"
    summary["evidence_readiness"] = {
        **(summary.get("evidence_readiness") or {}),
        "status": "insufficient",
        "production_evidence": False,
        "blocking_reasons": sorted(set((summary.get("readiness_blockers") or []) + ["fixture_smoke"])),
    }
    _rewrite_summary(output_root / key / "ranking_summary.json", summary)


def _write_baseline_report(
    args: argparse.Namespace,
    output_root: Path,
    label_config: dict,
    execution_config: dict,
    store,
    data_source_manager,
) -> None:
    replay = RankingReplayService(store=store, data_source_manager=data_source_manager).replay(
        strategy_code=args.strategy_code,
        risk_level=args.risk_level,
        start_date=args.start_date,
        end_date=args.end_date,
        attach_labels=True,
        label_config=label_config,
    )
    _build_and_annotate_report("baseline", replay["rows"], replay["coverage"], args, output_root, label_config, execution_config)
    print("generated baseline: historical pick snapshots")


def _write_offline_variant_report(
    args: argparse.Namespace,
    key: str,
    output_root: Path,
    label_config: dict,
    execution_config: dict,
    store,
    data_source_manager,
) -> None:
    generated = generate_offline_recall_rows(
        store=store,
        experiment_key=key,
        strategy_code=args.strategy_code,
        risk_level=args.risk_level,
        start_date=args.start_date,
        end_date=args.end_date,
        max_rows_per_day=args.max_rows_per_day,
        min_market_snapshot_count=args.min_market_snapshot_count,
    )
    rows = attach_forward_labels(generated["rows"], data_source_manager, label_config=label_config)
    coverage = {
        **generated["coverage"],
        "experiment_key": key,
        "recall_experiment": generated["experiment"],
    }
    _build_and_annotate_report(key, rows, coverage, args, output_root, label_config, execution_config)


def _build_and_annotate_report(
    key: str,
    rows: List[dict],
    coverage: dict,
    args: argparse.Namespace,
    output_root: Path,
    label_config: dict,
    execution_config: dict,
) -> dict:
    summary = build_ranking_report(
        candidate_rows=rows,
        strategy_code=args.strategy_code,
        risk_level=args.risk_level,
        start_date=args.start_date,
        end_date=args.end_date,
        horizons=args.horizons,
        top_k_values=args.top_k,
        output_dir=str(output_root / key),
        label_config=label_config,
        coverage=coverage,
        execution_config=execution_config,
    )
    experiment = _experiment_by_key(key)
    summary.update(
        {
            "experiment_key": key,
            "recall_experiment": experiment,
            "recall_size": experiment.get("recall_size"),
            "deep_analysis_size": experiment.get("deep_analysis_size"),
            "recall_method": experiment.get("recall_method"),
            "generated_by": "run_offline_recall_evaluation.py",
        }
    )
    summary = annotate_ranking_evidence_readiness(summary)
    _rewrite_summary(output_root / key / "ranking_summary.json", summary)
    return summary


def _rewrite_summary(path: Path, summary: dict) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown_report(report: dict, output_path: Path) -> None:
    lines = [
        "# Offline Recall Experiment Comparison",
        "",
        f"- status: `{report.get('status')}`",
        f"- production_switch_ready: `{str(report.get('production_switch_ready')).lower()}`",
        f"- blocking_reasons: `{', '.join(report.get('blocking_reasons') or []) or '-'}`",
        "",
        "| experiment | available | evidence | compatibility | Precision@3 | Precision@5 | NDCG@10 | Top5 Avg Return |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("experiments") or []:
        metrics = row.get("metrics") or {}
        issues = row.get("compatibility_issues") or []
        compatibility = row.get("compatibility_status") or "-"
        if issues:
            compatibility = f"{compatibility}: {', '.join(str(item) for item in issues)}"
        lines.append(
            "| {key} | {available} | {evidence} | {compatibility} | {p3:.4f} | {p5:.4f} | {ndcg:.4f} | {ret:.4f} |".format(
                key=row.get("key"),
                available=str(bool(row.get("available"))).lower(),
                evidence=row.get("evidence_status"),
                compatibility=compatibility,
                p3=float(metrics.get("precision_at_3") or 0.0),
                p5=float(metrics.get("precision_at_5") or 0.0),
                ndcg=float(metrics.get("ndcg_at_10") or 0.0),
                ret=float(metrics.get("top_5_avg_return_pct") or 0.0),
            )
        )
    lines.extend(["", "This artifact is read-only research evidence and does not change production strategy logic.", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _experiment_by_key(key: str) -> dict:
    for item in DEFAULT_EXPERIMENTS:
        if item.get("key") == key:
            return dict(item)
    return {"key": key}


def _parse_date(parser: argparse.ArgumentParser, name: str, value: str):
    try:
        parsed = _parse_iso_date(value)
    except ValueError:
        parser.error(f"{name} must use YYYY-MM-DD")
    if parsed.isoformat() != value:
        parser.error(f"{name} must use YYYY-MM-DD")
    return parsed


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _normalize_date_text(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value).strip()
    if not text_value:
        return None
    for fmt, width in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(text_value[:width], fmt).date().isoformat()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(text_value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _parse_int_list(parser: argparse.ArgumentParser, name: str, value: str) -> List[int]:
    try:
        items = [int(item.strip()) for item in str(value).split(",") if item.strip()]
    except ValueError:
        parser.error(f"{name} must be a comma-separated integer list")
    if not items:
        parser.error(f"{name} must not be empty")
    if any(item <= 0 for item in items):
        parser.error(f"{name} values must be greater than 0")
    return items


if __name__ == "__main__":
    raise SystemExit(run())
