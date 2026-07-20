"""Development-only H1 evidence for certified SH/SZ industry-relative features.

This module intentionally contains no fitted model.  It answers one pre-registered
question only: do the four registered industry-relative features improve a fixed
equal-weight rank over the fixed ``adjusted_return_60d`` baseline on the sealed
R1 A/C development folds?  It cannot access a formal future time holdout and it
cannot modify production recommendations.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from .evaluator import (
    bootstrap_uplift,
    evaluate_ranking,
    simulate_daily_topk_portfolio,
    validate_identical_comparison_rows,
)
from .feature_audit import FeatureAuditResult, audit_features
from .splits import SplitPlan, WalkForwardFold


UNIVERSE_ID = "shsz_a_share_v1"
ALLOWED_EXCHANGES = ("SH", "SZ")
BASELINE_FEATURE = "adjusted_return_60d"
H1_FEATURES = (
    "industry_return_5d_rank",
    "industry_return_5d_excess",
    "industry_return_20d_rank",
    "industry_return_20d_excess",
)
_LABEL_COLUMNS = (
    "trade_date",
    "symbol",
    "eligible_for_training",
    "alpha_relevance_grade_10d",
    "alpha_top10_10d",
    "alpha_target_10d",
    "future_return_10d",
    "net_return_after_cost_10d",
    "severe_negative_10d",
    "entry_price",
    "exit_price",
    "exit_trade_date",
    "entry_tradeable",
    "path_ambiguous_10d",
    "horizon_available_10d",
)
_SCORE_COLUMNS = (*H1_FEATURES, BASELINE_FEATURE)


class SHSZH1FeatureEvidenceError(ValueError):
    """Raised when the R1/R2-bound H1 evidence contract is not admissible."""


def run_shsz_h1_feature_evidence(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    """Run the fixed H1 comparison without training or selecting a model."""
    labels_root = Path(label_root).expanduser().resolve()
    features_root = Path(feature_asset_root).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"H1 evidence output directory already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete H1 evidence requires inspection: {temporary}")
    temporary.mkdir(parents=True)
    try:
        _write_progress(temporary, "data-verify", status="running")
        inputs = _load_bound_inputs(labels_root, features_root)
        _write_json(temporary / "input_manifest.json", inputs["input_manifest"])

        _write_progress(temporary, "load-labels", status="running")
        labels = _load_labels(inputs, on_progress=lambda current, total: _write_progress(
            temporary,
            "load-labels",
            status="running",
            completed_files=current,
            total_files=total,
        ))
        _write_progress(temporary, "load-features", status="running", label_row_count=len(labels))
        rows = _load_joined_feature_rows(inputs, labels, on_progress=lambda current, total, trade_date: _write_progress(
            temporary,
            "load-features",
            status="running",
            completed_dates=current,
            total_dates=total,
            current_trade_date=trade_date,
        ))
        split_plan = inputs["split_plan"]

        _write_progress(temporary, "feature-audit", status="running", row_count=len(rows))
        audit = audit_features(
            rows,
            split_plan,
            feature_schema=H1_FEATURES,
            primary_target="alpha_target_10d",
            on_progress=lambda payload: _write_progress(
                temporary,
                "feature-audit",
                status="running",
                row_count=len(rows),
                **{key: value for key, value in payload.items() if key not in {"status", "stage"}},
            ),
        )
        _write_feature_audit_artifacts(temporary, audit)

        _write_progress(temporary, "score-fixed-h1", status="running", row_count=len(rows))
        scored = _score_fixed_h1(rows)
        fold_metrics, predictions = _evaluate_registered_folds(
            scored,
            split_plan,
            bootstrap_iterations=max(1, int(bootstrap_iterations)),
            on_progress=lambda fold, quadrant: _write_progress(
                temporary,
                "evaluate-fold",
                status="running",
                current_fold=fold,
                current_quadrant=quadrant,
            ),
        )
        pq.write_table(pa.Table.from_pandas(predictions, preserve_index=False), temporary / "predictions.parquet", compression="zstd")
        _write_json(temporary / "fold_metrics.json", fold_metrics)

        candidate_screen = _candidate_screen(fold_metrics)
        _write_json(temporary / "candidate_screen.json", candidate_screen)
        report = _report(
            inputs=inputs,
            rows=rows,
            audit=audit,
            fold_metrics=fold_metrics,
            candidate_screen=candidate_screen,
            code_commit=code_commit,
        )
        _write_json(temporary / "h1_feature_evidence.json", report)
        _write_model_card(temporary / "model_card.md", report)
        _write_progress(temporary, "complete", status="complete", row_count=len(rows))
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


def _load_bound_inputs(labels_root: Path, features_root: Path) -> dict[str, Any]:
    registry_path = labels_root / "dataset_registry.json"
    split_path = labels_root / "development_split_plan.json"
    label_manifest_path = labels_root / "label_split_manifest.json"
    feature_manifest_path = features_root / "feature_asset_manifest.json"
    registry = _read_json(registry_path)
    split_payload = _read_json(split_path)
    label_manifest = _read_json(label_manifest_path)
    feature_manifest = _read_json(feature_manifest_path)

    _require_research_only_r1(registry, label_manifest)
    _require_research_only_r2(feature_manifest)
    _verify_feature_manifest(feature_manifest)
    if _sha256_file(registry_path) != str(feature_manifest.get("label_registry_sha256", "")):
        raise SHSZH1FeatureEvidenceError("R2 label registry SHA256 does not match the supplied R1 label registry")
    if _sha256_file(split_path) != str(feature_manifest.get("label_split_sha256", "")):
        raise SHSZH1FeatureEvidenceError("R2 label split SHA256 does not match the supplied R1 development split")
    panel_sha = str(registry.get("source_panel_manifest_sha256", ""))
    if panel_sha != str(feature_manifest.get("panel_manifest_sha256", "")):
        raise SHSZH1FeatureEvidenceError("R1 and R2 source panel manifest SHA256 values differ")

    split_plan = _parse_development_split(split_payload)
    _verify_label_files(labels_root, registry)
    matrix_root = _verify_feature_matrix(features_root, feature_manifest, split_plan.development_dates)
    available = _feature_contract_names(feature_manifest)
    required = set(_SCORE_COLUMNS)
    missing = sorted(required - available)
    if missing:
        raise SHSZH1FeatureEvidenceError("R2 feature contract misses H1 evidence fields: " + ", ".join(missing))
    return {
        "registry": registry,
        "split_payload": split_payload,
        "label_manifest": label_manifest,
        "feature_manifest": feature_manifest,
        "labels_root": labels_root,
        "matrix_root": matrix_root,
        "split_plan": split_plan,
        "input_manifest": {
            "universe_id": UNIVERSE_ID,
            "allowed_exchanges": list(ALLOWED_EXCHANGES),
            "label_registry_sha256": _sha256_file(registry_path),
            "label_split_sha256": _sha256_file(split_path),
            "label_split_manifest_sha256": _sha256_file(label_manifest_path),
            "feature_asset_manifest_sha256": _sha256_file(feature_manifest_path),
            "feature_asset_payload_sha256": str(feature_manifest.get("sha256", "")),
            "source_panel_manifest_sha256": panel_sha,
            "registered_matrix_path": str(feature_manifest.get("matrix_path", "")),
            "resolved_matrix_path": str(matrix_root),
            "formal_future_holdout_status": "awaiting_model_freeze_and_future_labels",
            "bound_at": _now(),
        },
    }


def _require_research_only_r1(registry: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if registry.get("label_quality_passed") is not True:
        raise SHSZH1FeatureEvidenceError("R1 labels failed their quality gate")
    if manifest.get("status") != "complete_development_labels_ready" or manifest.get("research_ready") is not True:
        raise SHSZH1FeatureEvidenceError("R1 label asset is not research-ready")
    if manifest.get("production_integration_allowed") is True or registry.get("production_integration_allowed") is True:
        raise SHSZH1FeatureEvidenceError("H1 evidence requires a research-only R1 label asset")
    if manifest.get("universe_id") != UNIVERSE_ID or tuple(manifest.get("allowed_exchanges", ())) != ALLOWED_EXCHANGES:
        raise SHSZH1FeatureEvidenceError("R1 label asset does not declare the SH/SZ research universe")
    if registry.get("future_holdout_status") != "awaiting_model_freeze_and_future_labels":
        raise SHSZH1FeatureEvidenceError("H1 evidence cannot run after a future holdout state change")


def _require_research_only_r2(manifest: Mapping[str, Any]) -> None:
    if manifest.get("status") != "complete" or manifest.get("research_ready") is not True:
        raise SHSZH1FeatureEvidenceError("R2 feature asset is not complete and research-ready")
    if manifest.get("production_integration_allowed") is True:
        raise SHSZH1FeatureEvidenceError("H1 evidence requires a research-only R2 feature asset")
    if manifest.get("universe_id") != UNIVERSE_ID or tuple(manifest.get("allowed_exchanges", ())) != ALLOWED_EXCHANGES:
        raise SHSZH1FeatureEvidenceError("R2 feature asset does not declare the SH/SZ research universe")
    if manifest.get("formal_future_holdout_status") != "awaiting_model_freeze_and_future_labels":
        raise SHSZH1FeatureEvidenceError("H1 evidence cannot access an opened future holdout")


def _verify_feature_manifest(manifest: Mapping[str, Any]) -> None:
    expected = _payload_sha256({key: value for key, value in manifest.items() if key != "sha256"})
    if str(manifest.get("sha256", "")) != expected:
        raise SHSZH1FeatureEvidenceError("R2 feature asset manifest SHA256 is invalid")


def _parse_development_split(payload: Mapping[str, Any]) -> SplitPlan:
    future = payload.get("future_holdout")
    if not isinstance(future, Mapping) or future.get("formal_evaluation_allowed") is not False:
        raise SHSZH1FeatureEvidenceError("development split must keep the formal future holdout sealed")
    dates = tuple(sorted({_date_text(value) for value in payload.get("development_dates", ())}))
    a_symbols = tuple(sorted({_symbol_text(value) for value in payload.get("A_dev_train_symbols", ())}))
    c_symbols = tuple(sorted({_symbol_text(value) for value in payload.get("C_dev_unseen_symbols", ())}))
    if not dates or not a_symbols or not c_symbols or set(a_symbols) & set(c_symbols):
        raise SHSZH1FeatureEvidenceError("development split has invalid A/C membership")
    raw_folds = payload.get("walk_forward", ())
    folds = []
    for raw in raw_folds:
        validation_dates = tuple(_date_text(value) for value in raw.get("validation_dates", ()))
        training_dates = tuple(_date_text(value) for value in raw.get("training_dates", ()))
        training_symbols = tuple(sorted({_symbol_text(value) for value in raw.get("training_symbols", ())}))
        if not validation_dates or not training_dates or not training_symbols:
            raise SHSZH1FeatureEvidenceError("development split has an incomplete walk-forward fold")
        if not set(validation_dates).issubset(dates) or not set(training_dates).issubset(dates):
            raise SHSZH1FeatureEvidenceError("development split fold includes non-development dates")
        if set(training_symbols) != set(a_symbols):
            raise SHSZH1FeatureEvidenceError("development split fold changes fixed A training membership")
        folds.append(WalkForwardFold(
            fold=int(raw["fold"]),
            training_dates=training_dates,
            validation_dates=validation_dates,
            training_symbols=training_symbols,
            train_start=_date_text(raw.get("train_start", training_dates[0])),
            train_end=_date_text(raw.get("train_end", training_dates[-1])),
            validation_start=_date_text(raw.get("validation_start", validation_dates[0])),
            validation_end=_date_text(raw.get("validation_end", validation_dates[-1])),
        ))
    if len(folds) != 5 or {fold.fold for fold in folds} != {1, 2, 3, 4, 5}:
        raise SHSZH1FeatureEvidenceError("H1 evidence requires exactly five registered walk-forward folds")
    return SplitPlan(
        development_dates=dates,
        final_dates=(),
        stock_holdout_symbols=c_symbols,
        A_dev_train_symbols=a_symbols,
        B_final_train_symbols=(),
        C_dev_unseen_symbols=c_symbols,
        D_final_unseen_symbols=(),
        walk_forward=tuple(sorted(folds, key=lambda item: item.fold)),
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256=str(payload.get("split_sha256", "")),
    )


def _verify_label_files(root: Path, registry: Mapping[str, Any]) -> None:
    entries = registry.get("label_files", ())
    if not isinstance(entries, list) or not entries:
        raise SHSZH1FeatureEvidenceError("R1 label registry has no registered label files")
    for entry in entries:
        path = root / str(entry.get("path", ""))
        if not path.is_file():
            raise SHSZH1FeatureEvidenceError(f"registered R1 label file is missing: {path}")
        if int(entry.get("row_count", -1)) != int(pq.ParquetFile(path).metadata.num_rows):
            raise SHSZH1FeatureEvidenceError(f"registered R1 label file row count differs: {path}")
        if _sha256_file(path) != str(entry.get("sha256", "")):
            raise SHSZH1FeatureEvidenceError(f"registered R1 label file SHA256 differs: {path}")


def _verify_feature_matrix(root: Path, manifest: Mapping[str, Any], development_dates: Iterable[str]) -> Path:
    registered = Path(str(manifest.get("matrix_path", ""))).expanduser().resolve()
    root_matrix = (root / "matrix").resolve()
    if registered.is_dir() and registered.is_relative_to(root):
        matrix_root = registered
    elif root_matrix.is_dir():
        # R2 was atomically promoted from a staging directory.  Older manifests
        # retain that now-removed staging path, but only the same asset's fixed
        # matrix/ directory is admissible as a relocation target.
        matrix_root = root_matrix
    else:
        raise SHSZH1FeatureEvidenceError("R2 matrix path is unavailable or escapes its feature asset root")
    # This deliberate Hive scan rejects the old v1 large_string/string partition
    # mismatch before any labels or scores are consumed.
    try:
        schema = ds.dataset(matrix_root, format="parquet", partitioning="hive").schema
    except (pa.ArrowInvalid, pa.ArrowTypeError) as error:
        raise SHSZH1FeatureEvidenceError("R2 matrix is not Hive-readable with its partition schema") from error
    for key in ("trade_date", "symbol"):
        if key not in schema.names or schema.field(key).type != pa.string():
            raise SHSZH1FeatureEvidenceError(f"R2 matrix {key} must use Arrow string for Hive compatibility")
    entries = manifest.get("matrix_files", ())
    if not isinstance(entries, list) or not entries:
        raise SHSZH1FeatureEvidenceError("R2 feature manifest has no registered matrix files")
    by_date: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        path = root / str(entry.get("path", ""))
        if not path.is_file() or _sha256_file(path) != str(entry.get("sha256", "")):
            raise SHSZH1FeatureEvidenceError(f"registered R2 matrix file SHA256 differs: {path}")
        trade_date = _date_text(entry.get("trade_date"))
        by_date[trade_date] = entry
    missing = sorted(set(development_dates) - set(by_date))
    if missing:
        raise SHSZH1FeatureEvidenceError("R2 matrix misses R1 development dates: " + ", ".join(missing[:5]))
    return matrix_root


def _feature_contract_names(manifest: Mapping[str, Any]) -> set[str]:
    features = manifest.get("feature_contract", {}).get("features", ())
    return {
        str(item.get("name"))
        for item in features
        if isinstance(item, Mapping) and item.get("name")
    }


def _load_labels(inputs: Mapping[str, Any], *, on_progress) -> pd.DataFrame:
    entries = inputs["registry"]["label_files"]
    frames = []
    for index, entry in enumerate(entries, start=1):
        path = Path(inputs["labels_root"]) / str(entry["path"])
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(_LABEL_COLUMNS) - available)
        if missing:
            raise SHSZH1FeatureEvidenceError("R1 labels miss H1 evidence columns: " + ", ".join(missing))
        frame = pq.ParquetFile(path).read(columns=list(_LABEL_COLUMNS)).to_pandas()
        _assert_no_bj_symbols(frame, "R1 labels")
        frames.append(frame)
        on_progress(index, len(entries))
    labels = pd.concat(frames, ignore_index=True)
    labels["trade_date"] = labels["trade_date"].map(_date_text)
    labels["symbol"] = labels["symbol"].map(_symbol_text)
    labels = labels.loc[labels["eligible_for_training"].eq(True)].copy()
    labels = labels.dropna(subset=["trade_date", "symbol"])
    if labels.duplicated(["trade_date", "symbol"]).any():
        raise SHSZH1FeatureEvidenceError("R1 labels contain duplicate trade_date/symbol keys")
    expected_dates = set(inputs["split_plan"].development_dates)
    actual_dates = set(labels["trade_date"])
    if actual_dates != expected_dates:
        raise SHSZH1FeatureEvidenceError("R1 labels do not exactly cover the registered development dates")
    return labels.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _load_joined_feature_rows(inputs: Mapping[str, Any], labels: pd.DataFrame, *, on_progress) -> pd.DataFrame:
    matrix_root = Path(inputs["matrix_root"])
    dates = tuple(inputs["split_plan"].development_dates)
    frames = []
    columns = ["trade_date", "symbol", *_SCORE_COLUMNS]
    for index, trade_date in enumerate(dates, start=1):
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise SHSZH1FeatureEvidenceError(f"R2 matrix file missing for development date: {trade_date}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise SHSZH1FeatureEvidenceError(f"R2 matrix {trade_date} misses H1 evidence columns: " + ", ".join(missing))
        frame = pq.ParquetFile(path).read(columns=columns).to_pandas()
        _assert_no_bj_symbols(frame, f"R2 matrix {trade_date}")
        frame["trade_date"] = frame["trade_date"].map(_date_text)
        frame["symbol"] = frame["symbol"].map(_symbol_text)
        if frame.duplicated(["trade_date", "symbol"]).any():
            raise SHSZH1FeatureEvidenceError(f"R2 matrix {trade_date} contains duplicate trade_date/symbol keys")
        frames.append(frame)
        on_progress(index, len(dates), trade_date)
    features = pd.concat(frames, ignore_index=True)
    merged = labels.merge(features, on=["trade_date", "symbol"], how="left", validate="one_to_one", indicator=True)
    missing = merged.loc[merged["_merge"].ne("both"), ["trade_date", "symbol"]]
    if not missing.empty:
        first = missing.iloc[0]
        raise SHSZH1FeatureEvidenceError(
            f"R2 matrix does not contain an R1 label key: {first['trade_date']}/{first['symbol']}"
        )
    merged = merged.drop(columns="_merge")
    if len(merged) != len(labels):
        raise SHSZH1FeatureEvidenceError("H1 input join did not preserve the R1 label row set")
    return merged.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _score_fixed_h1(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows.copy()
    for feature in _SCORE_COLUMNS:
        result[feature] = pd.to_numeric(result[feature], errors="coerce")
    h1_valid = result.loc[:, list(H1_FEATURES)].notna().all(axis=1)
    baseline_valid = result[BASELINE_FEATURE].notna()
    result["risk_eligible"] = (
        h1_valid
        & baseline_valid
        & result["entry_tradeable"].eq(True)
        & result["horizon_available_10d"].eq(True)
        & result["path_ambiguous_10d"].eq(False)
    )
    scores = pd.DataFrame(index=result.index)
    for feature in H1_FEATURES:
        scores[feature] = result.groupby("trade_date", sort=False)[feature].rank(method="average", pct=True)
    result["h1_industry_relative_score"] = scores.mean(axis=1)
    result["baseline_adjusted_return_60d_score"] = result[BASELINE_FEATURE]
    return result


def _evaluate_registered_folds(scored: pd.DataFrame, split_plan: SplitPlan, *, bootstrap_iterations: int, on_progress) -> tuple[dict[str, Any], pd.DataFrame]:
    metrics: dict[str, Any] = {}
    prediction_frames = []
    for fold in split_plan.walk_forward:
        for quadrant, symbols in (("A_development_seen", split_plan.A_dev_train_symbols), ("C_development_unseen", split_plan.C_dev_unseen_symbols)):
            on_progress(fold.fold, quadrant)
            rows = scored.loc[
                scored["trade_date"].isin(fold.validation_dates) & scored["symbol"].isin(symbols) & scored["risk_eligible"].eq(True)
            ].copy()
            if rows.empty:
                raise SHSZH1FeatureEvidenceError(f"fold {fold.fold} {quadrant} has no comparison rows after the fixed risk mask")
            comparators = {
                "h1_industry_relative": rows[["trade_date", "symbol", "risk_eligible"]].copy(),
                "baseline_adjusted_return_60d": rows[["trade_date", "symbol", "risk_eligible"]].copy(),
            }
            validate_identical_comparison_rows(comparators)
            h1 = evaluate_ranking(rows, score_col="h1_industry_relative_score", grade_col="alpha_relevance_grade_10d", strong_col="alpha_top10_10d")
            baseline = evaluate_ranking(rows, score_col="baseline_adjusted_return_60d_score", grade_col="alpha_relevance_grade_10d", strong_col="alpha_top10_10d")
            bootstrap = bootstrap_uplift(
                rows,
                score_col="h1_industry_relative_score",
                baseline_score_col="baseline_adjusted_return_60d_score",
                grade_col="alpha_relevance_grade_10d",
                strong_col="alpha_top10_10d",
                iterations=bootstrap_iterations,
                seed=10_000 + fold.fold,
                block_length=10,
            )
            h1_portfolio = _portfolio_with_ratio(simulate_daily_topk_portfolio(rows, score_col="h1_industry_relative_score"))
            baseline_portfolio = _portfolio_with_ratio(simulate_daily_topk_portfolio(rows, score_col="baseline_adjusted_return_60d_score"))
            key = f"fold_{fold.fold}_{quadrant}"
            metrics[key] = {
                "fold": fold.fold,
                "quadrant": quadrant,
                "validation_dates": list(fold.validation_dates),
                "comparison_row_count": int(len(rows)),
                "h1": h1,
                "baseline": baseline,
                "bootstrap": bootstrap,
                "h1_portfolio": h1_portfolio,
                "baseline_portfolio": baseline_portfolio,
            }
            prediction_frames.append(rows.assign(fold=fold.fold, quadrant=quadrant))
    return metrics, pd.concat(prediction_frames, ignore_index=True)


def _portfolio_with_ratio(portfolio: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(portfolio)
    drawdown = float(result.get("maximum_drawdown", 0.0))
    total_return = float(result.get("total_return", 0.0))
    result["return_drawdown_ratio"] = total_return / abs(drawdown) if drawdown < 0 else None
    return result


def _candidate_screen(metrics: Mapping[str, Any]) -> dict[str, Any]:
    a_rows = [value for key, value in metrics.items() if key.endswith("_A_development_seen")]
    c_rows = [value for key, value in metrics.items() if key.endswith("_C_development_unseen")]
    a_passes = [
        value["h1"]["precision_at_5"] >= value["baseline"]["precision_at_5"]
        and value["h1"]["ndcg_at_10"] >= value["baseline"]["ndcg_at_10"]
        and value["h1"]["top_5_mean_return"] >= value["baseline"]["top_5_mean_return"]
        and value["bootstrap"]["precision_at_5_uplift_ci_low"] > 0.0
        and value["h1_portfolio"]["maximum_drawdown"] >= value["baseline_portfolio"]["maximum_drawdown"]
        and value["h1_portfolio"]["closed_trade_count"] > 0
        for value in a_rows
    ]
    c_passes = [
        value["h1"]["ndcg_at_10"] >= value["baseline"]["ndcg_at_10"] - 0.02
        for value in c_rows
    ]
    a_count, c_count = sum(a_passes), sum(c_passes)
    passed = a_count >= 4 and c_count >= 4
    return {
        "status": "development_feature_group_candidate" if passed else "research_only_failed_gate",
        "passed": passed,
        "production_integration_allowed": False,
        "a_fold_pass_count": a_count,
        "c_fold_pass_count": c_count,
        "required_fold_count": 4,
        "market_state": {
            "status": "unavailable",
            "reason": "R2 has no registered materialized market_context feature; no proxy was inferred.",
        },
        "failure_rule": "H1 is not eligible for a ranker candidate unless both A and C pass at least four registered folds.",
    }


def _report(*, inputs: Mapping[str, Any], rows: pd.DataFrame, audit: FeatureAuditResult, fold_metrics: Mapping[str, Any], candidate_screen: Mapping[str, Any], code_commit: str) -> dict[str, Any]:
    return {
        "status": "complete",
        "research_only": True,
        "production_integration_allowed": False,
        "model_trained": False,
        "code_commit": str(code_commit),
        "universe_id": UNIVERSE_ID,
        "allowed_exchanges": list(ALLOWED_EXCHANGES),
        "hypothesis": "Fixed equal-weight H1 industry-relative ranking versus adjusted_return_60d baseline.",
        "h1_features": list(H1_FEATURES),
        "baseline_feature": BASELINE_FEATURE,
        "label_contract": {
            "relevance_grade": "alpha_relevance_grade_10d",
            "precision_positive": "alpha_top10_10d",
            "economics": "net_return_after_cost_10d",
            "continuous_alpha": "alpha_target_10d",
            "risk": "severe_negative_10d",
            "execution": ["entry_price", "exit_price", "exit_trade_date", "entry_tradeable", "path_ambiguous_10d", "horizon_available_10d"],
        },
        "input_manifest": inputs["input_manifest"],
        "row_count": int(len(rows)),
        "walk_forward_fold_count": len(inputs["split_plan"].walk_forward),
        "feature_audit": {
            "primary_target": "alpha_target_10d",
            "feature_count": len(H1_FEATURES),
            "minimum_coverage": float(audit.coverage["coverage"].min()) if not audit.coverage.empty else 0.0,
        },
        "fold_metrics": dict(fold_metrics),
        "candidate_screen": dict(candidate_screen),
        "market_state": dict(candidate_screen["market_state"]),
        "limitations": [
            "Development-only A/C evidence; the formal future time holdout remains sealed.",
            "No model was trained, tuned, calibrated, or attached to CoachService.",
            "No production ranking, score, buy, sell, stop, or position behavior changed.",
        ],
        "generated_at": _now(),
    }


def _write_feature_audit_artifacts(destination: Path, audit: FeatureAuditResult) -> None:
    audit.coverage.to_csv(destination / "feature_coverage.csv", index=False)
    audit.ic.to_csv(destination / "feature_ic.csv", index=False)
    audit.bucket_returns.to_csv(destination / "feature_bucket_returns.csv", index=False)
    audit.correlation.to_csv(destination / "feature_correlation.csv", index=False)
    audit.drift.to_csv(destination / "feature_drift.csv", index=False)
    audit.group_eligibility.to_csv(destination / "feature_group_eligibility.csv", index=False)


def _write_model_card(path: Path, report: Mapping[str, Any]) -> None:
    screen = report["candidate_screen"]
    path.write_text(
        "# SH/SZ R3 H1 Feature Evidence\n\n"
        "No model was trained. This is a fixed, development-only feature-group comparison.\n\n"
        f"- Status: `{screen['status']}`\n"
        f"- A fold passes: `{screen['a_fold_pass_count']}/5`\n"
        f"- C fold passes: `{screen['c_fold_pass_count']}/5`\n"
        "- Formal future time holdout: sealed\n"
        "- Production integration: forbidden\n",
        encoding="utf-8",
    )


def _assert_no_bj_symbols(rows: pd.DataFrame, source: str) -> None:
    raw = rows["symbol"].astype("string").fillna("").str.upper().str.strip()
    if raw.str.endswith(".BJ").any():
        raise SHSZH1FeatureEvidenceError(f"{source} contains a BJ symbol before H1 evidence calculation")


def _date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise SHSZH1FeatureEvidenceError(f"invalid trade_date in registered asset: {value}")
    return parsed.strftime("%Y-%m-%d")


def _symbol_text(value: Any) -> str:
    raw = str(value).strip().upper()
    if raw.endswith(".BJ"):
        raise SHSZH1FeatureEvidenceError("BJ symbol is outside the SH/SZ research universe")
    code = raw.split(".", 1)[0].zfill(6)
    if not code.isdigit() or len(code) != 6:
        raise SHSZH1FeatureEvidenceError(f"invalid symbol in registered asset: {value}")
    return code


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required H1 input is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_progress(destination: Path, stage: str, *, status: str, **values: Any) -> None:
    _write_json(destination / "progress.json", {"status": status, "stage": stage, "updated_at": _now(), **values})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
