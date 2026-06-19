#!/usr/bin/env python3
"""Reproducible command-line harness for coach backtest baselines.

The default path wraps CoachService.run_backtest without changing strategy
logic. The smoke fixture path is deterministic and non-investable; it exists so
CI can validate artifact shape without external market data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

BASELINE_SCHEMA_VERSION = "1.0"
KEY_METRIC_FIELDS = (
    "annual_return",
    "max_drawdown",
    "sharpe",
    "win_rate",
    "profit_loss_ratio",
)


def _parse_cli_date(parser: argparse.ArgumentParser, argument_name: str, value: str):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        parser.error(f"{argument_name} must use YYYY-MM-DD")
    if parsed.isoformat() != value:
        parser.error(f"{argument_name} must use YYYY-MM-DD")
    return parsed


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> argparse.Namespace:
    test_start = _parse_cli_date(parser, "test-start", args.test_start)
    test_end = _parse_cli_date(parser, "test-end", args.test_end)
    if test_start > test_end:
        parser.error("test-start must be on or before test-end")
    if args.universe_size <= 0:
        parser.error("universe-size must be greater than 0")
    if args.commission < 0:
        parser.error("commission must be greater than or equal to 0")
    if args.slippage < 0:
        parser.error("slippage must be greater than or equal to 0")
    return args


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a reproducible SmartStock coach backtest baseline and write a JSON artifact.",
    )
    parser.add_argument("--strategy-code", required=True, help="Strategy code passed through to CoachService.")
    parser.add_argument("--test-start", required=True, help="Backtest start date, YYYY-MM-DD.")
    parser.add_argument("--test-end", required=True, help="Backtest end date, YYYY-MM-DD.")
    parser.add_argument("--risk-level", required=True, choices=("low", "medium", "high"))
    parser.add_argument("--universe-size", required=True, type=int)
    parser.add_argument("--commission", required=True, type=float)
    parser.add_argument("--slippage", required=True, type=float)
    parser.add_argument("--output", required=True, help="Path to write the reproducibility artifact.")
    parser.add_argument(
        "--fixture",
        choices=("smoke",),
        default=None,
        help="Use deterministic smoke fixture instead of live market data. Smoke output is not strategy evidence.",
    )
    return validate_args(parser, parser.parse_args(argv))


def build_backtest_payload(args: argparse.Namespace) -> Dict[str, Any]:
    """Build the exact payload passed to CoachService without changing defaults."""
    return {
        "strategy_code": args.strategy_code,
        "test_start": args.test_start,
        "test_end": args.test_end,
        "config": {
            "risk_level": args.risk_level,
            "universe_size": int(args.universe_size),
            "commission": float(args.commission),
            "slippage": float(args.slippage),
        },
    }


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _fixture_run_id(payload: Dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:12]
    return f"fixture_smoke_{digest}"


def run_fixture_smoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return deterministic synthetic output for artifact-contract tests only."""
    config = dict(payload.get("config") or {})
    effective_config = {
        **config,
        "test_start": payload.get("test_start"),
        "test_end": payload.get("test_end"),
        "fixture": "smoke",
    }
    universe_size = int(effective_config.get("universe_size") or 0)
    commission = float(effective_config.get("commission") or 0.0)
    slippage = float(effective_config.get("slippage") or 0.0)
    equity_curve = [
        {"date": str(payload.get("test_start")), "value": 1.0},
        {"date": "2025-04-30", "value": 1.03125},
        {"date": "2025-08-29", "value": 0.9875},
        {"date": str(payload.get("test_end")), "value": 1.0642},
    ]
    drawdown_curve = [
        {"date": str(payload.get("test_start")), "value": 0.0},
        {"date": "2025-04-30", "value": 0.0},
        {"date": "2025-08-29", "value": -0.042425},
        {"date": str(payload.get("test_end")), "value": 0.0},
    ]
    diagnostics = {
        "source": "fixture_smoke",
        "data_source": "deterministic synthetic fixture",
        "trade_count": 8,
        "closed_roundtrips": 4,
        "avg_holding_days": 13.5,
        "avg_return_pct": 1.605,
        "total_realized_pnl": 6420.0,
        "total_realized_return_pct": 6.42,
        "calendar_days": 244,
        "universe_size": universe_size,
        "valid_history_symbols": universe_size,
        "max_drawdown": 0.042425,
        "annual_return": 0.0642,
        "sharpe": 1.1185,
        "fixture_notice": "Deterministic smoke fixture; not real market evidence and not investable.",
    }
    metrics = {
        "annual_return": 0.0642,
        "max_drawdown": 0.042425,
        "sharpe": 1.1185,
        "win_rate": 0.5,
        "profit_loss_ratio": 1.31,
    }
    credibility = {
        "live_ready": False,
        "grade": "D",
        "score": 0.0,
        "summary": "Smoke fixture only; not eligible for live readiness.",
        "failed_checks": [{"key": "fixture_smoke", "threshold": "real baseline required", "passed": False}],
        "assumptions": {
            "money_flow_proxy_used": True,
            "buy_execution_model": "T+1 next_open_with_slippage",
            "sell_execution_model": "same_day_close_with_slippage",
            "commission_included": True,
            "slippage_included": True,
            "mock_fallback_disabled": True,
        },
    }
    return {
        "run_id": _fixture_run_id(payload),
        "status": "success",
        "strategy_code": payload.get("strategy_code"),
        "config": effective_config,
        "metrics": metrics,
        "by_state": [
            {"state_tag": "offensive", "win_rate": 0.5, "max_drawdown": 0.018, "sample_count": 2},
            {"state_tag": "neutral", "win_rate": 0.5, "max_drawdown": 0.042425, "sample_count": 2},
            {"state_tag": "defensive", "win_rate": 0.0, "max_drawdown": 0.0, "sample_count": 0},
        ],
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "trades": [],
        "closed_roundtrips": [],
        "diagnostics": diagnostics,
        "probability_calibration": {"sample_size": 4, "source": "fixture_smoke"},
        "credibility": credibility,
        "live_readiness": {
            "ready": False,
            "grade": "D",
            "score": 0.0,
            "summary": "Smoke fixture only; not live-ready evidence.",
            "failed_checks": credibility["failed_checks"],
        },
        "backtest_engine": "fixture_smoke_v1",
        "started_at": "2025-12-31 00:00:00",
        "finished_at": "2025-12-31 00:00:00",
        "fixture_inputs": {
            "commission": commission,
            "slippage": slippage,
            "universe_size": universe_size,
        },
    }


def run_live_backtest(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run the existing CoachService backtest synchronously through app.main."""
    from app.main import coach_service

    submission = coach_service.run_backtest(payload)
    run_id = submission.get("run_id")
    result = coach_service.get_backtest_result(run_id) if run_id else None
    if not result:
        raise RuntimeError(f"Backtest run did not produce a retrievable result: {submission}")
    return result


def _run_git(args: List[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def get_git_info() -> Dict[str, Any]:
    status = _run_git(["status", "--porcelain", "--untracked-files=no"])
    return {
        "sha": _run_git(["rev-parse", "HEAD"]) or "unknown",
        "dirty": bool(status),
    }


def current_generated_at() -> str:
    china_tz = timezone(timedelta(hours=8))
    return datetime.now(china_tz).isoformat(timespec="seconds")


def summarize_drawdown_curve(drawdown_curve: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not drawdown_curve:
        return {
            "points": 0,
            "start_date": None,
            "end_date": None,
            "worst_date": None,
            "min_drawdown": 0.0,
            "last_drawdown": 0.0,
        }
    worst = min(drawdown_curve, key=lambda item: float(item.get("value") or 0.0))
    return {
        "points": len(drawdown_curve),
        "start_date": drawdown_curve[0].get("date"),
        "end_date": drawdown_curve[-1].get("date"),
        "worst_date": worst.get("date"),
        "min_drawdown": round(float(worst.get("value") or 0.0), 6),
        "last_drawdown": round(float(drawdown_curve[-1].get("value") or 0.0), 6),
    }


def build_data_coverage(run_result: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = run_result.get("diagnostics") or {}
    config = run_result.get("config") or payload.get("config") or {}
    universe_size = int(diagnostics.get("universe_size") or config.get("universe_size") or 0)
    valid_history_symbols = int(diagnostics.get("valid_history_symbols") or 0)
    coverage_ratio = (
        round(valid_history_symbols / universe_size, 6)
        if universe_size > 0
        else 0.0
    )
    return {
        "source": diagnostics.get("source"),
        "test_start": config.get("test_start") or payload.get("test_start"),
        "test_end": config.get("test_end") or payload.get("test_end"),
        "calendar_days": int(diagnostics.get("calendar_days") or 0),
        "universe_size": universe_size,
        "valid_history_symbols": valid_history_symbols,
        "coverage_ratio": coverage_ratio,
    }


def build_execution_assumptions(run_result: Dict[str, Any]) -> Dict[str, Any]:
    config = run_result.get("config") or {}
    credibility = run_result.get("credibility") or {}
    assumptions = dict(credibility.get("assumptions") or {})
    return {
        "buy_execution_model": assumptions.get("buy_execution_model", "T+1 next_open_with_slippage"),
        "sell_execution_model": assumptions.get("sell_execution_model", "same_day_close_with_slippage"),
        "commission": float(config.get("commission") or 0.0),
        "slippage": float(config.get("slippage") or 0.0),
        "commission_included": bool(assumptions.get("commission_included", True)),
        "slippage_included": bool(assumptions.get("slippage_included", True)),
        "mock_fallback_disabled": bool(assumptions.get("mock_fallback_disabled", False)),
        "constraints": [
            "Signals are generated before buy execution.",
            "Buy execution uses the next trading session open with slippage.",
            "Sell execution uses configured stop/take-profit/holding logic from CoachService.",
        ],
    }


def _command_args(args: argparse.Namespace) -> Dict[str, Any]:
    return {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}


def build_artifact(
    run_result: Dict[str, Any],
    payload: Dict[str, Any],
    args: argparse.Namespace,
    mode: str,
    git_info: Dict[str, Any],
    generated_at: str,
    output_path: Optional[str],
) -> Dict[str, Any]:
    fixture_mode = mode == "fixture_smoke"
    warning = (
        "Smoke fixture is deterministic and non-investable; it validates harness wiring only."
        if fixture_mode
        else "Real baseline artifact; review data coverage and credibility gates before use."
    )
    return {
        "baseline_schema_version": BASELINE_SCHEMA_VERSION,
        "artifact_type": "coach_backtest_baseline",
        "evidence_mode": mode,
        "investable_evidence": not fixture_mode,
        "evidence_warning": warning,
        "strategy_code": run_result.get("strategy_code") or payload.get("strategy_code"),
        "run_id": run_result.get("run_id"),
        "status": run_result.get("status"),
        "effective_config": run_result.get("config") or payload.get("config") or {},
        "execution_assumptions": build_execution_assumptions(run_result),
        "data_coverage": build_data_coverage(run_result, payload),
        "metrics": run_result.get("metrics") or {},
        "metrics_tolerance": {
            "key_metric_fields": list(KEY_METRIC_FIELDS),
            "repeat_match_absolute_tolerance": 1e-12 if fixture_mode else 1e-9,
        },
        "drawdown_curve_summary": summarize_drawdown_curve(run_result.get("drawdown_curve") or []),
        "diagnostics": run_result.get("diagnostics") or {},
        "by_state": run_result.get("by_state") or [],
        "live_readiness": run_result.get("live_readiness") or {},
        "output_artifacts": {
            "artifact_path": str(output_path) if output_path else None,
            "format": "json",
            "contains": [
                "effective_config",
                "execution_assumptions",
                "data_coverage",
                "metrics",
                "drawdown_curve_summary",
                "diagnostics",
            ],
        },
        "reproducibility": {
            "git_sha": git_info.get("sha") or "unknown",
            "dirty": bool(git_info.get("dirty")),
            "command_args": _command_args(args),
            "generated_at": generated_at,
            "baseline_schema_version": BASELINE_SCHEMA_VERSION,
        },
    }


def write_artifact(artifact: Dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def key_metrics_match(
    first: Dict[str, Any],
    second: Dict[str, Any],
    tolerance: float = 1e-9,
    keys: Iterable[str] = KEY_METRIC_FIELDS,
) -> bool:
    for key in keys:
        left = float(first.get(key) or 0.0)
        right = float(second.get(key) or 0.0)
        if abs(left - right) > tolerance:
            return False
    return True


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    payload = build_backtest_payload(args)
    mode = "fixture_smoke" if args.fixture == "smoke" else "historical_replay"
    run_result = run_fixture_smoke(payload) if args.fixture == "smoke" else run_live_backtest(payload)
    output_path = Path(args.output)
    artifact = build_artifact(
        run_result=run_result,
        payload=payload,
        args=args,
        mode=mode,
        git_info=get_git_info(),
        generated_at=current_generated_at(),
        output_path=str(output_path),
    )
    try:
        written_path = write_artifact(artifact, output_path)
    except OSError as exc:
        print(f"error: failed to write artifact to {output_path}: {exc}", file=sys.stderr)
        return 1
    metrics = artifact.get("metrics") or {}
    print(f"wrote artifact: {written_path}")
    print(f"mode: {mode}")
    print(f"run_id: {artifact.get('run_id')}")
    print(
        "key_metrics: "
        + ", ".join(f"{key}={metrics.get(key)}" for key in KEY_METRIC_FIELDS)
    )
    if args.fixture == "smoke":
        print("warning: smoke fixture is deterministic, synthetic, and non-investable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
