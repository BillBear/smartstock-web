"""Immutable-input acceptance gate for one offline SH/SZ ML baseline.

This module is deliberately independent of production ML services.  It starts
by proving that the local research assets describe the same sealed SH/SZ
development-only study; later stages may consume its returned binding but may
not relax it.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.linear_model import LogisticRegression


UNIVERSE_ID = "shsz_a_share_v1"
ALLOWED_EXCHANGES = ("SH", "SZ")
FIXED_FEATURES = (
    "adjusted_return_20d",
    "adjusted_return_60d",
    "price_to_sma_20d",
    "amount_log_rank",
    "turnover_rate_rank",
)
_REQUIRED_LABEL_COLUMNS = (
    "trade_date",
    "symbol",
    "eligible_for_training",
    "entry_tradeable",
    "horizon_available_10d",
    "path_ambiguous_10d",
    "alpha_top10_10d",
    "alpha_target_10d",
    "net_return_after_cost_10d",
    "severe_negative_10d",
)
_FORBIDDEN_FEATURE_TOKENS = ("future", "label", "exit", "entry_price", "target", "tp_", "sl_")


class MLRecoveryAcceptanceError(ValueError):
    """Raised when a local asset cannot support the sealed recovery study."""


def verify_recovery_inputs(
    label_root: str | Path,
    feature_asset_root: str | Path,
    panel_root: str | Path,
) -> dict[str, Any]:
    """Bind R1, R2 and the certified panel before loading a research row."""
    labels_root = Path(label_root).expanduser().resolve()
    features_root = Path(feature_asset_root).expanduser().resolve()
    certified_panel_root = Path(panel_root).expanduser().resolve()
    registry_path = labels_root / "dataset_registry.json"
    split_path = labels_root / "development_split_plan.json"
    label_manifest_path = labels_root / "label_split_manifest.json"
    feature_manifest_path = features_root / "feature_asset_manifest.json"
    panel_manifest_path = certified_panel_root / "panel_rebuild_manifest.json"

    registry = _read_json(registry_path, "R1 label registry")
    split = _read_json(split_path, "R1 development split")
    label_manifest = _read_json(label_manifest_path, "R1 label manifest")
    feature_manifest = _read_json(feature_manifest_path, "R2 feature manifest")
    panel_manifest = _read_json(panel_manifest_path, "certified panel manifest")
    _require_r1_research_only(registry, label_manifest)
    _require_r2_research_only(feature_manifest)
    _require_panel_research_only(panel_manifest)
    _verify_payload_hash(feature_manifest, "R2 feature manifest")

    panel_sha = _sha256_file(panel_manifest_path)
    if panel_sha != str(registry.get("source_panel_manifest_sha256", "")):
        raise MLRecoveryAcceptanceError("panel manifest SHA256 does not match R1 registration")
    if panel_sha != str(feature_manifest.get("panel_manifest_sha256", "")):
        raise MLRecoveryAcceptanceError("panel manifest SHA256 does not match R2 registration")
    if _sha256_file(registry_path) != str(feature_manifest.get("label_registry_sha256", "")):
        raise MLRecoveryAcceptanceError("R2 label registry SHA256 does not match R1")
    if _sha256_file(split_path) != str(feature_manifest.get("label_split_sha256", "")):
        raise MLRecoveryAcceptanceError("R2 development split SHA256 does not match R1")

    split_plan = _parse_sealed_development_split(split)
    _verify_registered_parquet_files(labels_root, registry.get("label_files"), "R1 label")
    _verify_registered_parquet_files(features_root, feature_manifest.get("matrix_files"), "R2 matrix")
    return {
        "labels_root": labels_root,
        "features_root": features_root,
        "panel_root": certified_panel_root,
        "registry": registry,
        "label_manifest": label_manifest,
        "feature_manifest": feature_manifest,
        "panel_manifest": panel_manifest,
        "split_plan": split_plan,
        "input_manifest": {
            "universe_id": UNIVERSE_ID,
            "allowed_exchanges": list(ALLOWED_EXCHANGES),
            "label_registry_sha256": _sha256_file(registry_path),
            "label_split_sha256": _sha256_file(split_path),
            "label_split_manifest_sha256": _sha256_file(label_manifest_path),
            "feature_asset_manifest_sha256": _sha256_file(feature_manifest_path),
            "feature_asset_payload_sha256": str(feature_manifest.get("sha256", "")),
            "panel_rebuild_manifest_sha256": panel_sha,
            "formal_future_holdout_status": "awaiting_model_freeze_and_future_labels",
            "production_integration_allowed": False,
        },
    }


def validate_fixed_features(features: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Reject a feature contract that could carry an outcome or execution label."""
    normalized = tuple(str(feature).strip() for feature in features)
    if not normalized or len(set(normalized)) != len(normalized) or any(not feature for feature in normalized):
        raise MLRecoveryAcceptanceError("fixed feature contract must contain unique non-empty fields")
    unsafe = [
        feature
        for feature in normalized
        if any(token in feature.lower() for token in _FORBIDDEN_FEATURE_TOKENS)
    ]
    if unsafe:
        raise MLRecoveryAcceptanceError("fixed feature contract contains future or label field: " + ", ".join(unsafe))
    return normalized


def build_recovery_dataset(inputs: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load only registered R1 development rows and matching R2 feature files."""
    features = validate_fixed_features(FIXED_FEATURES)
    feature_contract = inputs["feature_manifest"].get("feature_contract", {})
    available = {
        str(item.get("name"))
        for item in feature_contract.get("features", ())
        if isinstance(item, Mapping) and item.get("name")
    }
    missing_contract = sorted(set(features) - available)
    if missing_contract:
        raise MLRecoveryAcceptanceError("R2 feature contract misses fixed features: " + ", ".join(missing_contract))
    label_frames = _read_registered_frames(
        Path(inputs["labels_root"]),
        inputs["registry"].get("label_files"),
        _REQUIRED_LABEL_COLUMNS,
        "R1 label",
    )
    labels = pd.concat(label_frames, ignore_index=True)
    development_dates = tuple(inputs["split_plan"]["development_dates"])
    if set(_normalize_date_series(labels["trade_date"], "R1 labels")) != set(development_dates):
        raise MLRecoveryAcceptanceError("R1 labels do not exactly cover registered development dates")
    by_date = {
        _normalize_date(entry.get("trade_date"), "R2 matrix manifest"): entry
        for entry in inputs["feature_manifest"].get("matrix_files", ())
        if isinstance(entry, Mapping)
    }
    missing_dates = sorted(set(development_dates) - set(by_date))
    if missing_dates:
        raise MLRecoveryAcceptanceError("R2 matrix misses development dates: " + ", ".join(missing_dates[:5]))
    matrix_frames = []
    for trade_date in development_dates:
        entry = by_date[trade_date]
        path = Path(inputs["features_root"]) / str(entry.get("path", ""))
        matrix_frames.extend(
            _read_registered_frames(
                Path(inputs["features_root"]),
                [entry],
                ("trade_date", "symbol", *features),
                "R2 matrix",
            )
        )
        if not path.is_file():
            raise MLRecoveryAcceptanceError(f"R2 matrix file is missing: {path}")
    matrix = pd.concat(matrix_frames, ignore_index=True)
    rows, report = build_recovery_rows(labels, matrix)
    return rows, {
        **report,
        "source_matrix_row_count": int(len(matrix)),
        "development_date_count": int(len(development_dates)),
        "source_label_file_count": int(len(label_frames)),
        "source_matrix_file_count": int(len(matrix_frames)),
    }


def build_recovery_rows(labels: pd.DataFrame, matrix: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Join labels to fixed same-date features and apply one common mask."""
    features = validate_fixed_features(FIXED_FEATURES)
    label_rows = _normalize_label_rows(labels)
    matrix_rows = _normalize_matrix_rows(matrix, features)
    joined = label_rows.merge(matrix_rows, on=["trade_date", "symbol"], how="left", validate="one_to_one", indicator=True)
    missing_matrix = joined["_merge"].ne("both")
    if missing_matrix.any():
        first = joined.loc[missing_matrix, ["trade_date", "symbol"]].iloc[0]
        raise MLRecoveryAcceptanceError(f"R2 matrix does not cover R1 label key: {first['trade_date']}/{first['symbol']}")
    joined = joined.drop(columns="_merge")
    numeric_features = joined.loc[:, features].apply(pd.to_numeric, errors="coerce")
    finite_features = pd.DataFrame(
        np.isfinite(numeric_features.to_numpy(dtype="float64")),
        index=joined.index,
        columns=features,
    )
    execution_eligible = (
        joined["eligible_for_training"].eq(True)
        & joined["entry_tradeable"].eq(True)
        & joined["horizon_available_10d"].eq(True)
        & joined["path_ambiguous_10d"].eq(False)
        & joined["alpha_top10_10d"].notna()
        & pd.to_numeric(joined["alpha_target_10d"], errors="coerce").notna()
    )
    feature_complete = finite_features.all(axis=1)
    result = joined.loc[execution_eligible & feature_complete].copy()
    for feature in features:
        result[feature] = pd.to_numeric(result[feature], errors="coerce")
        result[f"rank__{feature}"] = result.groupby("trade_date", sort=False)[feature].rank(method="average", pct=True)
    result["risk_eligible"] = True
    report = {
        "source_label_row_count": int(len(label_rows)),
        "joined_row_count": int(len(joined)),
        "eligible_row_count": int(len(result)),
        "excluded_execution_count": int((~execution_eligible).sum()),
        "excluded_missing_feature_count": int((execution_eligible & ~feature_complete).sum()),
        "fixed_features": list(features),
        "common_mask_contract": "model and adjusted_return_60d baseline use identical risk_eligible rows",
    }
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True), report


def audit_fixed_features(rows: pd.DataFrame, split_plan: Mapping[str, Any]) -> pd.DataFrame:
    """Report descriptive validation-only diagnostics without feature selection."""
    _require_recovery_rows(rows)
    diagnostics: list[dict[str, Any]] = []
    quadrants = {
        "A": tuple(split_plan["A_dev_train_symbols"]),
        "C": tuple(split_plan["C_dev_unseen_symbols"]),
    }
    for fold in split_plan["walk_forward"]:
        validation_dates = tuple(fold["validation_dates"])
        for quadrant, symbols in quadrants.items():
            current = rows.loc[
                rows["trade_date"].isin(validation_dates) & rows["symbol"].isin(symbols) & rows["risk_eligible"].eq(True)
            ].copy()
            if current.empty:
                raise MLRecoveryAcceptanceError(f"feature audit has no eligible rows for fold {fold['fold']} {quadrant}")
            for feature in FIXED_FEATURES:
                rank_column = f"rank__{feature}"
                daily_ic = current.groupby("trade_date", sort=True).apply(
                    lambda group: group[rank_column].corr(group["alpha_target_10d"], method="spearman"),
                    include_groups=False,
                )
                daily_top5_returns = []
                for _, date_rows in current.groupby("trade_date", sort=True):
                    selected = date_rows.sort_values([rank_column, "symbol"], ascending=[False, True], kind="stable").head(5)
                    daily_top5_returns.append(float(pd.to_numeric(selected["net_return_after_cost_10d"], errors="coerce").mean()))
                diagnostics.append(
                    {
                        "fold": int(fold["fold"]),
                        "quadrant": quadrant,
                        "feature": feature,
                        "row_count": int(len(current)),
                        "date_count": int(current["trade_date"].nunique()),
                        "coverage": float(current[feature].notna().mean()),
                        "mean_daily_spearman_ic": float(daily_ic.dropna().mean()) if daily_ic.notna().any() else float("nan"),
                        "mean_daily_top5_net_return": float(np.mean(daily_top5_returns)) if daily_top5_returns else float("nan"),
                    }
                )
    return pd.DataFrame(diagnostics).sort_values(["fold", "quadrant", "feature"], kind="stable").reset_index(drop=True)


def run_fixed_logistic_oof(rows: pd.DataFrame, split_plan: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit the one registered model on A history and score later A/C rows."""
    _require_oof_rows(rows)
    ranked_features = tuple(f"rank__{feature}" for feature in FIXED_FEATURES)
    predictions = []
    coefficients = []
    fold_metrics: dict[str, Any] = {}
    fit_symbols_by_fold: dict[str, list[str]] = {}
    for fold in split_plan["walk_forward"]:
        fold_number = int(fold["fold"])
        training_dates = tuple(fold["training_dates"])
        validation_dates = tuple(fold["validation_dates"])
        training_symbols = tuple(fold["training_symbols"])
        if max(training_dates) >= min(validation_dates):
            raise MLRecoveryAcceptanceError(f"fold {fold_number} training dates are not strictly before validation dates")
        train = rows.loc[
            rows["trade_date"].isin(training_dates)
            & rows["symbol"].isin(training_symbols)
            & rows["risk_eligible"].eq(True)
        ].copy()
        if train.empty or train["alpha_top10_10d"].nunique() != 2:
            raise MLRecoveryAcceptanceError(f"fold {fold_number} has no two-class A training data")
        model = LogisticRegression(
            C=0.1,
            solver="lbfgs",
            max_iter=200,
            class_weight="balanced",
            random_state=20_260_722,
        )
        model.fit(train.loc[:, ranked_features], train["alpha_top10_10d"].astype(int))
        fit_symbols_by_fold[str(fold_number)] = sorted(set(train["symbol"]))
        for feature, coefficient in zip(ranked_features, model.coef_[0], strict=True):
            coefficients.append({"fold": fold_number, "feature": feature.removeprefix("rank__"), "coefficient": float(coefficient)})
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
                raise MLRecoveryAcceptanceError(f"fold {fold_number} {quadrant} has no eligible validation rows")
            validation["model_score"] = model.decision_function(validation.loc[:, ranked_features])
            validation["baseline_score"] = validation["rank__adjusted_return_60d"]
            validation["fold"] = fold_number
            validation["quadrant"] = quadrant
            validation["train_max_date"] = max(training_dates)
            metric = {
                "fold": fold_number,
                "quadrant": quadrant,
                "row_count": int(len(validation)),
                "date_count": int(validation["trade_date"].nunique()),
                "model": _evaluate_daily_rankings(validation, "model_score"),
                "baseline": _evaluate_daily_rankings(validation, "baseline_score"),
            }
            fold_metrics[f"fold_{fold_number}_{quadrant}"] = metric
            predictions.append(validation)
    prediction_rows = pd.concat(predictions, ignore_index=True).sort_values(
        ["fold", "quadrant", "trade_date", "symbol"], kind="stable"
    ).reset_index(drop=True)
    candidate_screen = _fixed_baseline_gate(fold_metrics)
    return prediction_rows, {
        "fit_symbols_by_fold": fit_symbols_by_fold,
        "coefficients": coefficients,
        "fold_metrics": fold_metrics,
        "candidate_screen": candidate_screen,
        "production_integration_allowed": False,
    }


def run_ml_recovery_acceptance(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    panel_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
) -> dict[str, Any]:
    """Run the sealed recovery baseline and atomically publish local artifacts."""
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"recovery acceptance output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete recovery acceptance requires inspection: {temporary}")
    temporary.mkdir()
    try:
        _write_progress(temporary, "data-verify", status="running")
        inputs = verify_recovery_inputs(label_root, feature_asset_root, panel_root)
        input_manifest = {**inputs["input_manifest"], "code_commit": str(code_commit)}
        _write_json(temporary / "input_manifest.json", input_manifest)
        _write_json(temporary / "fixed_feature_contract.json", _fixed_feature_contract(inputs["feature_manifest"]))

        _write_progress(temporary, "build-common-mask", status="running")
        rows, mask_report = build_recovery_dataset(inputs)
        _write_json(temporary / "common_mask_report.json", mask_report)
        _write_json(temporary / "data_quality_report.json", _data_quality_report(rows, mask_report))

        _write_progress(temporary, "feature-diagnostics", status="running", eligible_row_count=int(len(rows)))
        diagnostics = audit_fixed_features(rows, inputs["split_plan"])
        diagnostics.to_csv(temporary / "feature_diagnostics.csv", index=False)

        _write_progress(temporary, "fixed-oof", status="running", eligible_row_count=int(len(rows)))
        predictions, oof_report = run_fixed_logistic_oof(rows, inputs["split_plan"])
        _write_parquet(temporary / "oof_predictions.parquet", predictions)
        _write_json(temporary / "fold_metrics.json", oof_report["fold_metrics"])
        _write_daily_metrics(predictions, temporary / "daily_metrics.csv")
        pd.DataFrame(oof_report["coefficients"]).to_csv(temporary / "coefficients.csv", index=False)
        _write_json(temporary / "candidate_screen.json", oof_report["candidate_screen"])
        report = {
            "status": "complete",
            "research_only": True,
            "production_integration_allowed": False,
            "model_role": "fixed_development_only_ranking_baseline",
            "model_serialized": False,
            "code_commit": str(code_commit),
            "input_manifest": input_manifest,
            "fixed_features": list(FIXED_FEATURES),
            "eligible_row_count": int(len(rows)),
            "eligible_symbol_count": int(rows["symbol"].nunique()),
            "eligible_trade_date_count": int(rows["trade_date"].nunique()),
            "candidate_screen": oof_report["candidate_screen"],
            "limitations": [
                "Only the sealed R1 development A/C folds were read; no future time holdout was opened.",
                "The model score is an uncalibrated ranking score, not a probability or trading instruction.",
                "This research run cannot modify production selection, ranking, trading, or risk behavior.",
            ],
        }
        _write_json(temporary / "ml_recovery_acceptance.json", report)
        _write_progress(temporary, "complete", status="complete", eligible_row_count=int(len(rows)))
        os.replace(temporary, destination)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            status="failed",
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _evaluate_daily_rankings(rows: pd.DataFrame, score_column: str) -> dict[str, float | int]:
    daily = [_daily_ranking_metrics(current, score_column) for _, current in rows.groupby("trade_date", sort=True)]
    if not daily:
        raise MLRecoveryAcceptanceError("ranking evaluation has no signal dates")
    summary: dict[str, float | int] = {"date_count": len(daily), "candidate_count": int(sum(item["candidate_count"] for item in daily))}
    for metric in ("precision_at_3", "precision_at_5", "precision_at_10", "ndcg_at_10", "mrr", "top_5_mean_net_return", "severe_negative_rate"):
        summary[metric] = float(np.mean([float(item[metric]) for item in daily]))
    return summary


def _daily_ranking_metrics(rows: pd.DataFrame, score_column: str) -> dict[str, float]:
    ranked = rows.sort_values([score_column, "symbol"], ascending=[False, True], kind="stable").reset_index(drop=True)
    strong = ranked["alpha_top10_10d"].eq(True).to_numpy(dtype=bool)
    top = lambda count: slice(0, min(count, len(ranked)))
    denominator = lambda count: max(1, min(count, len(ranked)))
    grades = strong.astype("float64")
    ideal = np.sort(grades)[::-1][:10]
    dcg = sum(float(value) / np.log2(index + 2) for index, value in enumerate(grades[:10]))
    idcg = sum(float(value) / np.log2(index + 2) for index, value in enumerate(ideal))
    first = np.flatnonzero(strong)
    selected = ranked.iloc[top(5)]
    returns = pd.to_numeric(selected["net_return_after_cost_10d"], errors="coerce")
    return {
        "candidate_count": float(len(ranked)),
        "precision_at_3": float(strong[top(3)].sum() / denominator(3)),
        "precision_at_5": float(strong[top(5)].sum() / denominator(5)),
        "precision_at_10": float(strong[top(10)].sum() / denominator(10)),
        "ndcg_at_10": float(dcg / idcg) if idcg > 0 else 0.0,
        "mrr": float(1.0 / (first[0] + 1)) if len(first) else 0.0,
        "top_5_mean_net_return": float(returns.mean()) if not returns.empty else 0.0,
        "severe_negative_rate": float(selected["severe_negative_10d"].eq(True).mean()) if not selected.empty else 0.0,
    }


def _fixed_baseline_gate(fold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    grouped = {"A": [], "C": []}
    for metric in fold_metrics.values():
        quadrant = str(metric.get("quadrant", ""))
        if quadrant in grouped:
            grouped[quadrant].append(metric)
    support = {}
    complete = all(len(grouped[quadrant]) == 5 for quadrant in grouped)
    for quadrant, metrics in grouped.items():
        support[quadrant] = sum(
            metric["model"]["ndcg_at_10"] > metric["baseline"]["ndcg_at_10"]
            and metric["model"]["precision_at_5"] > metric["baseline"]["precision_at_5"]
            for metric in metrics
        )
    if not complete:
        status = "incomplete_fixed_folds"
    elif support["A"] >= 4 and support["C"] >= 4:
        status = "baseline_research_completed"
    else:
        status = "baseline_research_failed_gate"
    return {
        "status": status,
        "passed": status == "baseline_research_completed",
        "required_fold_count": 4,
        "supporting_fold_counts": support,
        "evaluated_fold_counts": {key: len(value) for key, value in grouped.items()},
        "production_integration_allowed": False,
    }


def _fixed_feature_contract(feature_manifest: Mapping[str, Any]) -> dict[str, Any]:
    by_name = {
        str(item.get("name")): item
        for item in feature_manifest.get("feature_contract", {}).get("features", ())
        if isinstance(item, Mapping) and item.get("name")
    }
    return {
        "features": [
            {
                "name": feature,
                "source": by_name[feature].get("source"),
                "formula": by_name[feature].get("formula"),
                "availability": by_name[feature].get("availability"),
                "rank_transform": "same_trade_date_percentile_rank",
            }
            for feature in FIXED_FEATURES
        ],
        "forbidden_feature_tokens": list(_FORBIDDEN_FEATURE_TOKENS),
        "selection_or_tuning_allowed": False,
        "production_integration_allowed": False,
    }


def _data_quality_report(rows: pd.DataFrame, mask_report: Mapping[str, Any]) -> dict[str, Any]:
    daily_positive = rows.groupby("trade_date", sort=True)["alpha_top10_10d"].mean()
    feature_coverage = {
        feature: float(rows[feature].notna().mean())
        for feature in FIXED_FEATURES
    }
    return {
        "status": "complete",
        "source": dict(mask_report),
        "eligible_row_count": int(len(rows)),
        "eligible_symbol_count": int(rows["symbol"].nunique()),
        "eligible_trade_date_count": int(rows["trade_date"].nunique()),
        "daily_positive_rate_min": float(daily_positive.min()),
        "daily_positive_rate_median": float(daily_positive.median()),
        "daily_positive_rate_max": float(daily_positive.max()),
        "fixed_feature_coverage": feature_coverage,
        "common_mask_applied": True,
        "formal_future_holdout_read": False,
    }


def _write_daily_metrics(predictions: pd.DataFrame, path: Path) -> None:
    records = []
    for (fold, quadrant, trade_date), current in predictions.groupby(["fold", "quadrant", "trade_date"], sort=True):
        for score_name in ("model", "baseline"):
            metrics = _daily_ranking_metrics(current, f"{score_name}_score")
            records.append({"fold": int(fold), "quadrant": str(quadrant), "trade_date": str(trade_date), "score": score_name, **metrics})
    pd.DataFrame(records).to_csv(path, index=False)


def _require_r1_research_only(registry: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if registry.get("label_quality_passed") is not True:
        raise MLRecoveryAcceptanceError("R1 labels failed their quality gate")
    if registry.get("production_integration_allowed") is True:
        raise MLRecoveryAcceptanceError("R1 labels are not research-only")
    if registry.get("future_holdout_status") != "awaiting_model_freeze_and_future_labels":
        raise MLRecoveryAcceptanceError("R1 future holdout is not sealed")
    if manifest.get("status") != "complete_development_labels_ready" or manifest.get("research_ready") is not True:
        raise MLRecoveryAcceptanceError("R1 label asset is not complete and research-ready")
    if manifest.get("production_integration_allowed") is True:
        raise MLRecoveryAcceptanceError("R1 label asset is not research-only")
    _require_universe(manifest, "R1 label asset")


def _require_r2_research_only(manifest: Mapping[str, Any]) -> None:
    if manifest.get("status") != "complete" or manifest.get("research_ready") is not True:
        raise MLRecoveryAcceptanceError("R2 feature asset is not complete and research-ready")
    if manifest.get("production_integration_allowed") is True:
        raise MLRecoveryAcceptanceError("R2 feature asset is not research-only")
    if manifest.get("formal_future_holdout_status") != "awaiting_model_freeze_and_future_labels":
        raise MLRecoveryAcceptanceError("R2 future holdout is not sealed")
    _require_universe(manifest, "R2 feature asset")


def _require_panel_research_only(manifest: Mapping[str, Any]) -> None:
    if manifest.get("status") != "complete_shsz_panel_rebuilt" or manifest.get("research_ready") is not True:
        raise MLRecoveryAcceptanceError("certified panel is not a complete SH/SZ rebuilt research panel")
    if manifest.get("production_integration_allowed") is True:
        raise MLRecoveryAcceptanceError("certified panel is not research-only")
    _require_universe(manifest, "certified panel")


def _require_universe(manifest: Mapping[str, Any], source: str) -> None:
    if str(manifest.get("universe_id", "")) != UNIVERSE_ID:
        raise MLRecoveryAcceptanceError(f"{source} does not define {UNIVERSE_ID}")
    exchanges = tuple(str(value).upper() for value in manifest.get("allowed_exchanges", ()))
    if exchanges != ALLOWED_EXCHANGES:
        raise MLRecoveryAcceptanceError(f"{source} does not restrict the universe to SH/SZ")


def _verify_payload_hash(manifest: Mapping[str, Any], source: str) -> None:
    expected = str(manifest.get("sha256", ""))
    actual = _sha256_payload({key: value for key, value in manifest.items() if key != "sha256"})
    if not expected or actual != expected:
        raise MLRecoveryAcceptanceError(f"{source} SHA256 is invalid")


def _parse_sealed_development_split(payload: Mapping[str, Any]) -> dict[str, Any]:
    future_holdout = payload.get("future_holdout")
    if not isinstance(future_holdout, Mapping) or future_holdout.get("formal_evaluation_allowed") is not False:
        raise MLRecoveryAcceptanceError("future holdout must remain sealed")
    development_dates = tuple(sorted({_normalize_date(value, "R1 development split") for value in payload.get("development_dates", ())}))
    quadrants = payload.get("quadrants") if isinstance(payload.get("quadrants"), Mapping) else payload
    a_symbols = tuple(sorted({_normalize_symbol(value, "R1 development split") for value in quadrants.get("A_dev_train_symbols", ())}))
    c_symbols = tuple(sorted({_normalize_symbol(value, "R1 development split") for value in quadrants.get("C_dev_unseen_symbols", ())}))
    if not development_dates or not a_symbols or not c_symbols or set(a_symbols) & set(c_symbols):
        raise MLRecoveryAcceptanceError("R1 development split has invalid A/C membership")
    raw_folds = payload.get("walk_forward")
    if not isinstance(raw_folds, list) or len(raw_folds) != 5:
        raise MLRecoveryAcceptanceError("R1 development split must define exactly five walk-forward folds")
    folds = []
    for item in raw_folds:
        if not isinstance(item, Mapping):
            raise MLRecoveryAcceptanceError("R1 development split has an invalid walk-forward fold")
        training_dates = tuple(_normalize_date(value, "R1 walk-forward training date") for value in item.get("training_dates", ()))
        validation_dates = tuple(_normalize_date(value, "R1 walk-forward validation date") for value in item.get("validation_dates", ()))
        training_symbols = tuple(sorted({_normalize_symbol(value, "R1 walk-forward training symbol") for value in item.get("training_symbols", ())}))
        if not training_dates or not validation_dates or not training_symbols:
            raise MLRecoveryAcceptanceError("R1 development split has an incomplete walk-forward fold")
        if not set(training_dates).issubset(development_dates) or not set(validation_dates).issubset(development_dates):
            raise MLRecoveryAcceptanceError("R1 walk-forward fold uses a non-development date")
        if set(training_symbols) != set(a_symbols):
            raise MLRecoveryAcceptanceError("R1 walk-forward fold changes A training membership")
        folds.append(
            {
                "fold": int(item.get("fold")),
                "training_dates": training_dates,
                "validation_dates": validation_dates,
                "training_symbols": training_symbols,
            }
        )
    if {item["fold"] for item in folds} != {1, 2, 3, 4, 5}:
        raise MLRecoveryAcceptanceError("R1 development split has invalid walk-forward fold numbers")
    return {
        "development_dates": development_dates,
        "A_dev_train_symbols": a_symbols,
        "C_dev_unseen_symbols": c_symbols,
        "walk_forward": tuple(sorted(folds, key=lambda item: item["fold"])),
    }


def _verify_registered_parquet_files(root: Path, entries: Any, source: str) -> None:
    if not isinstance(entries, list) or not entries:
        raise MLRecoveryAcceptanceError(f"{source} registry has no registered parquet files")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MLRecoveryAcceptanceError(f"{source} registry has an invalid file entry")
        path = root / str(entry.get("path", ""))
        if not path.is_file():
            raise MLRecoveryAcceptanceError(f"{source} registered parquet file is missing: {path}")
        if _sha256_file(path) != str(entry.get("sha256", "")):
            raise MLRecoveryAcceptanceError(f"{source} registered parquet file SHA256 differs: {path}")
        if int(pq.ParquetFile(path).metadata.num_rows) != int(entry.get("row_count", -1)):
            raise MLRecoveryAcceptanceError(f"{source} registered parquet file row count differs: {path}")


def _read_registered_frames(
    root: Path,
    entries: Any,
    columns: tuple[str, ...],
    source: str,
) -> list[pd.DataFrame]:
    if not isinstance(entries, list) or not entries:
        raise MLRecoveryAcceptanceError(f"{source} loader has no registered files")
    frames = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MLRecoveryAcceptanceError(f"{source} loader has an invalid file entry")
        path = root / str(entry.get("path", ""))
        if not path.is_file():
            raise MLRecoveryAcceptanceError(f"{source} loader file is missing: {path}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise MLRecoveryAcceptanceError(f"{source} file misses required fields: " + ", ".join(missing))
        frames.append(pq.ParquetFile(path).read(columns=list(columns)).to_pandas())
    return frames


def _normalize_label_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("R1 labels must be a pandas DataFrame")
    missing = sorted(set(_REQUIRED_LABEL_COLUMNS) - set(rows.columns))
    if missing:
        raise MLRecoveryAcceptanceError("R1 labels miss recovery fields: " + ", ".join(missing))
    result = rows.loc[:, _REQUIRED_LABEL_COLUMNS].copy()
    result["trade_date"] = _normalize_date_series(result["trade_date"], "R1 labels")
    result["symbol"] = _normalize_symbol_series(result["symbol"], "R1 labels")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise MLRecoveryAcceptanceError("R1 labels have duplicate trade_date and symbol keys")
    return result


def _normalize_matrix_rows(rows: pd.DataFrame, features: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("R2 matrix must be a pandas DataFrame")
    required = {"trade_date", "symbol", *features}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise MLRecoveryAcceptanceError("R2 matrix misses fixed features: " + ", ".join(missing))
    result = rows.loc[:, ["trade_date", "symbol", *features]].copy()
    result["trade_date"] = _normalize_date_series(result["trade_date"], "R2 matrix")
    result["symbol"] = _normalize_symbol_series(result["symbol"], "R2 matrix")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise MLRecoveryAcceptanceError("R2 matrix has duplicate trade_date and symbol keys")
    return result


def _require_recovery_rows(rows: pd.DataFrame) -> None:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("recovery rows must be a pandas DataFrame")
    required = {
        "trade_date",
        "symbol",
        "risk_eligible",
        "alpha_target_10d",
        "net_return_after_cost_10d",
        *(f"rank__{feature}" for feature in FIXED_FEATURES),
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise MLRecoveryAcceptanceError("recovery rows miss required fields: " + ", ".join(missing))


def _require_oof_rows(rows: pd.DataFrame) -> None:
    _require_recovery_rows(rows)
    required = {"alpha_top10_10d", "severe_negative_10d", *(f"rank__{feature}" for feature in FIXED_FEATURES)}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise MLRecoveryAcceptanceError("OOF rows miss required fields: " + ", ".join(missing))
    if rows.duplicated(["trade_date", "symbol"]).any():
        raise MLRecoveryAcceptanceError("OOF rows have duplicate trade_date and symbol keys")


def _normalize_date_series(values: pd.Series, source: str) -> pd.Series:
    parsed = pd.to_datetime(values.astype("string"), errors="coerce", format="mixed")
    result = parsed.dt.strftime("%Y-%m-%d")
    if result.isna().any():
        raise MLRecoveryAcceptanceError(f"{source} has an invalid date: {values.loc[result.isna()].iloc[0]}")
    return result


def _normalize_symbol_series(values: pd.Series, source: str) -> pd.Series:
    raw = values.astype("string").fillna("").str.strip().str.upper()
    if raw.str.endswith(".BJ").any():
        raise MLRecoveryAcceptanceError(f"{source} contains BJ symbol before normalization")
    codes = raw.str.split(".", n=1, regex=False).str[0].str.zfill(6)
    invalid = raw.eq("") | ~codes.str.fullmatch(r"\d{6}").fillna(False)
    if invalid.any():
        raise MLRecoveryAcceptanceError(f"{source} has an invalid symbol: {raw.loc[invalid].iloc[0]}")
    return codes


def _read_json(path: Path, source: str) -> dict[str, Any]:
    if not path.is_file():
        raise MLRecoveryAcceptanceError(f"{source} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MLRecoveryAcceptanceError(f"{source} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise MLRecoveryAcceptanceError(f"{source} must be a JSON object: {path}")
    return payload


def _normalize_date(value: object, source: str) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise MLRecoveryAcceptanceError(f"{source} has an invalid date: {value}")
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _normalize_symbol(value: object, source: str) -> str:
    raw = str(value).strip().upper()
    if raw.endswith(".BJ"):
        raise MLRecoveryAcceptanceError(f"{source} contains BJ symbol before normalization")
    code = raw.split(".", 1)[0].zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise MLRecoveryAcceptanceError(f"{source} has an invalid symbol: {value}")
    return code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_progress(path: Path, stage: str, *, status: str, **details: Any) -> None:
    _write_json(
        path / "progress.json",
        {
            "stage": stage,
            "status": status,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write(path, lambda handle: json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True, default=_json_default))


def _write_parquet(path: Path, rows: pd.DataFrame) -> None:
    def write(handle: Any) -> None:
        table = pa.Table.from_pandas(rows, preserve_index=False)
        pq.write_table(table, handle, compression="zstd")

    _atomic_write(path, write, binary=True)


def _atomic_write(path: Path, writer: Any, *, binary: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        mode = "wb" if binary else "w"
        with os.fdopen(descriptor, mode, encoding=None if binary else "utf-8") as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")
