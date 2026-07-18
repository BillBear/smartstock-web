#!/usr/bin/env python3
"""Certify a completed full-market build before feature/model research."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.certified_dataset import certify_full_market_run
from app.evaluation.full_market_ml.sample_certification_runner import run_certification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="certification policy JSON")
    parser.add_argument("--asset-root", required=True, help="immutable local ML asset root")
    parser.add_argument("--run-root", help="completed Task 5 full-build runtime root for the V2 pre-feature contract")
    parser.add_argument("--code-commit", default=os.environ.get("GIT_COMMIT", ""))
    # Legacy evidence mode stays read-only so older certified assets remain
    # reproducible.  New formal runs must use --run-root.
    parser.add_argument("--output-root", help="legacy certification output root")
    parser.add_argument("--secondary-label-audit", help="legacy secondary label audit JSON")
    parser.add_argument("--security-provenance", help="legacy security provenance JSON")
    parser.add_argument("--sample-contract", help="legacy pre-derived sample contract JSON")
    arguments = parser.parse_args(argv)
    if not arguments.run_root:
        return _run_legacy(arguments)
    policy = _load_policy(Path(arguments.config))
    _validate_policy(policy)
    commit = str(arguments.code_commit).strip() or _git_commit()
    result = certify_full_market_run(
        run_root=arguments.run_root,
        asset_root=arguments.asset_root,
        code_commit=commit,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _run_legacy(arguments: argparse.Namespace) -> int:
    """Run the prior immutable-evidence reader without treating it as V2 input."""
    result = run_certification(
        config_path=Path(arguments.config),
        asset_root=Path(arguments.asset_root),
        output_root=Path(arguments.output_root) if arguments.output_root else Path(arguments.asset_root) / "certifications",
        secondary_label_audit_path=Path(arguments.secondary_label_audit) if arguments.secondary_label_audit else None,
        security_provenance_path=Path(arguments.security_provenance) if arguments.security_provenance else None,
        sample_contract_path=Path(arguments.sample_contract) if arguments.sample_contract else None,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["certificate"]["status"] == "certified_research_sample" else 2


def _load_policy(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("certification policy must be a JSON object")
    return payload


def _validate_policy(policy: dict[str, object]) -> None:
    required = {
        "certification_version": "full_market_sample_v2",
        "outer_folds": 5,
        "embargo_sessions": 20,
        "stock_holdout_ratio": 0.20,
        "sealed_temporal_audit_dates": 60,
        "production_integration_allowed": False,
    }
    for key, expected in required.items():
        if policy.get(key) != expected:
            raise ValueError(f"certification policy requires {key}={expected!r}")


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"sample certification blocked: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(2)
