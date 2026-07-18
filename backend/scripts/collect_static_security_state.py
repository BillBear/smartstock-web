#!/usr/bin/env python3
"""Collect a token-safe immutable TuShare stock-master evidence asset."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.static_security_state import collect_static_security_state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--observed-at-utc", default=None)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    pro_factory: Callable[[str], Any] | None = None,
) -> int:
    args = parse_args(argv)
    environment = os.environ if environ is None else environ
    token = str(environment.get("TUSHARE_TOKEN", "")).strip()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is not configured")
    if pro_factory is None:
        import tushare as ts

        pro_factory = ts.pro_api
    asset = collect_static_security_state(
        pro_factory(token),
        Path(args.asset_root).resolve() / "security-state",
        observed_at_utc=args.observed_at_utc,
    )
    print(json.dumps(asset.public_summary(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _sanitise(message: str) -> str:
    token = os.environ.get("TUSHARE_TOKEN", "")
    return message.replace(token, "[redacted]") if token else message


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"static_security_state_error: {_sanitise(str(error))}", file=sys.stderr)
        raise SystemExit(1)
