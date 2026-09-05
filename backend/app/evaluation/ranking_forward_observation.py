"""Append-only observation of existing signals; no production strategy calls."""
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from app.evaluation.ranking_quality_diagnosis import validate_snapshot_identity, label_snapshot_rows, validate_labeled_snapshot_sample
from app.evaluation.ranking_quality_experiments import compare_current_and_a


IDENTITY = {"user_id": "default", "strategy_code": "trend_breakout", "risk_level": "medium"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _read(path):
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if digest(envelope["payload"]) != envelope["sha256"]:
        raise ValueError("observation_hash_mismatch")
    return envelope["payload"]


def _create(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"payload": payload, "sha256": digest(payload)}, handle,
                      ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    except FileExistsError:
        pass
    return _read(path)


def read_days(root):
    days = [_read(path) for path in sorted((root / "days").glob("*.json"))]
    if not days:
        return []
    cohort = _read(root / "cohort.json")
    if len({day["trade_date"] for day in days}) != len(days):
        raise ValueError("duplicate_observation_dates")
    for day in days:
        if day["identity"] != IDENTITY or day["config_sha256"] != cohort["config_sha256"]:
            raise ValueError("cohort_identity_or_config_mismatch")
        if day["captured_at"][:10] != day["trade_date"]:
            raise ValueError("not_a_same_day_forward_observation")
        if any(row.get("trade_date") != day["trade_date"] or any(row.get(key) != value for key, value in IDENTITY.items()) for row in day["snapshots"]):
            raise ValueError("snapshot_identity_mismatch")
        validate_snapshot_identity(day["snapshots"])
    return days


def capture_day(root, snapshots, config, now):
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    today = local.date().isoformat()
    if local.hour < 16:
        return {"status": "before_capture_window", "date": today}
    latest = max((item.get("trade_date", "") for item in snapshots), default=None)
    rows = [dict(item) for item in snapshots if item.get("trade_date") == today]
    if not rows:
        return {"status": "waiting_for_current_day_snapshot", "date": today, "latest_snapshot_date": latest}
    if config.get("risk_level") != "medium" or any(
        config.get(key) is None or not math.isfinite(float(config[key])) or not 0 <= float(config[key]) < .5
        for key in ("commission", "slippage")
    ):
        raise ValueError("saved_configuration_missing_or_invalid")
    for row in rows:
        if any(row.get(key) != value for key, value in IDENTITY.items()):
            raise ValueError("snapshot_identity_mismatch")
        probability = row.get("dd_prob")
        if probability is None or not math.isfinite(float(probability)) or not 0 <= float(probability) <= 1:
            raise ValueError("dd_prob_unavailable_or_invalid")
        row.pop("actual_action", None)  # later manual actions are not selection inputs
    validate_snapshot_identity(rows)
    rows.sort(key=lambda row: (int(row["rank_no"]), row["symbol"]))
    config_hash = digest(config)
    cohort = _create(root / "cohort.json", {"identity": IDENTITY, "strategy_config": config,
                     "config_sha256": config_hash, "started_at": local.isoformat(),
                     "comparison": "current_rank_vs_dd_prob_ascending_only", "primary_horizon": 10,
                     "capture_window": "16:00-23:59 Asia/Shanghai, same-day only"})
    if cohort["config_sha256"] != config_hash:
        return {"status": "config_changed", "date": today}
    path = root / "days" / f"{today}.json"
    existed = path.exists()
    payload = {"identity": IDENTITY, "trade_date": today, "captured_at": local.isoformat(),
               "config_sha256": config_hash, "strategy_config": config, "snapshots": rows,
               "signals_sha256": digest(rows),
               "baseline_order": [row["symbol"] for row in rows],
               "a_order": [row["symbol"] for row in sorted(rows, key=lambda row: (float(row["dd_prob"]), row["symbol"]))]}
    saved = _create(path, payload)
    if saved["signals_sha256"] != payload["signals_sha256"]:
        return {"status": "snapshot_changed_after_freeze", "date": today, "path": str(path)}
    return {"status": "already_captured" if existed else "captured", "date": today,
            "candidate_count": len(rows), "signals_sha256": saved["signals_sha256"], "path": str(path)}


def evaluate_days(root, fetcher, now):
    days = read_days(root)
    if not days:
        return {"status": "waiting_for_forward_observations", "observation_date_count": 0}
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    config = days[0]["strategy_config"]
    costs = {"commission": config["commission"], "slippage": config["slippage"],
             "take_profit_pct": config.get("stop_profit_pct", 15), "stop_loss_pct": config.get("stop_loss_pct", 8)}
    snapshots = [row for day in days for row in day["snapshots"]]

    def bounded_history(symbol, start, end):
        return fetcher(symbol, start, min(end, local.date().isoformat()))

    labeled, coverage = label_snapshot_rows(snapshots, bounded_history, costs)
    valid, sample = validate_labeled_snapshot_sample(labeled)
    mature = {}
    for horizon in (5, 10, 20):
        mature[str(horizon)] = []
        for day in days:
            items = [row for row in valid if row["trade_date"] == day["trade_date"]]
            if len(items) == len(day["snapshots"]) and all(row.get(f"future_return_{horizon}d") is not None for row in items):
                mature[str(horizon)].append(day["trade_date"])
    return {"status": "observing_not_promoted", "observation_date_count": len(days),
            "evaluated_at": local.isoformat(), "mature_dates": mature, "coverage": coverage,
            "sample_validation": sample, "comparison": compare_current_and_a(valid),
            "labeled_rows": labeled, "costs": costs,
            "limitations": ["next_bar_open_proxy_not_verified_fill", "no_automatic_promotion", "dd_prob_may_contain_ML_influence"]}
