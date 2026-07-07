from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap() -> Path:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate SmartStock strategy and ML promotion gate.")
    parser.add_argument("--metrics-json", required=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap()
    from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

    args = parse_args(argv)
    metrics = json.loads(Path(args.metrics_json).read_text(encoding="utf-8"))
    result = evaluate_promotion_gate(metrics)
    output = Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "completed", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
