#!/usr/bin/env python3
"""Run measured contract/model preflight for ranking research."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.research_contract import contract_from_mapping
from app.evaluation.full_market_ml.research_preflight import (
    collect_research_evidence,
    evaluate_research_preflight,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("contract", "model"))
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw = args.config.read_bytes()
    import hashlib

    contract = contract_from_mapping(
        json.loads(raw.decode("utf-8")), source_config_sha256=hashlib.sha256(raw).hexdigest()
    )
    evidence = collect_research_evidence(
        contract, args.run_root, args.asset_root, phase=args.phase
    )
    report = evaluate_research_preflight(
        evidence, expected_contract_sha=contract.sha256(), phase=args.phase
    )
    output = args.output or args.run_root / "artifacts" / "preflight" / args.phase / "preflight_report.json"
    _write_json_atomic(output, report)
    print(json.dumps({"output": str(output), "passed": report["passed"], "failed_gates": report["failed_gates"]}, sort_keys=True))
    return 0 if report["passed"] else 2


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
