"""One pre-registered development-only recovery feature hypothesis.

This module is deliberately separate from production services and accepts only
the sealed R1 development rows assembled by ``ml_recovery_acceptance``.  It
does not read prospective data, choose features, or publish a fitted model.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd
from sklearn.linear_model import LogisticRegression

from app.evaluation.ml_recovery_acceptance import (
    MLRecoveryAcceptanceError,
    _evaluate_daily_rankings,
    _write_daily_metrics,
    _write_json,
    _write_parquet,
    _write_progress,
    build_recovery_dataset,
    verify_recovery_inputs,
)


H1_HYPOTHESIS_ID = "H1_momentum_trend_quality_v1"
H1_FEATURES = ("adjusted_return_60d", "price_to_sma_20d")
H1_MODEL_PARAMETERS = MappingProxyType(
    {
        "C": 0.1,
        "solver": "lbfgs",
        "max_iter": 200,
        "class_weight": "balanced",
        "random_state": 20_260_728,
    }
)
_REQUIRED_ROW_COLUMNS = {
    "trade_date",
    "symbol",
    "risk_eligible",
    "alpha_top10_10d",
    "net_return_after_cost_10d",
    "severe_negative_10d",
    *(f"rank__{feature}" for feature in H1_FEATURES),
}
_GATE_METRICS = (
    "ndcg_at_10",
    "precision_at_5",
    "top_5_mean_net_return",
    "severe_negative_rate",
)


def run_h1_momentum_trend_oof(rows: pd.DataFrame, split_plan: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit the H1 contract on A history and score later A/C development rows."""
    _require_h1_rows(rows)
    predictions: list[pd.DataFrame] = []
    coefficients: list[dict[str, Any]] = []
    fold_metrics: dict[str, Any] = {}
    fit_symbols_by_fold: dict[str, list[str]] = {}
    ranked_features = tuple(f"rank__{feature}" for feature in H1_FEATURES)

    for fold in split_plan.get("walk_forward", ()):
        fold_number = int(fold["fold"])
        training_dates = tuple(str(value) for value in fold["training_dates"])
        validation_dates = tuple(str(value) for value in fold["validation_dates"])
        training_symbols = tuple(str(value) for value in fold["training_symbols"])
        if not training_dates or not validation_dates or max(training_dates) >= min(validation_dates):
            raise MLRecoveryAcceptanceError(f"H1 fold {fold_number} training dates are not strictly before validation dates")
        train = rows.loc[
            rows["trade_date"].isin(training_dates)
            & rows["symbol"].isin(training_symbols)
            & rows["risk_eligible"].eq(True)
        ].copy()
        if train.empty or train["alpha_top10_10d"].nunique() != 2:
            raise MLRecoveryAcceptanceError(f"H1 fold {fold_number} has no two-class A training data")
        model = LogisticRegression(**H1_MODEL_PARAMETERS)
        model.fit(train.loc[:, ranked_features], train["alpha_top10_10d"].astype(int))
        fit_symbols_by_fold[str(fold_number)] = sorted(set(train["symbol"]))
        coefficients.extend(
            {
                "fold": fold_number,
                "feature": feature,
                "coefficient": float(coefficient),
            }
            for feature, coefficient in zip(H1_FEATURES, model.coef_[0], strict=True)
        )
        for quadrant, symbols in (
            ("A", tuple(split_plan["A_dev_train_symbols"])),
            ("C", tuple(split_plan["C_dev_unseen_symbols"])),
        ):
            validation = rows.loc[
                rows["trade_date"].isin(validation_dates)
                & rows["symbol"].isin(symbols)
                & rows["risk_eligible"].eq(True)
            ].copy()
            if validation.empty:
                raise MLRecoveryAcceptanceError(f"H1 fold {fold_number} {quadrant} has no eligible validation rows")
            validation["model_score"] = model.decision_function(validation.loc[:, ranked_features])
            validation["baseline_score"] = validation["rank__adjusted_return_60d"]
            validation["fold"] = fold_number
            validation["quadrant"] = quadrant
            validation["train_max_date"] = max(training_dates)
            fold_metrics[f"fold_{fold_number}_{quadrant}"] = {
                "fold": fold_number,
                "quadrant": quadrant,
                "row_count": int(len(validation)),
                "date_count": int(validation["trade_date"].nunique()),
                "model": _evaluate_daily_rankings(validation, "model_score"),
                "baseline": _evaluate_daily_rankings(validation, "baseline_score"),
            }
            predictions.append(validation)

    if not predictions:
        raise MLRecoveryAcceptanceError("H1 split has no walk-forward folds")
    prediction_rows = pd.concat(predictions, ignore_index=True).sort_values(
        ["fold", "quadrant", "trade_date", "symbol"], kind="stable"
    ).reset_index(drop=True)
    return prediction_rows, {
        "hypothesis_id": H1_HYPOTHESIS_ID,
        "feature_contract": list(H1_FEATURES),
        "model_parameters": dict(H1_MODEL_PARAMETERS),
        "fit_symbols_by_fold": fit_symbols_by_fold,
        "coefficients": coefficients,
        "fold_metrics": fold_metrics,
        "candidate_screen": screen_h1_candidate(fold_metrics),
        "production_integration_allowed": False,
    }


def screen_h1_candidate(fold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Apply H1's pre-registered non-degradation gate to all A/C folds."""
    grouped: dict[str, list[Mapping[str, Any]]] = {"A": [], "C": []}
    for metric in fold_metrics.values():
        quadrant = str(metric.get("quadrant", ""))
        if quadrant in grouped:
            grouped[quadrant].append(metric)
    support: dict[str, dict[str, int]] = {}
    for quadrant, metrics in grouped.items():
        support[quadrant] = {
            "ndcg_at_10_non_decreasing": _support_count(metrics, "ndcg_at_10", higher_is_better=True),
            "precision_at_5_non_decreasing": _support_count(metrics, "precision_at_5", higher_is_better=True),
            "top_5_mean_net_return_non_decreasing": _support_count(
                metrics, "top_5_mean_net_return", higher_is_better=True
            ),
            "severe_negative_rate_non_increasing": _support_count(
                metrics, "severe_negative_rate", higher_is_better=False
            ),
        }
    complete = all(len(grouped[quadrant]) == 5 for quadrant in grouped)
    passed = complete and all(
        count >= 4
        for quadrant in ("A", "C")
        for count in support[quadrant].values()
    )
    return {
        "status": "development_candidate_for_future_holdout" if passed else "development_research_failed_gate",
        "passed": bool(passed),
        "required_fold_count": 4,
        "evaluated_fold_counts": {quadrant: len(metrics) for quadrant, metrics in grouped.items()},
        "support": support,
        "candidate_freeze_allowed": bool(passed),
        "production_integration_allowed": False,
    }


def run_h1_momentum_trend_experiment(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    panel_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
) -> dict[str, Any]:
    """Atomically publish a local, development-only H1 research run."""
    destination = Path(output_dir).expanduser().resolve()
    if "prospective-lockbox" in destination.parts:
        raise MLRecoveryAcceptanceError("H1 outputs must not be written inside the prospective lockbox")
    if destination.exists():
        raise FileExistsError(f"H1 output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete H1 run requires inspection: {temporary}")
    temporary.mkdir()
    try:
        _write_progress(temporary, "data-verify", status="running", hypothesis_id=H1_HYPOTHESIS_ID)
        inputs = verify_recovery_inputs(label_root, feature_asset_root, panel_root)
        input_manifest = {**inputs["input_manifest"], "code_commit": str(code_commit)}
        _write_json(temporary / "input_manifest.json", input_manifest)
        _write_json(temporary / "hypothesis_contract.json", _h1_contract())

        _write_progress(temporary, "build-common-mask", status="running", hypothesis_id=H1_HYPOTHESIS_ID)
        rows, mask_report = build_recovery_dataset(inputs)
        _write_json(temporary / "common_mask_report.json", mask_report)
        _write_json(temporary / "data_quality_report.json", _h1_data_quality_report(rows, mask_report))

        _write_progress(
            temporary,
            "h1-oof",
            status="running",
            hypothesis_id=H1_HYPOTHESIS_ID,
            eligible_row_count=int(len(rows)),
        )
        predictions, oof_report = run_h1_momentum_trend_oof(rows, inputs["split_plan"])
        _write_parquet(temporary / "oof_predictions.parquet", predictions)
        _write_json(temporary / "fold_metrics.json", oof_report["fold_metrics"])
        _write_daily_metrics(predictions, temporary / "daily_metrics.csv")
        pd.DataFrame(oof_report["coefficients"]).to_csv(temporary / "coefficients.csv", index=False)
        _write_json(temporary / "candidate_screen.json", oof_report["candidate_screen"])

        report = {
            "status": "complete",
            "research_only": True,
            "production_integration_allowed": False,
            "model_role": "development_only_h1_momentum_trend_quality",
            "model_serialized": False,
            "hypothesis_id": H1_HYPOTHESIS_ID,
            "code_commit": str(code_commit),
            "input_manifest": input_manifest,
            "feature_contract": list(H1_FEATURES),
            "model_parameters": dict(H1_MODEL_PARAMETERS),
            "eligible_row_count": int(len(rows)),
            "eligible_symbol_count": int(rows["symbol"].nunique()),
            "eligible_trade_date_count": int(rows["trade_date"].nunique()),
            "candidate_screen": oof_report["candidate_screen"],
            "limitations": [
                "Only sealed R1 development A/C folds were read; no prospective labels were opened.",
                "H1 is one pre-registered development hypothesis, not a production model selection.",
                "The decision score is uncalibrated and cannot be rendered as a probability or trading instruction.",
            ],
        }
        _write_json(temporary / "ml_recovery_h1_momentum_trend.json", report)
        _write_progress(
            temporary,
            "complete",
            status="complete",
            hypothesis_id=H1_HYPOTHESIS_ID,
            eligible_row_count=int(len(rows)),
        )
        os.replace(temporary, destination)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            status="failed",
            hypothesis_id=H1_HYPOTHESIS_ID,
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _support_count(metrics: list[Mapping[str, Any]], key: str, *, higher_is_better: bool) -> int:
    return sum(
        float(metric["model"][key]) >= float(metric["baseline"][key])
        if higher_is_better
        else float(metric["model"][key]) <= float(metric["baseline"][key])
        for metric in metrics
    )


def _h1_contract() -> dict[str, Any]:
    return {
        "hypothesis_id": H1_HYPOTHESIS_ID,
        "features": list(H1_FEATURES),
        "model_parameters": dict(H1_MODEL_PARAMETERS),
        "target": "alpha_top10_10d",
        "baseline": "rank__adjusted_return_60d",
        "research_only": True,
        "production_integration_allowed": False,
    }


def _h1_data_quality_report(rows: pd.DataFrame, mask_report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "eligible_row_count": int(len(rows)),
        "eligible_symbol_count": int(rows["symbol"].nunique()),
        "eligible_trade_date_count": int(rows["trade_date"].nunique()),
        "h1_feature_coverage": {feature: float(rows[feature].notna().mean()) for feature in H1_FEATURES},
        "common_mask_report": dict(mask_report),
        "research_only": True,
        "production_integration_allowed": False,
    }


def _require_h1_rows(rows: pd.DataFrame) -> None:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("H1 rows must be a pandas DataFrame")
    missing = sorted(_REQUIRED_ROW_COLUMNS - set(rows.columns))
    if missing:
        raise MLRecoveryAcceptanceError("H1 rows miss required fields: " + ", ".join(missing))
    if rows.duplicated(["trade_date", "symbol"]).any():
        raise MLRecoveryAcceptanceError("H1 rows have duplicate trade_date and symbol keys")
