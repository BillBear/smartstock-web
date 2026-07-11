#!/usr/bin/env python3
"""Run the full-market ML environment and TuShare preflight."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.config import load_full_market_ml_config  # noqa: E402
from app.evaluation.full_market_ml.preflight import run_preflight  # noqa: E402


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full-market ML preflight checks.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default="../runtime/ml_full_market/preflight.json")
    return parser.parse_args(argv)


def run(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    config = load_full_market_ml_config(args.config)
    output_path = Path(args.output).resolve()
    probe_client = _probe_client(os.environ)
    result = run_preflight(
        config,
        env=os.environ,
        probe_client=probe_client,
        runtime_root=output_path.parent,
    )
    print(f"ready: {result['ready']}")
    print(f"blocking_codes: {','.join(result['blocking_codes']) or '-'}")
    print(f"output: {output_path}")
    return 0 if result["ready"] else 1


def _probe_client(env: dict[str, str]):
    token = env.get("TUSHARE_TOKEN", "").strip()
    if not token:
        return None
    try:
        import tushare

        tushare.set_token(token)
        return tushare.pro_api()
    except Exception:
        return None


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
