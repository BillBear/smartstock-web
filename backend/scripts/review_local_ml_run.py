from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_paths() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def parse_args():
    parser = argparse.ArgumentParser(description="Review a finished local ML run.")
    parser.add_argument("run_dir")
    return parser.parse_args()


def main() -> int:
    _bootstrap_paths()
    from app.evaluation.ml_training_reviewer import review_local_ml_run

    args = parse_args()
    review = review_local_ml_run(args.run_dir)
    print(json.dumps({"recommendation": review["recommendation"], "run_dir": args.run_dir}, ensure_ascii=False))
    return 0 if review["recommendation"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
