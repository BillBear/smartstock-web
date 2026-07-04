from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def _load_local_env(backend_root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    repo_root = backend_root.parent
    from app.evaluation.local_ml_environment import local_secret_candidates

    candidates = [str(backend_root / ".env"), *local_secret_candidates(repo_root)]
    for path in candidates:
        env_path = Path(path)
        if env_path.exists():
            load_dotenv(env_path, override=False)


def parse_args():
    parser = argparse.ArgumentParser(description="Check local ML training environment.")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--history-smoke-symbols", default="002415,600519,300750")
    parser.add_argument("--train-end", default=None)
    return parser.parse_args()


def main() -> int:
    backend_root = _bootstrap_paths()
    _load_local_env(backend_root)

    from app.evaluation.local_ml_config import build_local_ml_config
    from app.evaluation.local_ml_environment import evaluate_environment_report
    from app.main import data_source_manager

    args = parse_args()
    cfg_payload = {"output_root": args.output_root} if args.output_root else {}
    if args.train_end:
        cfg_payload["train_end"] = args.train_end
    cfg = build_local_ml_config(cfg_payload)
    symbols = [item.strip() for item in args.history_smoke_symbols.split(",") if item.strip()]
    report = evaluate_environment_report(cfg, data_source_manager, symbols)
    output_root = Path(cfg["output_root"]) / cfg["run_id"]
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "preflight_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ready": report["ready"],
                "blocking_codes": report["blocking_codes"],
                "report_path": str(report_path),
                "tushare_token_configured": bool(os.environ.get("TUSHARE_TOKEN")),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
