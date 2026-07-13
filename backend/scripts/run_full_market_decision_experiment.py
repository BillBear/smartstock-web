"""Research-only staged runner for the R4A full-market decision experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import signal
import sys
import tempfile
import threading
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DECISION_STAGES = (
    "verify-assets",
    "build-decision-labels",
    "build-r4a-features",
    "feature-audit",
    "nested-a-c-oof",
    "policy-evaluation",
    "gate-decision",
    "write-model-card",
)
DEFAULT_STAGE_TIMEOUTS = {
    "verify-assets": 15 * 60,
    "build-decision-labels": 45 * 60,
    "build-r4a-features": 90 * 60,
    "feature-audit": 60 * 60,
    "nested-a-c-oof": 45 * 60,
    "policy-evaluation": 30 * 60,
    "gate-decision": 15 * 60,
    "write-model-card": 15 * 60,
}
StageService = Callable[[dict[str, Any], Path, Path, str], Mapping[str, Any]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the research-only R4A decision experiment")
    parser.add_argument("--config", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--stage", required=True, choices=DECISION_STAGES)
    parser.add_argument("--resume", action="store_true")
    return parser


class DecisionExperimentRunner:
    """Execute one immutable development stage with heartbeat and hash checks."""

    def __init__(
        self,
        config_path: str | Path,
        asset_root: str | Path,
        run_root: str | Path,
        *,
        services: Mapping[str, StageService] | None = None,
        heartbeat_interval_seconds: float = 30.0,
    ):
        self.config_path = Path(config_path).resolve()
        self.asset_root = Path(asset_root).resolve()
        self.run_root = Path(run_root).resolve()
        self.config = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        self.config_sha256 = _file_sha256(self.config_path)
        self.code_sha256 = _research_code_sha256()
        self.asset_manifest = self.asset_root / "asset_manifest.json"
        if not self.asset_manifest.is_file():
            raise FileNotFoundError(f"asset manifest is missing: {self.asset_manifest}")
        self.asset_manifest_sha256 = _file_sha256(self.asset_manifest)
        self.services = dict(services or default_services())
        missing = sorted(set(DECISION_STAGES) - set(self.services))
        if missing:
            raise ValueError("missing decision experiment services: " + ", ".join(missing))
        self.heartbeat_interval_seconds = max(0.01, float(heartbeat_interval_seconds))

    def run(self, stage: str, *, resume: bool = False) -> dict[str, Any]:
        if stage not in DECISION_STAGES:
            raise ValueError("unknown decision stage")
        stage_index = DECISION_STAGES.index(stage)
        upstream = {}
        for name in DECISION_STAGES[:stage_index]:
            state = self._read_state(name)
            if not self._state_reusable(state):
                raise RuntimeError(f"upstream stage is incomplete or invalid: {name}")
            upstream[name] = state
        inputs = {
            "config_sha256": self.config_sha256,
            "code_sha256": self.code_sha256,
            "asset_manifest_sha256": self.asset_manifest_sha256,
            **_additional_asset_hashes(self.config, self.asset_root),
            **{
                f"upstream:{name}": _json_sha256(state)
                for name, state in upstream.items()
            },
        }
        existing = self._read_state(stage)
        if existing and self._state_reusable(existing) and existing.get("input_hashes") == inputs:
            if resume:
                return existing
            raise FileExistsError(f"stage already complete: {stage}; use --resume")
        if existing and existing.get("status") == "complete":
            raise ValueError(f"stage contract changed after completion: {stage}")

        started = _now()
        running = self._state(stage, "running", inputs, {}, started_at=started)
        self._write_state(stage, running)
        stop = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(stage, stop), daemon=True)
        heartbeat.start()
        prior_alarm = self._start_timeout(stage)
        try:
            output = dict(self.services[stage](self.config, self.asset_root, self.run_root, stage) or {})
            complete = self._state(stage, "complete", inputs, output, started_at=started, ended_at=_now())
            self._write_state(stage, complete)
            return complete
        except TimeoutError as error:
            timeout = self._state(
                stage,
                "timeout",
                inputs,
                {},
                started_at=started,
                ended_at=_now(),
                failure={"type": type(error).__name__, "message": str(error)},
            )
            self._write_state(stage, timeout)
            raise
        except Exception as error:
            failed = self._state(
                stage,
                "failed",
                inputs,
                {},
                started_at=started,
                ended_at=_now(),
                failure={"type": type(error).__name__, "message": str(error)},
            )
            self._write_state(stage, failed)
            raise
        finally:
            self._stop_timeout(prior_alarm)
            stop.set()
            heartbeat.join(timeout=max(1.0, self.heartbeat_interval_seconds * 2))

    def _heartbeat(self, stage: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval_seconds):
            state = self._read_state(stage)
            if not state or state.get("status") != "running":
                return
            state["heartbeat_at"] = _now()
            self._write_state(stage, state, event="heartbeat")

    def _start_timeout(self, stage: str):
        timeout = float(self.config.get("budgets", {}).get(stage.replace("-", "_"), DEFAULT_STAGE_TIMEOUTS[stage]))
        if timeout <= 0 or not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
            return None
        previous = signal.getsignal(signal.SIGALRM)

        def raise_timeout(_number, _frame):
            raise TimeoutError(f"stage={stage} exceeded timeout_seconds={timeout}")

        signal.signal(signal.SIGALRM, raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        return previous

    @staticmethod
    def _stop_timeout(previous) -> None:
        if previous is None or not hasattr(signal, "SIGALRM"):
            return
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

    def _state(
        self,
        stage: str,
        status: str,
        inputs: Mapping[str, str],
        artifacts: Mapping[str, Any],
        *,
        started_at: str,
        ended_at: str | None = None,
        failure: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "status": status,
            "input_hashes": dict(inputs),
            "artifacts": dict(artifacts),
            "artifact_hashes": _artifact_hashes(artifacts),
            "started_at": started_at,
            "ended_at": ended_at,
            "heartbeat_at": ended_at or _now(),
            "elapsed_seconds": _elapsed(started_at, ended_at),
            "pid": os.getpid(),
            "failure": dict(failure) if failure else None,
        }

    def _state_reusable(self, state: dict[str, Any] | None) -> bool:
        return bool(
            state
            and state.get("status") == "complete"
            and state.get("artifact_hashes") == _artifact_hashes(state.get("artifacts", {}))
        )

    def _state_path(self, stage: str) -> Path:
        return self.run_root / "stages" / stage / "stage_state.json"

    def _read_state(self, stage: str) -> dict[str, Any] | None:
        path = self._state_path(stage)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _write_state(self, stage: str, state: dict[str, Any], *, event: str | None = None) -> None:
        path = self._state_path(stage)
        _write_json_atomic(path, state)
        _write_json_atomic(self.run_root / "progress.json", state)
        log = path.parent / "stage.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": _now(), "event": event or state["status"], "stage": stage}) + "\n")


def decide_r4a_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the immutable R4A development gates without tuning from results."""
    a_model = metrics["a_time"]["model"]
    a_base = metrics["a_time"]["amount_log"]
    c_model = metrics["c_unseen"]["model"]
    c_base = metrics["c_unseen"]["amount_log"]
    failed = []
    for key, code in (
        ("precision_at_5", "a_precision_at_5_not_above_amount_log"),
        ("ndcg_at_10", "a_ndcg_at_10_not_above_amount_log"),
        ("top5_mean_return", "a_top5_mean_return_not_above_amount_log"),
        ("top5_median_return", "a_top5_median_return_not_above_amount_log"),
    ):
        if float(a_model[key]) <= float(a_base[key]):
            failed.append(code)
    if float(a_model["top5_median_return"]) <= 0.0:
        failed.append("a_top5_median_return_not_positive")
    if float(a_base["severe_rate"]) - float(a_model["severe_rate"]) < 0.05:
        failed.append("a_severe_rate_uplift_below_5pp")
    bootstrap = metrics["bootstrap"]
    if float(bootstrap["precision_at_5_uplift_ci_low"]) <= 0.0:
        failed.append("precision_bootstrap_lower_bound_not_positive")
    if float(bootstrap["top5_mean_return_uplift_ci_low"]) <= 0.0:
        failed.append("return_bootstrap_lower_bound_not_positive")
    folds = list(metrics["folds"])
    required = max(1, int(len(folds) * 0.8 + 0.999999))
    if sum(float(row["model_ndcg_at_10"]) >= float(row["baseline_ndcg_at_10"]) for row in folds) < required:
        failed.append("fold_ndcg_consistency_below_80_percent")
    if sum(float(row["model_top5_median_return"]) > 0.0 for row in folds) < required:
        failed.append("fold_positive_median_consistency_below_80_percent")
    if float(c_model["precision_at_5"]) < 0.8 * float(a_model["precision_at_5"]):
        failed.append("c_precision_below_80_percent_of_a")
    if float(c_model["ndcg_at_10"]) < 0.8 * float(a_model["ndcg_at_10"]):
        failed.append("c_ndcg_below_80_percent_of_a")
    if float(c_model["precision_at_5"]) < float(c_base["precision_at_5"]) and float(c_model["ndcg_at_10"]) < float(c_base["ndcg_at_10"]):
        failed.append("c_trails_amount_log_on_precision_and_ndcg")
    portfolio = metrics["portfolio"]
    if float(portfolio["model"]["maximum_drawdown"]) < float(portfolio["amount_log"]["maximum_drawdown"]):
        failed.append("portfolio_drawdown_worse_than_amount_log")
    if float(portfolio["model"]["return_drawdown_ratio"]) < float(portfolio["amount_log"]["return_drawdown_ratio"]):
        failed.append("portfolio_return_drawdown_ratio_worse_than_amount_log")
    selective = metrics["selective"]
    if selective.get("threshold") is not None:
        if float(selective["precision_at_5"]) < 0.60:
            failed.append("selective_precision_below_60_percent")
        if float(selective["wilson_lower_bound"]) < 0.50:
            failed.append("selective_wilson_lower_bound_below_50_percent")
        if float(selective["severe_rate"]) > 0.15:
            failed.append("selective_severe_rate_above_15_percent")
        if float(selective["selected_date_coverage"]) < 0.15:
            failed.append("selective_date_coverage_below_15_percent")
    calibration = metrics["calibration"]
    if (
        float(calibration["ece"]) > 0.05
        or float(calibration["brier"]) >= float(calibration["prevalence_brier"])
        or not bool(calibration["bin_hit_rates_non_decreasing"])
    ):
        failed.append("probability_calibration_gate_failed")
    return {
        "status": "r4a_passed_development_gate" if not failed else "research_only_failed_gate",
        "failed_gates": failed,
        "probability_display_allowed": "probability_calibration_gate_failed" not in failed,
    }


def default_services() -> dict[str, StageService]:
    return {
        "verify-assets": _verify_assets,
        "build-decision-labels": _build_decision_labels,
        "build-r4a-features": _build_r4a_features,
        "feature-audit": _run_feature_audit,
        "nested-a-c-oof": _run_nested_oof,
        "policy-evaluation": _run_policy_evaluation,
        "gate-decision": _run_gate_decision,
        "write-model-card": _write_model_card,
    }


def _verify_assets(config: dict[str, Any], asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    from app.evaluation.full_market_ml.data_inventory import audit_source_fields, resolve_raw_asset_root

    manifest = _asset_manifest(asset_root)
    if manifest.get("verification_status") != "verified":
        raise ValueError("asset manifest verification_status must be verified")
    required_free_gb = float(config.get("run", {}).get("minimum_free_disk_gb", 50.0))
    free_bytes = shutil.disk_usage(run_root.parent if run_root.parent.exists() else asset_root).free
    if free_bytes < required_free_gb * 1024**3:
        raise RuntimeError(f"free disk below {required_free_gb:g} GB")
    dataset_root, raw_root = _asset_sources(asset_root)
    verified_files = 0
    verified_bytes = 0
    for source_root in (dataset_root, raw_root):
        source_manifest = json.loads((source_root / "source_manifest.json").read_text(encoding="utf-8"))
        if source_manifest.get("verification_status") != "verified":
            raise ValueError(f"source asset is not verified: {source_root}")
        for entry in source_manifest.get("files", []):
            path = source_root / str(entry["path"])
            if not path.is_file() or path.stat().st_size != int(entry["bytes"]) or _file_sha256(path) != entry["sha256"]:
                raise ValueError(f"asset checksum mismatch: {path}")
            verified_files += 1
            verified_bytes += path.stat().st_size
    resolved_raw, collection_manifest = resolve_raw_asset_root(asset_root)
    inventory = audit_source_fields(resolved_raw, collection_manifest)
    if not inventory.get("r4a_ready"):
        raise RuntimeError("R4A source inventory is not ready: " + ", ".join(inventory.get("blocking_codes", [])))
    output = _artifact_dir(run_root, "verify-assets")
    input_manifest = output / "input_manifest.json"
    quality = output / "data_quality_report.json"
    _write_json_atomic(
        input_manifest,
        {
            "dataset_id": manifest.get("dataset_id"),
            "asset_manifest_sha256": _file_sha256(asset_root / "asset_manifest.json"),
            "dataset_root": str(dataset_root),
            "raw_root": str(raw_root),
            "verified_files": verified_files,
            "verified_bytes": verified_bytes,
            "free_disk_bytes": free_bytes,
        },
    )
    _write_json_atomic(quality, inventory)
    return {"input_manifest": str(input_manifest), "data_quality_report": str(quality)}


def _build_decision_labels(config: dict[str, Any], asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    import pandas as pd

    from app.evaluation.full_market_ml.decision_labels import DecisionLabelContract, add_decision_labels

    dataset_root, _ = _asset_sources(asset_root)
    split = _load_source_split(dataset_root)
    development_dates = set(split.development_dates)
    contract = DecisionLabelContract(**config.get("labels", {}))
    output = _artifact_dir(run_root, "build-decision-labels")
    shard_root = output / "shards"
    daily_rows = []
    artifacts = []
    for source in _source_dataset_shards(dataset_root):
        rows = pd.read_parquet(source)
        rows["trade_date"] = pd.to_datetime(rows["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        rows = rows.loc[rows["trade_date"].isin(development_dates)].copy()
        rows = _add_research_strata(rows)
        labeled = add_decision_labels(rows, contract)
        destination = shard_root / source.parent.name / "data.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        labeled.to_parquet(destination, index=False)
        artifacts.append(_artifact_entry(destination, output))
        grouped = labeled.groupby("trade_date", sort=True).agg(
            row_count=("symbol", "size"),
            actionable_count=("label_actionable_positive_10d", "sum"),
            severe_count=("label_severe_negative_10d_v2", "sum"),
            eligible_count=("eligible_for_training_10d", "sum"),
        )
        daily_rows.append(grouped.reset_index())
    distribution = pd.concat(daily_rows, ignore_index=True).groupby("trade_date", as_index=False).sum()
    distribution["actionable_rate"] = distribution["actionable_count"] / distribution["eligible_count"].replace(0, pd.NA)
    distribution["severe_rate"] = distribution["severe_count"] / distribution["eligible_count"].replace(0, pd.NA)
    distribution_path = output / "decision_label_distribution.csv"
    distribution.to_csv(distribution_path, index=False)
    manifest_path = output / "label_manifest.json"
    _write_json_atomic(
        manifest_path,
        {
            "contract": config.get("labels", {}),
            "development_date_count": len(development_dates),
            "row_count": int(distribution["row_count"].sum()),
            "shards": artifacts,
        },
    )
    return {
        "label_manifest": str(manifest_path),
        "decision_label_distribution": str(distribution_path),
        "labeled_shard_root": str(shard_root),
    }


def _build_r4a_features(config: dict[str, Any], asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    import pandas as pd

    from app.evaluation.full_market_ml.interaction_features import INTERACTION_FEATURE_NAMES, build_interaction_features
    from app.evaluation.full_market_ml.market_industry_features import (
        INDUSTRY_FEATURE_NAMES,
        MARKET_FEATURE_NAMES,
        build_industry_state_features,
        build_market_state_features,
    )
    from app.evaluation.full_market_ml.moneyflow_features import MONEYFLOW_FEATURE_NAMES, build_moneyflow_features
    from app.evaluation.full_market_ml.collector import load_point_in_time_fundamentals
    from app.evaluation.full_market_ml.fundamental_features import (
        FUNDAMENTAL_FEATURE_NAMES,
        build_point_in_time_fundamental_features,
    )

    _, raw_root = _asset_sources(asset_root)
    label_root = _artifact_dir(run_root, "build-decision-labels") / "shards"
    labeled_paths = sorted(label_root.glob("shard=*/data.parquet"))
    if not labeled_paths:
        raise FileNotFoundError("labeled shards are missing")
    context_columns = [
        "trade_date", "symbol", "industry_l1", "adjusted_return_1d", "adjusted_return_5d",
        "adjusted_return_20d", "price_to_sma_20d", "total_mv", "at_up_limit", "at_down_limit",
        "amount_ratio_5d", "turnover_rate",
    ]
    context = pd.concat([pd.read_parquet(path, columns=context_columns) for path in labeled_paths], ignore_index=True)
    market = build_market_state_features(context)[["trade_date", "symbol", *MARKET_FEATURE_NAMES]]
    industry = build_industry_state_features(context)[["trade_date", "symbol", *INDUSTRY_FEATURE_NAMES]]
    context_features = market.merge(industry, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    del context, market, industry

    flow = _load_moneyflow_frame(raw_root)
    fundamental_config = config.get("fundamentals")
    fundamental_sources = None
    if fundamental_config:
        fundamental_root = _fundamental_asset_root(config, asset_root)
        fundamental_sources = {
            endpoint: load_point_in_time_fundamentals(fundamental_root, endpoint)
            for endpoint in ("fina_indicator", "forecast", "express")
        }

    configured_features = _configured_feature_names(config)
    required_columns = {
        "trade_date", "symbol", "industry_l1", "amount_log", "amount_cny", "future_return_10d",
        "eligible_for_training_10d", "entry_tradeable_10d", "net_return_after_cost_10d", "mfe_10d", "mae_10d",
        "label_actionable_positive_10d", "label_severe_negative_10d_v2", "target_clipped_return_10d",
        "return_relevance_grade_10d_v2", "adjusted_return_5d", "adjusted_return_20d", "adjusted_return_60d",
        "amount_ratio_5d", "turnover_rate_rank", "realized_volatility_20d", "adjusted_close_to_high",
        "atr_pct_14d", "amount_log_rank",
    }
    required_columns.update(configured_features)
    output = _artifact_dir(run_root, "build-r4a-features")
    shard_root = output / "shards"
    manifest_entries = []
    for source in labeled_paths:
        rows = pd.read_parquet(source)
        rows = rows.merge(context_features, on=["trade_date", "symbol"], how="left", validate="one_to_one", suffixes=("", "_r4a"))
        for name in (*MARKET_FEATURE_NAMES, *INDUSTRY_FEATURE_NAMES):
            alias = f"{name}_r4a"
            if alias in rows:
                rows[name] = rows.pop(alias)
        rows = build_interaction_features(rows)
        shard_symbols = set(rows["symbol"].astype(str).unique())
        rows = rows.merge(flow.loc[flow["symbol"].isin(shard_symbols)], on=["trade_date", "symbol"], how="left", validate="one_to_one")
        rows = build_moneyflow_features(rows)
        if fundamental_sources is not None:
            point_in_time = build_point_in_time_fundamental_features(
                rows[["trade_date", "symbol"]],
                fundamental_sources["fina_indicator"],
                fundamental_sources["forecast"],
                fundamental_sources["express"],
            )
            rows = rows.merge(
                point_in_time[["trade_date", "symbol", *FUNDAMENTAL_FEATURE_NAMES]],
                on=["trade_date", "symbol"],
                how="left",
                validate="one_to_one",
            )
        missing = sorted(required_columns - set(rows.columns))
        if missing:
            raise ValueError("R4A compact dataset missing columns: " + ", ".join(missing))
        compact = rows[sorted(required_columns)].copy()
        destination = shard_root / source.parent.name / "data.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        compact.to_parquet(destination, index=False)
        manifest_entries.append(_artifact_entry(destination, output))
    warmup_columns = ("adjusted_return_60d", "price_to_sma_60d", "sma_20d_to_sma_60d")
    warmup_rows = pd.concat(
        [pd.read_parquet(path, columns=["trade_date", *warmup_columns]) for path in sorted(shard_root.glob("shard=*/data.parquet"))],
        ignore_index=True,
    )
    model_dates = _dates_meeting_coverage(warmup_rows, warmup_columns, threshold=0.95)
    fundamental_coverage = None
    if fundamental_sources is not None:
        coverage_rows = pd.concat(
            [
                pd.read_parquet(path, columns=["trade_date", "point_in_time_coverage_flag"])
                for path in sorted(shard_root.glob("shard=*/data.parquet"))
            ],
            ignore_index=True,
        )
        coverage_rows = coverage_rows.loc[coverage_rows["trade_date"].isin(model_dates)]
        fundamental_coverage = float(pd.to_numeric(coverage_rows["point_in_time_coverage_flag"], errors="coerce").mean())
        minimum = float(fundamental_config.get("minimum_coverage", 0.70))
        if not math.isfinite(fundamental_coverage) or fundamental_coverage < minimum:
            raise RuntimeError(f"point-in-time fundamental coverage {fundamental_coverage:.4f} is below {minimum:.4f}")
    model_dates_path = output / "model_dates.json"
    _write_json_atomic(
        model_dates_path,
        {
            "dates": list(model_dates),
            "date_count": len(model_dates),
            "minimum_signal_feature_coverage": 0.95,
            "coverage_features": list(warmup_columns),
            "target_columns_read": [],
            "point_in_time_fundamental_coverage": fundamental_coverage,
        },
    )
    manifest_path = output / "feature_manifest.json"
    _write_json_atomic(
        manifest_path,
        {
            "feature_count": len(configured_features),
            "features": list(configured_features),
            "shards": manifest_entries,
            "development_only": True,
            "fundamental_asset_id": fundamental_config.get("asset_id") if fundamental_config else None,
        },
    )
    return {
        "feature_manifest": str(manifest_path),
        "feature_shard_root": str(shard_root),
        "model_dates": str(model_dates_path),
    }


def _run_feature_audit(config: dict[str, Any], asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    import pandas as pd

    from app.evaluation.full_market_ml.feature_audit import audit_features
    from app.evaluation.full_market_ml.feature_selection import evaluate_feature_blocks

    dataset_root, _ = _asset_sources(asset_root)
    split = _load_source_split(dataset_root)
    features = _configured_feature_names(config)
    columns = [
        "trade_date", "symbol", "future_return_10d", "eligible_for_training_10d",
        "label_actionable_positive_10d", "label_severe_negative_10d_v2", "target_clipped_return_10d",
        "return_relevance_grade_10d_v2", "amount_log", *features,
    ]
    rows = _read_feature_shards(run_root, columns)
    audit = audit_features(rows, split, feature_schema=features)
    decisions = evaluate_feature_blocks(rows, split, _configured_feature_blocks(config))
    output = _artifact_dir(run_root, "feature-audit")
    coverage_path = output / "feature_coverage.csv"
    bins_path = output / "feature_bins.csv"
    drift_path = output / "feature_drift.csv"
    evidence_path = output / "feature_evidence.csv"
    decisions_path = output / "feature_block_decisions.json"
    report_path = output / "feature_audit.json"
    audit.coverage.to_csv(coverage_path, index=False)
    audit.bucket_returns.to_csv(bins_path, index=False)
    audit.drift.to_csv(drift_path, index=False)
    audit.ic.to_csv(evidence_path, index=False)
    _write_json_atomic(decisions_path, {"decisions": [vars(item) for item in decisions]})
    _write_json_atomic(report_path, audit.to_csv_rows())
    return {
        "feature_coverage": str(coverage_path),
        "feature_bins": str(bins_path),
        "feature_drift": str(drift_path),
        "feature_evidence": str(evidence_path),
        "feature_block_decisions": str(decisions_path),
        "feature_audit": str(report_path),
    }


def _run_nested_oof(config: dict[str, Any], asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    import pandas as pd

    from app.evaluation.full_market_ml.decision_model import DecisionModelSpec, run_nested_decision_oof
    from app.evaluation.full_market_ml.decision_policy import DecisionPolicySpec

    dataset_root, _ = _asset_sources(asset_root)
    split = _load_source_split(dataset_root)
    decisions_path = _artifact_dir(run_root, "feature-audit") / "feature_block_decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))["decisions"]
    accepted_blocks = {row["name"] for row in decisions if row["status"] == "accepted"}
    blocks = _configured_feature_blocks(config)
    features = tuple(dict.fromkeys(feature for name, values in blocks.items() if name in accepted_blocks for feature in values))
    if not features:
        raise RuntimeError("feature audit accepted no model feature blocks")
    if len(features) > 125:
        raise RuntimeError("accepted feature schema exceeds the 125-feature local limit")
    required = [
        "trade_date", "symbol", "amount_log", "label_actionable_positive_10d",
        "label_severe_negative_10d_v2", "target_clipped_return_10d", "return_relevance_grade_10d_v2",
        "eligible_for_training_10d", "entry_tradeable_10d", "net_return_after_cost_10d", "mfe_10d", "mae_10d",
        *features,
    ]
    rows = _read_feature_shards(run_root, required)
    seeds = tuple(int(value) for value in config.get("models", {}).get("seeds", [17, 42, 73]))
    families = tuple(config.get("models", {}).get("families", ["logistic", "lightgbm_shallow"]))
    model_specs = tuple(DecisionModelSpec(model_family=family, feature_schema=features, seeds=seeds) for family in families)
    policy_specs = tuple(
        DecisionPolicySpec(score_mode=mode, risk_quantile_gate=float(config.get("policy", {}).get("risk_quantile_gate", 0.70)))
        for mode in ("success", "return", "combined")
    )
    output = _artifact_dir(run_root, "nested-a-c-oof")
    report = run_nested_decision_oof(
        rows,
        split,
        model_specs,
        policy_specs,
        checkpoint_dir=output / "checkpoints",
        resume=True,
    )
    a_path = output / "a_time_oof_predictions.parquet"
    c_path = output / "c_unseen_oof_predictions.parquet"
    fold_path = output / "fold_metrics.csv"
    selection_path = output / "model_selection.json"
    report["a_predictions"].to_parquet(a_path, index=False)
    report["c_predictions"].to_parquet(c_path, index=False)
    pd.DataFrame(report["fold_metrics"]).to_csv(fold_path, index=False)
    _write_json_atomic(
        selection_path,
        {
            "status": report["status"],
            "failed_gates": report["failed_gates"],
            "contract_sha256": report["contract_sha256"],
            "model_metrics": report["model_metrics"],
            "baseline_metrics": report["baseline_metrics"],
            "model_selection": report["model_selection"],
            "selected_features": list(features),
        },
    )
    return {
        "a_time_oof_predictions": str(a_path),
        "c_unseen_oof_predictions": str(c_path),
        "fold_metrics": str(fold_path),
        "model_selection": str(selection_path),
    }


def _run_policy_evaluation(config: dict[str, Any], _asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    import numpy as np
    import pandas as pd

    from app.evaluation.full_market_ml.decision_evaluator import evaluate_decision_policy
    from app.evaluation.full_market_ml.decision_policy import evaluate_policy_metrics

    nested = _artifact_dir(run_root, "nested-a-c-oof")
    a_rows = pd.read_parquet(nested / "a_time_oof_predictions.parquet")
    c_rows = pd.read_parquet(nested / "c_unseen_oof_predictions.parquet")
    a_model = evaluate_policy_metrics(a_rows, score_col="policy_score", eligible_col="risk_eligible")
    a_base = evaluate_policy_metrics(a_rows, score_col="amount_log")
    c_model = evaluate_policy_metrics(c_rows, score_col="policy_score", eligible_col="risk_eligible") if not c_rows.empty else dict(a_model)
    c_base = evaluate_policy_metrics(c_rows, score_col="amount_log") if not c_rows.empty else dict(a_base)
    threshold_values = pd.to_numeric(a_rows.get("confidence_threshold"), errors="coerce").dropna()
    threshold = float(threshold_values.iloc[-1]) if len(threshold_values) else None
    model_evaluation = evaluate_decision_policy(
        _portfolio_ready_rows(a_rows),
        score_col="policy_score",
        risk_col="severe_probability",
        selection_threshold=None,
    )
    baseline_evaluation = evaluate_decision_policy(
        a_rows,
        score_col="amount_log",
        risk_col="severe_probability",
        selection_threshold=None,
    )
    bootstrap = _bootstrap_decision_uplift(
        a_rows,
        iterations=int(config.get("bootstrap", {}).get("iterations", 1000)),
        block_length=int(config.get("bootstrap", {}).get("block_length", 10)),
        seed=int(config.get("bootstrap", {}).get("seed", 42)),
    )
    selective_rows = a_rows.loc[a_rows["policy_eligible"].eq(True)].copy()
    selective_metrics = evaluate_policy_metrics(selective_rows, score_col="policy_score") if not selective_rows.empty else {
        "precision_at_5": 0.0, "ndcg_at_10": 0.0, "top5_median_return": 0.0, "severe_rate": 1.0
    }
    selected_count = int(selective_rows["label_actionable_positive_10d"].eq(True).sum())
    selective = {
        "threshold": threshold,
        **selective_metrics,
        "wilson_lower_bound": _wilson_lower(selected_count, len(selective_rows)),
        "selected_date_coverage": float(selective_rows["trade_date"].nunique() / max(1, a_rows["trade_date"].nunique())),
    }
    calibration = _calibration_report(a_rows)
    folds = pd.read_csv(nested / "fold_metrics.csv").to_dict("records")
    metrics = {
        "a_time": {"model": a_model, "amount_log": a_base},
        "c_unseen": {"model": c_model, "amount_log": c_base},
        "folds": folds,
        "bootstrap": bootstrap,
        "portfolio": {
            "model": model_evaluation.rolling_portfolio,
            "amount_log": baseline_evaluation.rolling_portfolio,
        },
        "selective": selective,
        "calibration": calibration,
    }
    output = _artifact_dir(run_root, "policy-evaluation")
    metrics_path = output / "policy_metrics.json"
    baseline_path = output / "baseline_comparison.csv"
    selective_path = output / "selective_policy_metrics.csv"
    portfolio_path = output / "portfolio_comparison.csv"
    bootstrap_path = output / "bootstrap_intervals.json"
    calibration_path = output / "calibration_report.json"
    errors_path = output / "error_samples.csv"
    _write_json_atomic(metrics_path, metrics)
    pd.DataFrame([
        {"scope": scope, "system": system, **values}
        for scope in ("a_time", "c_unseen")
        for system, values in metrics[scope].items()
    ]).to_csv(baseline_path, index=False)
    pd.DataFrame([selective]).to_csv(selective_path, index=False)
    pd.DataFrame([
        {"system": name, **values} for name, values in metrics["portfolio"].items()
    ]).to_csv(portfolio_path, index=False)
    _write_json_atomic(bootstrap_path, bootstrap)
    _write_json_atomic(calibration_path, calibration)
    _error_samples(a_rows).to_csv(errors_path, index=False)
    return {
        "policy_metrics": str(metrics_path),
        "baseline_comparison": str(baseline_path),
        "selective_policy_metrics": str(selective_path),
        "portfolio_comparison": str(portfolio_path),
        "bootstrap_intervals": str(bootstrap_path),
        "calibration_report": str(calibration_path),
        "error_samples": str(errors_path),
    }


def _run_gate_decision(_config: dict[str, Any], _asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    metrics_path = _artifact_dir(run_root, "policy-evaluation") / "policy_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    decision = decide_r4a_gate(metrics)
    output = _artifact_dir(run_root, "gate-decision")
    decision_path = output / "model_metrics.json"
    candidate_path = output / "candidate_manifest.json"
    _write_json_atomic(decision_path, {**decision, "metrics": metrics})
    _write_json_atomic(
        candidate_path,
        {
            "status": decision["status"],
            "failed_gates": decision["failed_gates"],
            "production_export_allowed": False,
            "final_fit_allowed": decision["status"] == "r4a_passed_development_gate",
            "development_only": True,
        },
    )
    return {"model_metrics": str(decision_path), "candidate_manifest": str(candidate_path)}


def _write_model_card(_config: dict[str, Any], _asset_root: Path, run_root: Path, _stage: str) -> Mapping[str, Any]:
    decision = json.loads((_artifact_dir(run_root, "gate-decision") / "model_metrics.json").read_text(encoding="utf-8"))
    output = _artifact_dir(run_root, "write-model-card")
    model_card = output / "model_card.md"
    closure = output / "run_closure.json"
    lines = [
        "# R4A Full-Market Decision Model Card",
        "",
        f"- Status: `{decision['status']}`",
        "- Scope: development A walk-forward and C unseen-stock OOF only.",
        "- Production integration: prohibited.",
        f"- Probability display allowed: `{decision['probability_display_allowed']}`",
        "",
        "## Failed Gates",
        "",
    ]
    lines.extend(f"- `{value}`" for value in decision["failed_gates"]) if decision["failed_gates"] else lines.append("- None")
    model_card.write_text("\n".join(lines) + "\n", encoding="utf-8")
    outcome = (
        "r4a_passed_development_gate"
        if decision["status"] == "r4a_passed_development_gate"
        else "r4a_failed_alpha_gate_but_pipeline_valid"
    )
    _write_json_atomic(closure, {"outcome": outcome, "status": decision["status"], "failed_gates": decision["failed_gates"]})
    return {"model_card": str(model_card), "run_closure": str(closure)}


def _asset_manifest(asset_root: Path) -> dict[str, Any]:
    manifest = json.loads((asset_root / "asset_manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("asset manifest must be an object")
    return manifest


def _load_moneyflow_frame(raw_root: Path):
    import pandas as pd
    import pyarrow.dataset as ds

    columns = [
        "ts_code", "trade_date", "buy_sm_amount", "sell_sm_amount", "buy_md_amount", "sell_md_amount",
        "buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount",
    ]
    # The parquet files already carry trade_date as a string. Do not infer the
    # Hive partition field, which Arrow otherwise types as int32 and conflicts
    # with the file schema.
    dataset = ds.dataset(raw_root / "raw" / "endpoint=moneyflow", format="parquet")
    flow = dataset.to_table(columns=columns).to_pandas()
    flow["symbol"] = flow["ts_code"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
    flow["trade_date"] = pd.to_datetime(flow["trade_date"].astype(str), errors="coerce").dt.strftime("%Y-%m-%d")
    return flow.drop(columns="ts_code").drop_duplicates(["trade_date", "symbol"], keep="last")


def _asset_sources(asset_root: Path) -> tuple[Path, Path]:
    sources = _asset_manifest(asset_root).get("sources", [])
    datasets = [Path(item["destination"]).resolve() for item in sources if item.get("role") == "dataset"]
    raws = [Path(item["destination"]).resolve() for item in sources if item.get("role") == "raw"]
    if len(datasets) != 1 or len(raws) != 1:
        raise ValueError("asset manifest must contain exactly one dataset and one raw source")
    return datasets[0], raws[0]


def _source_dataset_shards(dataset_root: Path) -> list[Path]:
    paths = sorted((dataset_root / "artifacts" / "full-build" / "dataset-v3").glob("shard=*/data.parquet"))
    if len(paths) != 64:
        raise ValueError(f"expected 64 immutable dataset shards, found {len(paths)}")
    return paths


def _load_source_split(dataset_root: Path):
    from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold

    path = dataset_root / "artifacts" / "full-build" / "split_plan_v3.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    quadrants = raw["quadrants"]
    folds = tuple(
        WalkForwardFold(
            **{
                key: tuple(value) if key in {"training_dates", "validation_dates", "training_symbols"} else value
                for key, value in fold.items()
            }
        )
        for fold in raw["walk_forward"]
    )
    return SplitPlan(
        development_dates=tuple(raw["development_dates"]),
        final_dates=tuple(raw["final_dates"]),
        stock_holdout_symbols=tuple(raw["stock_holdout_symbols"]),
        A_dev_train_symbols=tuple(quadrants["A_dev_train_symbols"]),
        B_final_train_symbols=tuple(quadrants["B_final_train_symbols"]),
        C_dev_unseen_symbols=tuple(quadrants["C_dev_unseen_symbols"]),
        D_final_unseen_symbols=tuple(quadrants["D_final_unseen_symbols"]),
        walk_forward=folds,
        stratum_counts_before=raw["stratum_counts_before"],
        stratum_counts_after=raw["stratum_counts_after"],
        split_sha256=raw["split_sha256"],
        final_holdout_frozen_model_sha=raw.get("final_holdout_frozen_model_sha"),
    )


def _add_research_strata(rows):
    import numpy as np
    import pandas as pd

    result = rows.copy()
    symbol = result["symbol"].astype("string").str.zfill(6)
    result["board"] = np.select(
        [symbol.str.startswith("688"), symbol.str.startswith(("300", "301"))],
        ["star", "chinext"],
        default="main",
    )
    for source, output in (("total_mv", "size_bucket"), ("amount_cny", "liquidity_bucket")):
        rank = result.groupby("trade_date", sort=False)[source].rank(pct=True)
        result[output] = pd.cut(
            rank,
            bins=[-np.inf, 1 / 3, 2 / 3, np.inf],
            labels=["low", "mid", "high"],
        ).astype("string")
    return result


def _configured_feature_blocks(config: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    raw = config.get("feature_blocks")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("config.feature_blocks must define pre-registered blocks")
    blocks = {str(name): tuple(str(value) for value in values) for name, values in raw.items()}
    if any(not values for values in blocks.values()):
        raise ValueError("feature blocks must not be empty")
    return blocks


def _configured_feature_names(config: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(feature for values in _configured_feature_blocks(config).values() for feature in values))


def _fundamental_asset_root(config: dict[str, Any], asset_root: Path) -> Path:
    fundamental = config.get("fundamentals")
    if not isinstance(fundamental, dict) or not str(fundamental.get("asset_id", "")).strip():
        raise ValueError("config.fundamentals.asset_id is required for R4B")
    return asset_root / "fundamentals" / str(fundamental["asset_id"])


def _additional_asset_hashes(config: dict[str, Any], asset_root: Path) -> dict[str, str]:
    if not config.get("fundamentals"):
        return {}
    manifest = _fundamental_asset_root(config, asset_root) / "collection_manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(f"fundamental collection manifest is missing: {manifest}")
    return {"fundamental_asset_manifest_sha256": _file_sha256(manifest)}


def _artifact_dir(run_root: Path, stage: str) -> Path:
    path = run_root / "artifacts" / stage
    path.mkdir(parents=True, exist_ok=True)
    return path


def _artifact_entry(path: Path, relative_root: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(relative_root)),
        "bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _read_feature_shards(run_root: Path, columns: list[str] | tuple[str, ...]):
    import pandas as pd

    paths = sorted((_artifact_dir(run_root, "build-r4a-features") / "shards").glob("shard=*/data.parquet"))
    if not paths:
        raise FileNotFoundError("R4A feature shards are missing")
    unique_columns = list(dict.fromkeys(columns))
    rows = pd.concat([pd.read_parquet(path, columns=unique_columns) for path in paths], ignore_index=True)
    model_dates_path = _artifact_dir(run_root, "build-r4a-features") / "model_dates.json"
    if not model_dates_path.is_file():
        raise FileNotFoundError("model date coverage contract is missing")
    model_dates = set(json.loads(model_dates_path.read_text(encoding="utf-8"))["dates"])
    return rows.loc[rows["trade_date"].isin(model_dates)].reset_index(drop=True)


def _dates_meeting_coverage(rows, features: tuple[str, ...], *, threshold: float) -> tuple[str, ...]:
    if not 0.0 < float(threshold) <= 1.0:
        raise ValueError("coverage threshold must be in (0, 1]")
    missing = sorted({"trade_date", *features} - set(rows.columns))
    if missing:
        raise ValueError("coverage rows missing columns: " + ", ".join(missing))
    coverage = rows.groupby("trade_date", sort=True)[list(features)].agg(lambda values: values.notna().mean())
    return tuple(str(value) for value in coverage.index[coverage.ge(float(threshold)).all(axis=1)])


def _bootstrap_decision_uplift(rows, *, iterations: int, block_length: int, seed: int) -> dict[str, Any]:
    import numpy as np

    from app.evaluation.full_market_ml.decision_policy import evaluate_policy_metrics

    dates = tuple(sorted(rows["trade_date"].unique()))
    daily = {}
    for trade_date, current in rows.groupby("trade_date", sort=False):
        model = evaluate_policy_metrics(current, score_col="policy_score", eligible_col="risk_eligible")
        baseline = evaluate_policy_metrics(current, score_col="amount_log")
        daily[str(trade_date)] = {
            "precision": model["precision_at_5"] - baseline["precision_at_5"],
            "return": model["top5_mean_return"] - baseline["top5_mean_return"],
        }
    rng = np.random.default_rng(seed)
    precision, returns = [], []
    for _ in range(max(1, int(iterations))):
        sampled = []
        while len(sampled) < len(dates):
            start = int(rng.integers(0, len(dates)))
            sampled.extend(dates[(start + offset) % len(dates)] for offset in range(max(1, block_length)))
        sampled = sampled[: len(dates)]
        precision.append(float(np.mean([daily[date]["precision"] for date in sampled])))
        returns.append(float(np.mean([daily[date]["return"] for date in sampled])))
    return {
        "method": "circular_block",
        "iterations": len(precision),
        "block_length": int(block_length),
        "precision_at_5_uplift": float(np.mean(precision)),
        "precision_at_5_uplift_ci_low": float(np.quantile(precision, 0.025)),
        "precision_at_5_uplift_ci_high": float(np.quantile(precision, 0.975)),
        "top5_mean_return_uplift": float(np.mean(returns)),
        "top5_mean_return_uplift_ci_low": float(np.quantile(returns, 0.025)),
        "top5_mean_return_uplift_ci_high": float(np.quantile(returns, 0.975)),
    }


def _portfolio_ready_rows(rows):
    result = rows.copy()
    if "policy_eligible" not in result:
        raise ValueError("policy_eligible is required before portfolio evaluation")
    result.loc[~result["policy_eligible"].eq(True), "policy_score"] = float("nan")
    return result


def _calibration_report(rows) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    valid = rows[["success_probability", "label_actionable_positive_10d"]].dropna().copy()
    if valid.empty:
        return {"ece": 1.0, "brier": 1.0, "prevalence_brier": 0.0, "bin_hit_rates_non_decreasing": False, "bins": []}
    probability = pd.to_numeric(valid["success_probability"], errors="coerce").clip(0, 1)
    outcome = valid["label_actionable_positive_10d"].astype(int)
    ordered = pd.DataFrame({"probability": probability, "outcome": outcome}).sort_values("probability", kind="stable")
    groups = [ordered.iloc[indexes] for indexes in np.array_split(np.arange(len(ordered)), min(10, len(ordered))) if len(indexes)]
    bins = [
        {
            "bin": index + 1,
            "count": len(group),
            "mean_probability": float(group["probability"].mean()),
            "hit_rate": float(group["outcome"].mean()),
        }
        for index, group in enumerate(groups)
    ]
    ece = float(sum(abs(row["mean_probability"] - row["hit_rate"]) * row["count"] for row in bins) / len(ordered))
    prevalence = float(outcome.mean())
    hit_rates = [row["hit_rate"] for row in bins]
    return {
        "ece": ece,
        "brier": float(np.mean((probability - outcome) ** 2)),
        "prevalence_brier": float(np.mean((prevalence - outcome) ** 2)),
        "bin_hit_rates_non_decreasing": all(right + 1e-12 >= left for left, right in zip(hit_rates, hit_rates[1:])),
        "bins": bins,
    }


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
    return float((centre - margin) / denominator)


def _error_samples(rows):
    import pandas as pd

    ranked = rows.sort_values(["trade_date", "policy_score", "symbol"], ascending=[True, False, True], kind="stable")
    ranked["rank"] = ranked.groupby("trade_date", sort=False).cumcount() + 1
    false_positive = ranked.loc[ranked["rank"].le(10) & ranked["label_severe_negative_10d_v2"].eq(True)].copy()
    missed = ranked.loc[ranked["rank"].gt(10) & ranked["label_actionable_positive_10d"].eq(True)].copy()
    false_positive["error_type"] = "top10_severe_negative"
    missed["error_type"] = "actionable_ranked_below_10"
    columns = [
        "trade_date", "symbol", "rank", "policy_score", "success_probability", "severe_probability",
        "target_clipped_return_10d", "error_type",
    ]
    return pd.concat([false_positive[columns], missed[columns]], ignore_index=True).head(5000)


def _artifact_hashes(artifacts: Mapping[str, Any]) -> dict[str, str]:
    hashes = {}
    for name, value in artifacts.items():
        if isinstance(value, str) and Path(value).is_file():
            hashes[name] = _file_sha256(Path(value))
    return hashes


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _research_code_sha256() -> str:
    """Hash the executable research pipeline, including uncommitted source edits."""
    backend_root = Path(__file__).resolve().parents[1]
    source_paths = [Path(__file__).resolve()]
    source_paths.extend(
        sorted((backend_root / "app" / "evaluation" / "full_market_ml").rglob("*.py"))
    )
    digest = hashlib.sha256()
    for path in sorted(set(source_paths)):
        relative = path.relative_to(backend_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _json_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=True, indent=2, sort_keys=True, default=str)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _elapsed(started_at: str, ended_at: str | None) -> float | None:
    if not ended_at:
        return None
    return max(0.0, (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = DecisionExperimentRunner(args.config, args.asset_root, args.run_root)
    state = runner.run(args.stage, resume=args.resume)
    print(json.dumps(state, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
