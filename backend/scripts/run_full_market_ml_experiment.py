from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run research-only full-market supervised ML experiment.")
    parser.add_argument("--panel-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--smoke", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.full_market_ml_trainer import run_full_market_ml_experiment

    args = parse_args(argv)
    summary = run_full_market_ml_experiment(args.panel_dir, args.output_dir, smoke=args.smoke)
    print(
        json.dumps(
            {
                "model_status": summary.get("model_status"),
                "production_enabled": summary.get("production_enabled"),
                "best_model": summary.get("best_model"),
                "output_dir": args.output_dir,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
