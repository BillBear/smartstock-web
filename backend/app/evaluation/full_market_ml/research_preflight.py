"""Adversarial, measured preflight for full-market ranking research."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .research_contract import RankingResearchContract


def evaluate_research_preflight(
    evidence: Mapping[str, Any],
    *,
    expected_contract_sha: str,
    phase: str,
) -> dict[str, Any]:
    """Evaluate raw evidence without trusting upstream pass/fail summaries."""
    if phase not in {"contract", "model"}:
        raise ValueError("preflight phase must be contract or model")
    decisions: dict[str, dict[str, Any]] = {}
    contract_hashes = [str(value) for value in evidence.get("contract_hashes", ())]
    data = dict(evidence.get("data", {}))
    data_failures = []
    if not contract_hashes or any(value != expected_contract_sha for value in contract_hashes):
        data_failures.append("stale_or_mixed_contract_hash")
    if not data.get("ready", False):
        data_failures.append("dataset_not_ready")
    if float(data.get("minimum_coverage_ratio", 0.0)) < 0.95:
        data_failures.append("historical_coverage_below_0_95")
    if int(data.get("minimum_daily_symbols", 0)) < 4500:
        data_failures.append("daily_universe_below_4500")
    if int(data.get("duplicate_key_count", 1)) != 0:
        data_failures.append("duplicate_date_symbol_keys")
    if int(data.get("invalid_adjusted_price_count", 1)) != 0:
        data_failures.append("invalid_adjusted_prices")
    decisions["data"] = _decision(data, data_failures)

    if phase == "contract":
        for section in ("labels", "features", "splits", "baselines", "evaluation"):
            decisions[section] = {
                "decision": "not_evaluated",
                "failed_gates": [],
                "measured": dict(evidence.get(section, {})),
            }
        return _report(phase, expected_contract_sha, decisions, model_ready=False)

    labels = dict(evidence.get("labels", {}))
    label_failures = []
    if not labels.get("passed", False):
        label_failures.append("objective_audit_failed")
    if int(labels.get("audited_date_count", 0)) < 30:
        label_failures.append("audited_dates_below_30")
    if not (
        0.08 <= float(labels.get("alpha_top10_prevalence_min", -1.0))
        and float(labels.get("alpha_top10_prevalence_max", 2.0)) <= 0.105
    ):
        label_failures.append("prevalence_outside_registered_band")
    if float(labels.get("alpha_top10_prevalence_std", 1.0)) > 0.01:
        label_failures.append("prevalence_is_unstable")
    correlation = labels.get("alpha_top10_market_return_correlation")
    if correlation is not None and abs(float(correlation)) >= 0.20:
        label_failures.append("prevalence_correlates_with_market")
    decisions["labels"] = _decision(labels, label_failures)

    features = dict(evidence.get("features", {}))
    feature_failures = []
    if not features.get("passed", False):
        feature_failures.append("feature_evidence_failed")
    if not features.get("point_in_time_verified", False):
        feature_failures.append("point_in_time_provenance_unverified")
    if float(features.get("maximum_core_missing_ratio", 1.0)) > 0.05:
        feature_failures.append("core_feature_missing_ratio_above_0_05")
    accepted = []
    for item in evidence.get("ablation", {}).get("decisions", ()):
        if item.get("status") != "accepted_alpha":
            continue
        accepted.append(str(item.get("name", "unknown")))
        uplift = item.get("aggregate_oof_uplift", {})
        if any(
            float(uplift.get(metric, 0.0)) <= 0.0
            for metric in ("precision_at_5_uplift", "ndcg_at_10_uplift", "top5_return_uplift")
        ):
            feature_failures.append(
                f"accepted_block_has_nonpositive_oof_uplift:{item.get('name', 'unknown')}"
            )
        interval = item.get("precision_bootstrap_ci", [0.0, 0.0])
        if len(interval) != 2 or float(interval[0]) <= 0.0:
            feature_failures.append(
                f"accepted_block_precision_ci_not_positive:{item.get('name', 'unknown')}"
            )
        if sum(bool(value) for value in item.get("inner_selected_folds", ())) < 4:
            feature_failures.append(
                f"accepted_block_selected_in_fewer_than_4_folds:{item.get('name', 'unknown')}"
            )
    if not accepted:
        feature_failures.append("no_accepted_alpha_feature_block")
    features["accepted_alpha_blocks"] = accepted
    decisions["features"] = _decision(features, feature_failures)

    splits = dict(evidence.get("splits", {}))
    split_failures = []
    if int(splits.get("outer_fold_count", 0)) != 5:
        split_failures.append("outer_fold_count_not_5")
    if int(splits.get("minimum_fit_dates", 0)) < 60:
        split_failures.append("inner_fit_dates_below_60")
    if int(splits.get("minimum_early_stop_dates", 0)) < 20:
        split_failures.append("inner_early_stop_dates_below_20")
    if int(splits.get("minimum_selection_dates", 0)) < 20:
        split_failures.append("inner_selection_dates_below_20")
    if not splits.get("roles_disjoint", False):
        split_failures.append("date_roles_not_disjoint")
    if not splits.get("roles_chronological", False):
        split_failures.append("date_roles_not_chronological")
    decisions["splits"] = _decision(splits, split_failures)

    baselines = dict(evidence.get("baselines", {}))
    baseline_failures = []
    if not baselines.get("definitions_exact", False):
        baseline_failures.append("definitions_not_exact")
    if not baselines.get("identical_rows", False):
        baseline_failures.append("comparison_rows_differ")
    if int(baselines.get("row_count", 0)) <= 0:
        baseline_failures.append("predictions_are_empty")
    decisions["baselines"] = _decision(baselines, baseline_failures)

    evaluation = dict(evidence.get("evaluation", {}))
    evaluation_failures = []
    if not evaluation.get("identical_rows", False):
        evaluation_failures.append("comparison_rows_differ")
    if not evaluation.get("identical_risk_mask", False):
        evaluation_failures.append("risk_masks_differ")
    decisions["evaluation"] = _decision(evaluation, evaluation_failures)
    return _report(phase, expected_contract_sha, decisions, model_ready=True)


def collect_research_evidence(
    contract: RankingResearchContract,
    run_root: Path,
    asset_root: Path,
    *,
    phase: str = "model",
) -> dict[str, Any]:
    """Load raw measured values from immutable stage artifacts."""
    artifacts = run_root / "artifacts"
    dataset_root = asset_root / "datasets" / contract.dataset_id / "artifacts" / "full-build"
    quality = _read_json(dataset_root / "quality_report_v3.json")
    if phase == "contract":
        universe_counts = quality.get("per_date_universe_count", {})
        return {
            "contract_hashes": [contract.sha256()],
            "data": {
                "ready": bool(quality.get("ready", False)),
                "minimum_coverage_ratio": float(quality.get("required_date_coverage", 0.0)),
                "minimum_daily_symbols": min(
                    (int(value) for value in universe_counts.values()), default=0
                ),
                "duplicate_key_count": int(quality.get("duplicate_key_count", -1)),
                "invalid_adjusted_price_count": max(
                    0,
                    int(quality.get("row_count", 0))
                    - int(quality.get("raw_valid_row_count", 0)),
                ),
                "date_count": len(universe_counts),
                "source": "immutable_dataset_quality_report",
            },
        }
    if phase != "model":
        raise ValueError("preflight phase must be contract or model")
    sample = _read_json(artifacts / "sample_audit.json")
    label = _read_json(artifacts / "label-audit" / "label_objective_report.json")
    feature = _read_json(artifacts / "feature-evidence" / "feature_evidence_report.json")
    feature_manifest = _read_json(
        artifacts / "feature-evidence" / "feature_matrix_manifest.json"
    )
    split = _read_json(artifacts / "feature-evidence" / "development_split.json")
    baseline = _read_json(artifacts / "baseline-oof" / "baseline_report.json")
    ablation = _read_json(artifacts / "nested-ablation" / "block_decisions.json")
    controlled_path = artifacts / "controlled-evaluation" / "controlled_report.json"
    controlled = _read_json(controlled_path) if controlled_path.is_file() else {}
    feature_csv = pd.read_csv(artifacts / "feature-evidence" / "feature_evidence.csv")
    summaries = feature_csv.loc[feature_csv["record_type"].eq("summary")].copy()
    moneyflow = set(dict(contract.feature_blocks).get("moneyflow", ()))
    core = summaries.loc[~summaries["feature"].isin(moneyflow)]
    forbidden_feature_names = sorted(
        name
        for name in feature_manifest.get("feature_names", ())
        if str(name).startswith(("future_", "label_", "alpha_target", "mfe_", "mae_", "tp_", "sl_"))
    )
    daily = sample.get("daily", ())
    label_daily = label.get("daily", ())
    inner_counts = []
    roles_disjoint = True
    roles_chronological = True
    for fold in split.get("walk_forward", ()):
        training = tuple(sorted(set(str(value) for value in fold.get("training_dates", ()))))
        validation = tuple(sorted(set(str(value) for value in fold.get("validation_dates", ()))))
        fit_count = len(training) - contract.minimum_inner_early_stop_dates - contract.minimum_inner_selection_dates
        inner_counts.append((fit_count, contract.minimum_inner_early_stop_dates, contract.minimum_inner_selection_dates))
        roles_disjoint &= not bool(set(training) & set(validation))
        roles_chronological &= bool(training and validation and max(training) < min(validation))
    expected_definitions = dict(contract.baseline_definitions)
    baseline_predictions = artifacts / "baseline-oof" / "baseline_predictions.parquet"
    score_columns = [f"score__{name}" for name in contract.required_baselines]
    baseline_keys = pd.read_parquet(
        baseline_predictions, columns=["trade_date", "symbol", "fold", "quadrant", *score_columns]
    )
    baseline_row_count = int(len(baseline_keys))
    comparison_keys = ["trade_date", "symbol", "fold", "quadrant"]
    scores_share_rows = bool(
        not baseline_keys.duplicated(comparison_keys).any()
        and baseline_keys[score_columns].notna().all().all()
    )
    risk_predictions = artifacts / "risk-oof" / "risk_predictions.parquet"
    risk_keys = (
        pd.read_parquet(risk_predictions, columns=[*comparison_keys, "risk_eligible"])
        if risk_predictions.is_file()
        else pd.DataFrame()
    )
    baseline_key_rows = baseline_keys[comparison_keys].sort_values(comparison_keys, kind="stable").reset_index(drop=True)
    risk_key_rows = (
        risk_keys[comparison_keys].sort_values(comparison_keys, kind="stable").reset_index(drop=True)
        if not risk_keys.empty
        else pd.DataFrame()
    )
    evaluation_rows_identical = bool(
        not risk_keys.empty
        and not risk_keys.duplicated(comparison_keys).any()
        and baseline_key_rows.equals(risk_key_rows)
    )
    evaluation_risk_mask_complete = bool(
        evaluation_rows_identical and risk_keys["risk_eligible"].notna().all()
    )
    contract_hashes = [
        value
        for value in (
            label.get("contract_sha256"),
            feature.get("contract_sha256"),
            baseline.get("contract_sha256"),
            ablation.get("contract_sha256"),
            controlled.get("contract_sha256") if controlled else contract.sha256(),
            contract.sha256(),
        )
        if value
    ]
    return {
        "contract_hashes": contract_hashes,
        "data": {
            "ready": bool(sample.get("ready", False) and quality.get("ready", False)),
            "minimum_coverage_ratio": min((float(item.get("coverage_ratio", 0.0)) for item in daily), default=0.0),
            "minimum_daily_symbols": min((int(item.get("valid_count", 0)) for item in daily), default=0),
            "duplicate_key_count": int(quality.get("duplicate_key_count", -1)),
            "invalid_adjusted_price_count": max(
                0,
                int(quality.get("row_count", 0))
                - int(quality.get("raw_valid_row_count", 0)),
            ),
            "date_count": int(sample.get("date_count", 0)),
            "blocking_codes": list(sample.get("blocking_codes", ())),
        },
        "labels": {
            "passed": bool(label.get("passed", False)),
            "audited_date_count": int(label.get("audited_date_count", 0)),
            "alpha_top10_prevalence_min": min((float(item["alpha_top10_prevalence"]) for item in label_daily), default=-1.0),
            "alpha_top10_prevalence_max": max((float(item["alpha_top10_prevalence"]) for item in label_daily), default=2.0),
            "alpha_top10_prevalence_std": label.get("alpha_top10_prevalence_std"),
            "alpha_top10_market_return_correlation": label.get("alpha_top10_market_return_correlation"),
        },
        "features": {
            "passed": bool(feature.get("passed", False)),
            "point_in_time_verified": bool(
                feature_manifest.get("contract_sha256") == contract.sha256()
                and not forbidden_feature_names
            ),
            "forbidden_future_feature_names": forbidden_feature_names,
            "maximum_core_missing_ratio": float(1.0 - core["coverage"].min()) if not core.empty else 1.0,
            "feature_count": int(feature.get("feature_count", 0)),
        },
        "splits": {
            "outer_fold_count": len(split.get("walk_forward", ())),
            "roles_disjoint": roles_disjoint,
            "roles_chronological": roles_chronological,
            "minimum_fit_dates": min((value[0] for value in inner_counts), default=0),
            "minimum_early_stop_dates": min((value[1] for value in inner_counts), default=0),
            "minimum_selection_dates": min((value[2] for value in inner_counts), default=0),
            "split_sha256": split.get("split_sha256"),
        },
        "baselines": {
            "definitions_exact": baseline.get("definitions") == expected_definitions,
            "identical_rows": bool(
                scores_share_rows
                and baseline_row_count == int(baseline.get("row_count", baseline_row_count))
            ),
            "row_count": baseline_row_count,
        },
        "ablation": {"decisions": list(ablation.get("decisions", ()))},
        "evaluation": {
            "identical_rows": evaluation_rows_identical,
            "identical_risk_mask": evaluation_risk_mask_complete,
            "comparison_key_sha256": controlled.get("comparison_key_sha256"),
        },
    }


def _decision(measured: Mapping[str, Any], failures: list[str]) -> dict[str, Any]:
    return {
        "decision": "fail" if failures else "pass",
        "failed_gates": sorted(set(failures)),
        "measured": dict(measured),
    }


def _report(
    phase: str,
    expected_contract_sha: str,
    decisions: Mapping[str, Mapping[str, Any]],
    *,
    model_ready: bool,
) -> dict[str, Any]:
    failed = [
        f"{section}:{gate}"
        for section, decision in decisions.items()
        for gate in decision.get("failed_gates", ())
    ]
    passed = not failed
    return {
        "phase": phase,
        "contract_sha256": expected_contract_sha,
        "passed": passed,
        "model_ready": bool(passed and model_ready),
        "failed_gates": sorted(failed),
        "decisions": dict(decisions),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"research preflight artifact is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"research preflight artifact must be an object: {path}")
    return value
