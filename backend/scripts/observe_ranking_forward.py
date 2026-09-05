#!/usr/bin/env python3
"""Capture existing same-day signals or evaluate frozen current-vs-A observations."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.evaluation.ranking_forward_observation import capture_day, read_days, evaluate_days, digest, _create, _read
from scripts.analyze_ranking_quality import load_persisted_inputs, ExplicitHistoryFetcher, DEFAULT_DB_URL, freeze_observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "evaluate", "status"))
    parser.add_argument("--root", type=Path, required=True, help="Persistent research directory outside disposable worktrees")
    parser.add_argument("--database-url", default=os.environ.get("COACH_DB_URL", DEFAULT_DB_URL))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if args.command == "capture":
        if now.hour < 16:
            result = {"status": "before_capture_window", "date": now.date().isoformat()}
        else:
            snapshots, config, _ = load_persisted_inputs(args.database_url, "default", "trend_breakout", "medium")
            result = capture_day(root, snapshots, config, now)
        freeze_observation(root / "checks", {"checked_at": now.isoformat(), **result})
    else:
        days = read_days(root)
        if not days:
            result = {"status": "waiting_for_forward_observations", "observation_date_count": 0}
        elif args.command == "status":
            result = {"status": "observing", "observation_date_count": len(days), "dates": [day["trade_date"] for day in days]}
        else:
            run = root / "runs" / (now.date().isoformat() + "-" + digest(days)[:12])
            target = run / "evaluation.json"
            if target.exists():
                evaluation = _read(target)
            else:
                token = os.environ.get("TUSHARE_TOKEN", "")
                if args.env_file:
                    from dotenv import dotenv_values
                    token = str(dotenv_values(args.env_file).get("TUSHARE_TOKEN") or token)
                if not token:
                    raise ValueError("token_missing")
                fetcher = ExplicitHistoryFetcher(token, cache_dir=run / "history")
                evaluation = evaluate_days(root, fetcher, now)
                if any(row.get("label_missing_reason") for row in evaluation.get("labeled_rows", [])):
                    ref = freeze_observation(run / "failed_attempts", evaluation)
                    print(json.dumps({"status": "label_data_incomplete", "evidence": ref}, ensure_ascii=False))
                    return 2
                evaluation = _create(target, evaluation)
            result = {"status": evaluation["status"], "observation_date_count": len(days),
                      "mature_dates": evaluation["mature_dates"], "result_path": str(target),
                      "paired_date_count": evaluation["comparison"]["paired_comparison"].get("matched_date_count", 0),
                      "automatic_promotion": False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result["status"] in ("config_changed", "snapshot_changed_after_freeze") else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        sys.exit(1)
