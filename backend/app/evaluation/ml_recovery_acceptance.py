"""Immutable-input acceptance gate for one offline SH/SZ ML baseline.

This module is deliberately independent of production ML services.  It starts
by proving that the local research assets describe the same sealed SH/SZ
development-only study; later stages may consume its returned binding but may
not relax it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


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
