#!/usr/bin/env python3
"""Audit full-market ML training dataset readiness without training a model."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.ml_training_audit import (  # noqa: E402
    build_ml_training_readiness_audit,
    write_ml_training_readiness_audit,
)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit SmartStock ML training dataset readiness.")
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--sample-step", type=int, default=3)
    parser.add_argument("--min-full-market-count", type=int, default=5000)
    parser.add_argument("--min-symbol-count", type=int, default=1500)
    parser.add_argument("--min-time-span-days", type=int, default=730)
    parser.add_argument("--min-estimated-samples", type=int, default=100000)
    parser.add_argument("--min-snapshot-dates", type=int, default=30)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args(argv)


def run(argv: Optional[Iterable[str]] = None, store=None) -> int:
    args = parse_args(argv)
    if store is None:
        load_local_env()
        from app.main import coach_store
        store = coach_store

    audit = build_ml_training_readiness_audit(
        store=store,
        train_start=args.train_start,
        train_end=args.train_end,
        sample_step=args.sample_step,
        min_full_market_count=args.min_full_market_count,
        min_symbol_count=args.min_symbol_count,
        min_time_span_days=args.min_time_span_days,
        min_estimated_samples=args.min_estimated_samples,
        min_snapshot_dates=args.min_snapshot_dates,
    )
    write_ml_training_readiness_audit(audit, output_json=args.output_json, output_md=args.output_md)
    print_summary(audit)
    return 0


def print_summary(audit: dict) -> None:
    observed = audit.get("observed") or {}
    print(f"status: {audit.get('status')}")
    print(f"dataset_build_ready: {audit.get('dataset_build_ready')}")
    print(f"production_ml_ready: {audit.get('production_ml_ready')}")
    print(f"latest_snapshot_trade_date: {observed.get('latest_snapshot_trade_date') or '-'}")
    print(f"latest_snapshot_count: {observed.get('latest_snapshot_count')}")
    print(f"eligible_full_market_snapshot_date_count: {observed.get('eligible_full_market_snapshot_date_count')}")
    print(f"estimated_sample_count: {observed.get('estimated_sample_count')}")
    print(f"blocking_codes: {','.join(audit.get('blocking_codes') or []) or '-'}")


def load_local_env(env_file: Optional[Path] = None) -> Optional[Path]:
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


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
