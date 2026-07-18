"""Read-only V3 contract feature evidence on registered walk-forward dates."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pyarrow.parquet as pq

from .feature_audit import FeatureAuditResult, audit_features
from .splits import SplitPlan, WalkForwardFold


class FeatureEvidenceError(ValueError):
    """Raised when a V3 feature evidence run lacks a certified input."""


_BLOCK_GROUPS = {
    "H1_momentum_trend": {"price_return", "trend", "cross_section_return"},
    "H2_liquidity_turnover": {"volume_liquidity", "cross_section_liquidity"},
    "H3_industry_relative": {"industry_relative"},
    "market_regime": {"market_context"},
}
_TURNOVER_FEATURES = {
    "turnover_rate",
    "turnover_ratio_20d",
    "turnover_rate_rank",
    "turnover_rate_robust_z",
}
_REQUIRED_COLUMNS = (
    "trade_date",
    "symbol",
    "future_return_10d",
    "net_return_after_cost_10d",
    "label_severe_negative_10d",
    "eligible_for_training_10d",
)


def run_v3_feature_evidence(
    *,
    source_dataset_root: str | Path,
    feature_asset_root: str | Path,
    output_root: str | Path,
    code_commit: str,
) -> dict[str, Any]:
    """Audit registered signal-time features without training or model selection."""
    source_root = Path(source_dataset_root).expanduser().resolve()
    asset_root = Path(feature_asset_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    manifest = _load_eligible_feature_asset(asset_root, source_root)
    split_payload = _read_json(source_root / "artifacts" / "full-build" / "split_plan_v2.json")
    split_plan = _development_only_split(split_payload)
    contract_features = _contract_features(manifest)
    matrix_root = Path(str(manifest["matrix_path"])).expanduser().resolve()
    block_features = _block_features(contract_features)
    selected_features = tuple(
        dict.fromkeys(feature for values in block_features.values() for feature in values)
    )
    if not selected_features:
        raise FeatureEvidenceError("feature contract has no auditable registered feature groups")

    _prepare_output(destination)
    _write_json(
        destination / "progress.json",
        {"status": "running", "stage": "load-walk-forward-rows", "updated_at": _now()},
    )
    try:
        rows = _load_walk_forward_rows(matrix_root, split_plan, selected_features)
        audit = audit_features(rows, split_plan, feature_schema=selected_features)
        _write_artifacts(destination, audit)
        report = _report(
            manifest=manifest,
            split_payload=split_payload,
            split_plan=split_plan,
            audit=audit,
            block_features=block_features,
            row_count=len(rows),
            code_commit=code_commit,
        )
        _write_json(destination / "feature_evidence.json", report)
        _write_json(
            destination / "progress.json",
            {"status": "complete", "stage": "complete", "updated_at": _now(), "row_count": len(rows)},
        )
        return report
    except Exception as error:
        _write_json(
            destination / "progress.json",
            {
                "status": "failed",
                "stage": "failed",
                "updated_at": _now(),
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        raise


def _load_eligible_feature_asset(asset_root: Path, source_root: Path) -> dict[str, Any]:
    path = asset_root / "feature_asset_manifest.json"
    manifest = _read_json(path)
    if manifest.get("status") != "complete" or manifest.get("training_eligible") is not True:
        raise FeatureEvidenceError("feature asset is not training eligible")
    if manifest.get("production_integration_allowed") is True:
        raise FeatureEvidenceError("feature evidence input must remain a research-only asset")
    if not str(manifest.get("feature_contract_sha256", "")):
        raise FeatureEvidenceError("feature asset is missing its contract SHA256")
    expected_sha = _payload_sha256({key: value for key, value in manifest.items() if key != "sha256"})
    if str(manifest.get("sha256", "")) != expected_sha:
        raise FeatureEvidenceError("feature asset manifest SHA256 is invalid")
    registry = _read_json(source_root / "dataset_registry_v2.json")
    if str(manifest.get("source_dataset_id", "")) != str(registry.get("dataset_id", "")):
        raise FeatureEvidenceError("feature asset belongs to a different source dataset")
    if str(manifest.get("source_dataset_sha256", "")) != str(registry.get("source_hashes", {}).get("dataset", "")):
        raise FeatureEvidenceError("feature asset source SHA256 does not match its dataset registry")
    matrix_root = Path(str(manifest.get("matrix_path", ""))).expanduser().resolve()
    if not matrix_root.is_dir():
        raise FeatureEvidenceError("feature asset matrix path is unavailable")
    return manifest


def _development_only_split(payload: Mapping[str, Any]) -> SplitPlan:
    development_dates = tuple(str(value) for value in payload.get("development_dates", ()))
    training_symbols = tuple(str(value) for value in payload.get("training_symbols", ()))
    holdout_symbols = tuple(str(value) for value in payload.get("stock_holdout_symbols", ()))
    folds = []
    for raw in payload.get("outer_folds", ()):
        validation_dates = tuple(str(value) for value in raw.get("test_dates", ()))
        fit_dates = tuple(str(value) for value in raw.get("fit_dates", ()))
        fold_symbols = tuple(str(value) for value in raw.get("training_symbols", training_symbols))
        if not validation_dates or not fold_symbols:
            raise FeatureEvidenceError("walk-forward fold is missing test dates or training symbols")
        if not set(validation_dates).issubset(set(development_dates)):
            raise FeatureEvidenceError("walk-forward fold includes a date outside the development period")
        folds.append(
            WalkForwardFold(
                fold=int(raw["fold"]),
                training_dates=fit_dates,
                validation_dates=validation_dates,
                training_symbols=fold_symbols,
                train_start=fit_dates[0] if fit_dates else "",
                train_end=fit_dates[-1] if fit_dates else "",
                validation_start=validation_dates[0],
                validation_end=validation_dates[-1],
            )
        )
    if len(folds) != 5:
        raise FeatureEvidenceError("feature evidence requires exactly five registered walk-forward folds")
    return SplitPlan(
        development_dates=development_dates,
        final_dates=(),
        stock_holdout_symbols=holdout_symbols,
        A_dev_train_symbols=training_symbols,
        B_final_train_symbols=(),
        C_dev_unseen_symbols=holdout_symbols,
        D_final_unseen_symbols=(),
        walk_forward=tuple(folds),
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256=str(payload.get("sha256", "")),
    )


def _contract_features(manifest: Mapping[str, Any]) -> dict[str, str]:
    values = manifest.get("feature_contract", {}).get("features", ())
    features = {
        str(item["name"]): str(item["group"])
        for item in values
        if isinstance(item, Mapping) and item.get("name") and item.get("group")
    }
    if not features:
        raise FeatureEvidenceError("feature asset has no registered feature definitions")
    return features


def _block_features(contract_features: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for block, groups in _BLOCK_GROUPS.items():
        names = [name for name, group in contract_features.items() if group in groups]
        if block == "H2_liquidity_turnover":
            names.extend(name for name in _TURNOVER_FEATURES if name in contract_features)
        result[block] = tuple(sorted(set(names)))
    return result


def _load_walk_forward_rows(
    matrix_root: Path,
    split_plan: SplitPlan,
    features: tuple[str, ...],
) -> pd.DataFrame:
    dates = {date for fold in split_plan.walk_forward for date in fold.validation_dates}
    columns = [*_REQUIRED_COLUMNS, *features]
    frames = []
    for trade_date in sorted(dates):
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise FeatureEvidenceError(f"feature matrix misses registered validation date: {trade_date}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise FeatureEvidenceError(
                f"feature matrix {trade_date} misses audit columns: " + ", ".join(missing)
            )
        frames.append(pq.read_table(path, columns=columns).to_pandas())
    rows = pd.concat(frames, ignore_index=True)
    rows["eligible_for_training"] = rows["eligible_for_training_10d"].eq(True)
    if rows.empty or not rows["eligible_for_training"].any():
        raise FeatureEvidenceError("walk-forward feature evidence has no label-eligible rows")
    return rows


def _write_artifacts(destination: Path, audit: FeatureAuditResult) -> None:
    audit.coverage.to_csv(destination / "feature_coverage.csv", index=False)
    audit.ic.to_csv(destination / "feature_ic.csv", index=False)
    audit.bucket_returns.to_csv(destination / "feature_bucket_returns.csv", index=False)
    audit.correlation.to_csv(destination / "feature_correlation.csv", index=False)
    audit.drift.to_csv(destination / "feature_drift.csv", index=False)
    audit.group_eligibility.to_csv(destination / "feature_group_eligibility.csv", index=False)


def _report(
    *,
    manifest: Mapping[str, Any],
    split_payload: Mapping[str, Any],
    split_plan: SplitPlan,
    audit: FeatureAuditResult,
    block_features: Mapping[str, tuple[str, ...]],
    row_count: int,
    code_commit: str,
) -> dict[str, Any]:
    return_target = "net_return_after_cost_10d"
    blocks = {
        block: _block_summary(audit, features, return_target)
        for block, features in block_features.items()
    }
    return {
        "status": "complete",
        "research_only": True,
        "model_selection_allowed": False,
        "production_integration_allowed": False,
        "code_commit": str(code_commit),
        "feature_asset_manifest_sha256": str(manifest.get("sha256", "")),
        "feature_contract_sha256": str(manifest["feature_contract_sha256"]),
        "source_dataset_id": str(manifest.get("source_dataset_id", "")),
        "source_dataset_sha256": str(manifest.get("source_dataset_sha256", "")),
        "split_sha256": str(split_payload.get("sha256", split_plan.split_sha256)),
        "walk_forward_fold_count": len(split_plan.walk_forward),
        "walk_forward_validation_date_count": len(
            {date for fold in split_plan.walk_forward for date in fold.validation_dates}
        ),
        "row_count": int(row_count),
        "blocks": blocks,
        "limitations": [
            "This is univariate development-period evidence, not a production-model result.",
            "The certified V3 contract has no materialized market_context feature, so market_regime is unavailable rather than inferred from a proxy.",
            "No final future holdout exists for this two-year research asset; no production decision may use this report.",
        ],
        "generated_at": _now(),
    }


def _block_summary(audit: FeatureAuditResult, features: tuple[str, ...], target: str) -> dict[str, Any]:
    if not features:
        return {
            "status": "unavailable",
            "reason": "no_registered_materialized_features",
            "feature_count": 0,
            "features": [],
        }
    ic = audit.ic.loc[audit.ic["feature"].isin(features) & audit.ic["target"].eq(target)].copy()
    buckets = audit.bucket_returns.loc[
        audit.bucket_returns["feature"].isin(features) & audit.bucket_returns["target"].eq(target)
    ].copy()
    coverage = audit.coverage.loc[audit.coverage["feature"].isin(features), "coverage"]
    return {
        "status": "evaluated",
        "feature_count": len(features),
        "features": list(features),
        "minimum_fold_coverage": float(coverage.min()) if not coverage.empty else 0.0,
        "median_feature_ic": float(ic["median_ic"].median()) if not ic.empty else None,
        "median_feature_icir": float(ic["icir"].replace([float("inf"), float("-inf")], pd.NA).median()) if not ic.empty else None,
        "median_top_bottom_spread": float(buckets["top_bottom_spread"].median()) if not buckets.empty else None,
        "stable_feature_count": int(ic.loc[ic["direction_consistency"].ge(0.8), "feature"].nunique()) if not ic.empty else 0,
        "selection_statuses": {
            str(key): int(value)
            for key, value in ic["selection"].value_counts().sort_index().items()
        },
    }


def _prepare_output(destination: Path) -> None:
    if destination.exists():
        if any(destination.iterdir()):
            raise FeatureEvidenceError(f"feature evidence output root must be empty: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=False)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required research artifact is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
