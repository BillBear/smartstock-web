"""Nested development-only training for the SmartStock three-head decision model."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

from .decision_policy import (
    DecisionPolicySpec,
    apply_decision_policy,
    derive_confidence_threshold,
    evaluate_policy_metrics,
    select_inner_policy,
)
from .features import assert_leak_free_schema
from .splits import FinalHoldoutAccessError, SplitPlan


LIGHTGBM_GRID = (
    {"num_leaves": 15, "max_depth": 4, "min_data_in_leaf": 500, "learning_rate": 0.05},
    {"num_leaves": 31, "max_depth": 6, "min_data_in_leaf": 500, "learning_rate": 0.03},
)
LOGISTIC_C_VALUES = (0.1, 1.0)


@dataclass(frozen=True)
class DecisionModelSpec:
    model_family: Literal["logistic", "lightgbm_shallow"]
    feature_schema: tuple[str, ...]
    success_target: str = "label_actionable_positive_10d"
    risk_target: str = "label_severe_negative_10d_v2"
    return_target: str = "target_clipped_return_10d"
    seeds: tuple[int, ...] = (17, 42, 73)

    def __post_init__(self) -> None:
        if self.model_family not in {"logistic", "lightgbm_shallow"}:
            raise ValueError("model_family must be logistic or lightgbm_shallow")
        if not self.feature_schema or len(self.feature_schema) > 125:
            raise ValueError("feature_schema must contain 1 to 125 features")
        assert_leak_free_schema(self.feature_schema)
        if not self.seeds:
            raise ValueError("seeds must not be empty")


def run_nested_decision_oof(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    model_specs: tuple[DecisionModelSpec, ...],
    policy_specs: tuple[DecisionPolicySpec, ...],
    *,
    checkpoint_dir: str | Path | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Select on inner time OOF and score only untouched outer A/C rows."""
    data = _development_rows(rows, split_plan, model_specs)
    if not model_specs:
        raise ValueError("model_specs must not be empty")
    if not policy_specs:
        raise ValueError("policy_specs must not be empty")

    contract = {
        "split_sha256": split_plan.split_sha256,
        "models": [asdict(spec) for spec in model_specs],
        "policies": [asdict(spec) for spec in policy_specs],
        "input_sha256": _data_contract_sha256(data, model_specs),
    }
    contract_sha256 = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    checkpoint_root = Path(checkpoint_dir) if checkpoint_dir is not None else None
    if checkpoint_root is not None:
        checkpoint_root.mkdir(parents=True, exist_ok=True)

    a_predictions: list[pd.DataFrame] = []
    c_predictions: list[pd.DataFrame] = []
    model_selection: list[dict[str, Any]] = []
    fold_metrics: list[dict[str, Any]] = []

    for fold in split_plan.walk_forward:
        if checkpoint_root is not None:
            loaded = _load_fold_checkpoint(
                checkpoint_root,
                fold.fold,
                contract_sha256=contract_sha256,
                resume=resume,
            )
            if loaded is not None:
                a_predictions.append(loaded["a_predictions"])
                if not loaded["c_predictions"].empty:
                    c_predictions.append(loaded["c_predictions"])
                fold_metrics.append(loaded["fold_metrics"])
                model_selection.append(loaded["model_selection"])
                continue
        outer_training = data.loc[
            data["trade_date"].isin(fold.training_dates)
            & data["symbol"].isin(fold.training_symbols)
        ].copy()
        outer_a = data.loc[
            data["trade_date"].isin(fold.validation_dates)
            & data["symbol"].isin(fold.training_symbols)
        ].copy()
        outer_c = data.loc[
            data["trade_date"].isin(fold.validation_dates)
            & data["symbol"].isin(split_plan.C_dev_unseen_symbols)
        ].copy()
        inner_train, inner_validation = _inner_time_split(outer_training)
        selected = _select_model_and_policy(
            inner_train,
            inner_validation,
            model_specs,
            policy_specs,
        )
        spec: DecisionModelSpec = selected["model_spec"]
        params = selected["model_params"]
        policy: DecisionPolicySpec = selected["policy_spec"]

        prior_all = pd.concat(a_predictions, ignore_index=True) if a_predictions else pd.DataFrame()
        prior_same_policy = [
            frame.loc[frame["policy_mode"].eq(policy.score_mode)]
            for frame in a_predictions
            if "policy_mode" in frame
        ]
        prior = pd.concat(prior_same_policy, ignore_index=True) if prior_same_policy else pd.DataFrame()
        threshold = derive_confidence_threshold(prior) if not prior.empty else None
        frozen_policy = DecisionPolicySpec(
            score_mode=policy.score_mode,
            risk_quantile_gate=policy.risk_quantile_gate,
            confidence_threshold=threshold,
        )
        fitted = _fit_heads(outer_training, spec, params)
        calibrators, calibration_meta = _prior_fold_calibrators(prior_all)
        a_raw = _predict_heads(fitted, outer_a, spec)
        a_scored = apply_decision_policy(_apply_prior_calibration(a_raw, calibrators, calibration_meta), frozen_policy)
        a_scored["fold"] = fold.fold
        a_scored["quadrant"] = "A_time_oof"
        a_scored["confidence_threshold"] = threshold
        a_predictions.append(a_scored)
        if not outer_c.empty:
            c_raw = _predict_heads(fitted, outer_c, spec)
            c_scored = apply_decision_policy(_apply_prior_calibration(c_raw, calibrators, calibration_meta), frozen_policy)
            c_scored["fold"] = fold.fold
            c_scored["quadrant"] = "C_unseen_oof"
            c_scored["confidence_threshold"] = threshold
            c_predictions.append(c_scored)

        fold_model = evaluate_policy_metrics(a_scored, score_col="policy_score", eligible_col="risk_eligible")
        fold_baseline = evaluate_policy_metrics(a_scored, score_col="amount_log")
        fold_record = {
            "fold": fold.fold,
            "model_family": spec.model_family,
            "score_mode": policy.score_mode,
            **{f"model_{key}": value for key, value in fold_model.items()},
            **{f"baseline_{key}": value for key, value in fold_baseline.items()},
        }
        selection_record = {
            "fold": fold.fold,
            "inner_training_dates": sorted(inner_train["trade_date"].unique().tolist()),
            "inner_validation_dates": sorted(inner_validation["trade_date"].unique().tolist()),
            "outer_validation_dates": list(fold.validation_dates),
            "model_family": spec.model_family,
            "model_params": dict(params),
            "score_mode": policy.score_mode,
            "inner_metrics": selected["metrics"],
            "confidence_threshold": threshold,
            "calibration_source_max_date": calibration_meta["source_max_date"],
            "probability_display_allowed": calibration_meta["probability_display_allowed"],
        }
        fold_metrics.append(fold_record)
        model_selection.append(selection_record)
        if checkpoint_root is not None:
            _write_fold_checkpoint(
                checkpoint_root,
                fold.fold,
                contract_sha256=contract_sha256,
                input_sha256=contract["input_sha256"],
                model_sha256=_json_sha256({"spec": asdict(spec), "params": dict(params)}),
                policy_sha256=_json_sha256(asdict(frozen_policy)),
                schema_sha256=str(a_scored["feature_schema_sha256"].iloc[0]),
                a_predictions=a_scored,
                c_predictions=c_scored if not outer_c.empty else outer_c,
                fold_metrics=fold_record,
                model_selection=selection_record,
            )

    a_frame = pd.concat(a_predictions, ignore_index=True) if a_predictions else data.iloc[0:0].copy()
    c_frame = pd.concat(c_predictions, ignore_index=True) if c_predictions else data.iloc[0:0].copy()
    model_metrics = evaluate_policy_metrics(a_frame, score_col="policy_score", eligible_col="risk_eligible")
    baseline_metrics = evaluate_policy_metrics(a_frame, score_col="amount_log")
    failed_gates = _development_gates(model_metrics, baseline_metrics, fold_metrics, c_frame)
    return {
        "status": "research_only_candidate" if not failed_gates else "research_only_failed_gate",
        "failed_gates": failed_gates,
        "a_predictions": a_frame,
        "c_predictions": c_frame,
        "model_metrics": model_metrics,
        "baseline_metrics": baseline_metrics,
        "fold_metrics": fold_metrics,
        "model_selection": model_selection,
        "contract_sha256": contract_sha256,
    }


def _data_contract_sha256(rows: pd.DataFrame, model_specs: tuple[DecisionModelSpec, ...]) -> str:
    columns = {
        "trade_date",
        "symbol",
        "amount_log",
        "label_actionable_positive_10d",
        "label_severe_negative_10d_v2",
        "target_clipped_return_10d",
        "return_relevance_grade_10d_v2",
    }
    for spec in model_specs:
        columns.update(spec.feature_schema)
    ordered = rows[sorted(columns)].copy()
    hashed = pd.util.hash_pandas_object(ordered, index=False, categorize=True).to_numpy(dtype="uint64")
    return hashlib.sha256(hashed.tobytes()).hexdigest()


def _json_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_fold_checkpoint(
    root: Path,
    fold: int,
    *,
    contract_sha256: str,
    resume: bool,
) -> dict[str, Any] | None:
    directory = root / f"fold_{fold:02d}"
    if not directory.exists():
        return None
    if not resume:
        raise FileExistsError(f"fold checkpoint already exists: {directory}")
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid fold checkpoint manifest: {manifest_path}") from error
    if manifest.get("contract_sha256") != contract_sha256:
        raise ValueError(f"fold {fold} checkpoint contract hash mismatch")
    frames = {}
    for key, filename in (("a_predictions", "a_predictions.parquet"), ("c_predictions", "c_predictions.parquet")):
        path = directory / filename
        if not path.is_file() or _file_sha256(path) != manifest.get("artifacts", {}).get(filename):
            raise ValueError(f"fold {fold} checkpoint checksum mismatch: {filename}")
        frames[key] = pd.read_parquet(path)
    return {
        **frames,
        "fold_metrics": manifest["fold_metrics"],
        "model_selection": manifest["model_selection"],
    }


def _write_fold_checkpoint(
    root: Path,
    fold: int,
    *,
    contract_sha256: str,
    input_sha256: str,
    model_sha256: str,
    policy_sha256: str,
    schema_sha256: str,
    a_predictions: pd.DataFrame,
    c_predictions: pd.DataFrame,
    fold_metrics: dict[str, Any],
    model_selection: dict[str, Any],
) -> None:
    destination = root / f"fold_{fold:02d}"
    if destination.exists():
        raise FileExistsError(f"fold checkpoint already exists: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=f".fold_{fold:02d}.tmp-", dir=root))
    try:
        a_path = temporary / "a_predictions.parquet"
        c_path = temporary / "c_predictions.parquet"
        a_predictions.to_parquet(a_path, index=False)
        c_predictions.to_parquet(c_path, index=False)
        manifest = {
            "schema_version": 1,
            "fold": fold,
            "contract_sha256": contract_sha256,
            "input_sha256": input_sha256,
            "model_sha256": model_sha256,
            "policy_sha256": policy_sha256,
            "feature_schema_sha256": schema_sha256,
            "artifacts": {
                a_path.name: _file_sha256(a_path),
                c_path.name: _file_sha256(c_path),
            },
            "fold_metrics": fold_metrics,
            "model_selection": model_selection,
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _development_rows(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    model_specs: tuple[DecisionModelSpec, ...],
) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    required = {
        "trade_date",
        "symbol",
        "amount_log",
        "label_actionable_positive_10d",
        "label_severe_negative_10d_v2",
        "target_clipped_return_10d",
        "return_relevance_grade_10d_v2",
    }
    for spec in model_specs:
        required.update(spec.feature_schema)
        required.update((spec.success_target, spec.risk_target, spec.return_target))
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("decision training rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if (~result["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("nested decision OOF accepts development dates only")
    if "eligible_for_training_10d" in result:
        result = result.loc[result["eligible_for_training_10d"].eq(True)].copy()
    if result.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("decision training rows contain duplicate trade_date and symbol")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _inner_time_split(outer_training: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = tuple(sorted(outer_training["trade_date"].unique()))
    if len(dates) < 2:
        raise ValueError("outer fold requires at least two training dates for inner selection")
    validation_count = max(1, int(np.ceil(len(dates) * 0.20)))
    validation_dates = dates[-validation_count:]
    training_dates = dates[:-validation_count]
    return (
        outer_training.loc[outer_training["trade_date"].isin(training_dates)].copy(),
        outer_training.loc[outer_training["trade_date"].isin(validation_dates)].copy(),
    )


def _select_model_and_policy(
    inner_train: pd.DataFrame,
    inner_validation: pd.DataFrame,
    model_specs: tuple[DecisionModelSpec, ...],
    policy_specs: tuple[DecisionPolicySpec, ...],
) -> dict[str, Any]:
    candidates = []
    for spec in model_specs:
        for params in _candidate_parameters(spec):
            fitted = _fit_heads(inner_train, spec, params, validation_rows=inner_validation)
            predictions = _predict_heads(fitted, inner_validation, spec)
            policy, metrics, reports = select_inner_policy(predictions, policy_specs)
            frozen_params = dict(params)
            if spec.model_family == "lightgbm_shallow":
                frozen_params["n_estimators"] = _selected_lightgbm_iterations(fitted)
            candidates.append(
                {
                    "model_spec": spec,
                    "model_params": frozen_params,
                    "policy_spec": policy,
                    "metrics": metrics,
                    "policy_reports": reports,
                }
            )
    return max(
        candidates,
        key=lambda item: (
            bool(item["metrics"]["risk_ok"]),
            bool(item["metrics"]["median_ok"]),
            float(item["metrics"]["ndcg_at_10"]),
            float(item["metrics"]["precision_at_5"]),
            -candidates.index(item),
        ),
    )


def _candidate_parameters(spec: DecisionModelSpec) -> tuple[dict[str, Any], ...]:
    if spec.model_family == "logistic":
        return tuple({"C": value} for value in LOGISTIC_C_VALUES)
    return tuple(dict(values) for values in LIGHTGBM_GRID)


def _fit_heads(
    rows: pd.DataFrame,
    spec: DecisionModelSpec,
    params: Mapping[str, Any],
    *,
    validation_rows: pd.DataFrame | None = None,
) -> dict[str, Any]:
    x = rows[list(spec.feature_schema)].astype("float32")
    validation_x = (
        validation_rows[list(spec.feature_schema)].astype("float32")
        if validation_rows is not None
        else None
    )
    fitted = {"success": [], "risk": [], "return": []}
    for seed in spec.seeds:
        fitted["success"].append(
            _fit_one(
                x,
                rows[spec.success_target],
                spec,
                params,
                seed,
                classification=True,
                validation_x=validation_x,
                validation_target=validation_rows[spec.success_target] if validation_rows is not None else None,
            )
        )
        fitted["risk"].append(
            _fit_one(
                x,
                rows[spec.risk_target],
                spec,
                params,
                seed,
                classification=True,
                validation_x=validation_x,
                validation_target=validation_rows[spec.risk_target] if validation_rows is not None else None,
            )
        )
        fitted["return"].append(
            _fit_one(
                x,
                rows[spec.return_target],
                spec,
                params,
                seed,
                classification=False,
                validation_x=validation_x,
                validation_target=validation_rows[spec.return_target] if validation_rows is not None else None,
            )
        )
    return fitted


def _fit_one(
    x: pd.DataFrame,
    target: pd.Series,
    spec: DecisionModelSpec,
    params: Mapping[str, Any],
    seed: int,
    *,
    classification: bool,
    validation_x: pd.DataFrame | None,
    validation_target: pd.Series | None,
) -> Any:
    y = pd.to_numeric(target, errors="coerce")
    valid = y.notna()
    x, y = x.loc[valid], y.loc[valid]
    if x.empty:
        raise ValueError("model head has no labeled training rows")
    if classification and y.nunique() < 2:
        return ("constant", float(y.iloc[0]))
    if spec.model_family == "logistic":
        steps = [("imputer", SimpleImputer(strategy="median", add_indicator=True)), ("scale", RobustScaler())]
        if classification:
            estimator = LogisticRegression(
                C=float(params["C"]),
                class_weight="balanced",
                max_iter=500,
                random_state=int(seed),
                solver="liblinear",
            )
        else:
            estimator = Ridge(alpha=1.0 / float(params["C"]), random_state=int(seed))
        model = Pipeline([*steps, ("model", estimator)])
        model.fit(x, y)
        return model

    import lightgbm as lgb

    common = {
        "n_estimators": int(params.get("n_estimators", 200)),
        "n_jobs": 6,
        "verbosity": -1,
        "random_state": int(seed),
        "num_leaves": int(params["num_leaves"]),
        "max_depth": int(params["max_depth"]),
        "min_child_samples": int(params["min_data_in_leaf"]),
        "learning_rate": float(params["learning_rate"]),
    }
    model = lgb.LGBMClassifier(class_weight="balanced", **common) if classification else lgb.LGBMRegressor(**common)
    fit_kwargs: dict[str, Any] = {}
    if validation_x is not None and validation_target is not None:
        validation_y = pd.to_numeric(validation_target, errors="coerce")
        valid_validation = validation_y.notna()
        if valid_validation.any():
            fit_kwargs = {
                "eval_set": [(validation_x.loc[valid_validation], validation_y.loc[valid_validation])],
                "eval_metric": "binary_logloss" if classification else "l2",
                "callbacks": [lgb.early_stopping(20, verbose=False)],
            }
    model.fit(x, y, **fit_kwargs)
    return model


def _selected_lightgbm_iterations(fitted: Mapping[str, list[Any]]) -> int:
    iterations = []
    for models in fitted.values():
        for model in models:
            value = getattr(model, "best_iteration_", None)
            if value is not None and int(value) > 0:
                iterations.append(int(value))
    return int(np.median(iterations)) if iterations else 200


def _predict_heads(fitted: Mapping[str, list[Any]], rows: pd.DataFrame, spec: DecisionModelSpec) -> pd.DataFrame:
    result = rows.copy()
    x = result[list(spec.feature_schema)].astype("float32")
    result["success_probability"] = _ensemble_predict(fitted["success"], x, classification=True)
    result["severe_probability"] = _ensemble_predict(fitted["risk"], x, classification=True)
    result["raw_success_score"] = result["success_probability"]
    result["raw_severe_score"] = result["severe_probability"]
    result["return_prediction"] = _ensemble_predict(fitted["return"], x, classification=False)
    result["model_family"] = spec.model_family
    result["feature_schema_sha256"] = hashlib.sha256("\n".join(spec.feature_schema).encode("utf-8")).hexdigest()
    return result


def _prior_fold_calibrators(prior_oof: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = {
        "source_max_date": None,
        "probability_display_allowed": False,
        "status": "uncalibrated_prior_oof_unavailable",
    }
    if prior_oof.empty:
        return {}, metadata
    metadata["source_max_date"] = str(prior_oof["trade_date"].max())
    calibrators = {}
    for name, score_col, target_col in (
        ("success", "raw_success_score", "label_actionable_positive_10d"),
        ("risk", "raw_severe_score", "label_severe_negative_10d_v2"),
    ):
        valid = prior_oof[[score_col, target_col]].dropna()
        if len(valid) < 30 or valid[target_col].nunique() < 2:
            continue
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(valid[score_col].to_numpy(dtype=float), valid[target_col].astype(int).to_numpy())
        calibrators[name] = calibrator
    if len(calibrators) == 2:
        metadata["status"] = "prior_oof_isotonic"
        metadata["probability_display_allowed"] = _prior_calibration_display_gate(prior_oof)
    return calibrators, metadata


def _apply_prior_calibration(
    predictions: pd.DataFrame,
    calibrators: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> pd.DataFrame:
    result = predictions.copy()
    if "success" in calibrators:
        result["success_probability"] = calibrators["success"].predict(result["raw_success_score"].to_numpy(dtype=float))
    if "risk" in calibrators:
        result["severe_probability"] = calibrators["risk"].predict(result["raw_severe_score"].to_numpy(dtype=float))
    result["calibration_status"] = metadata["status"]
    result["calibration_source_max_date"] = metadata["source_max_date"]
    result["probability_display_allowed"] = bool(metadata["probability_display_allowed"])
    return result


def _prior_calibration_display_gate(prior_oof: pd.DataFrame) -> bool:
    folds = sorted(pd.to_numeric(prior_oof.get("fold"), errors="coerce").dropna().unique())
    if len(folds) < 2:
        return False
    training = prior_oof.loc[prior_oof["fold"].isin(folds[:-1])]
    validation = prior_oof.loc[prior_oof["fold"].eq(folds[-1])]
    required = {"raw_success_score", "label_actionable_positive_10d"}
    if not required.issubset(training.columns) or training["label_actionable_positive_10d"].nunique() < 2:
        return False
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(
        training["raw_success_score"].to_numpy(dtype=float),
        training["label_actionable_positive_10d"].astype(int).to_numpy(),
    )
    probability = calibrator.predict(validation["raw_success_score"].to_numpy(dtype=float))
    outcome = validation["label_actionable_positive_10d"].astype(int).to_numpy(dtype=float)
    brier = float(np.mean((probability - outcome) ** 2))
    prevalence = float(outcome.mean())
    prevalence_brier = float(np.mean((prevalence - outcome) ** 2))
    ordered = pd.DataFrame({"probability": probability, "outcome": outcome}).sort_values("probability", kind="stable")
    groups = [
        ordered.iloc[indexes]
        for indexes in np.array_split(np.arange(len(ordered)), min(5, len(ordered)))
        if len(indexes)
    ]
    ece = float(sum(abs(part["probability"].mean() - part["outcome"].mean()) * len(part) for part in groups) / len(ordered))
    observed = [float(part["outcome"].mean()) for part in groups]
    monotonic = all(right + 1e-12 >= left for left, right in zip(observed, observed[1:]))
    return ece <= 0.05 and brier < prevalence_brier and monotonic


def _ensemble_predict(models: list[Any], x: pd.DataFrame, *, classification: bool) -> np.ndarray:
    predictions = []
    for model in models:
        if isinstance(model, tuple) and model[0] == "constant":
            predictions.append(np.full(len(x), model[1], dtype="float32"))
        elif classification:
            predictions.append(np.asarray(model.predict_proba(x)[:, 1], dtype="float32"))
        else:
            predictions.append(np.asarray(model.predict(x), dtype="float32"))
    return np.mean(np.vstack(predictions), axis=0)


def _development_gates(
    model: dict[str, float],
    baseline: dict[str, float],
    folds: list[dict[str, Any]],
    c_predictions: pd.DataFrame,
) -> list[str]:
    failed = []
    if model["precision_at_5"] <= baseline["precision_at_5"]:
        failed.append("a_precision_at_5_not_above_amount_log")
    if model["ndcg_at_10"] <= baseline["ndcg_at_10"]:
        failed.append("a_ndcg_at_10_not_above_amount_log")
    if model["top5_median_return"] <= 0.0:
        failed.append("a_top5_median_return_not_positive")
    if model["severe_rate"] > baseline["severe_rate"]:
        failed.append("a_severe_rate_worse_than_amount_log")
    fold_wins = sum(row["model_ndcg_at_10"] >= row["baseline_ndcg_at_10"] for row in folds)
    required = max(1, int(np.ceil(len(folds) * 0.80)))
    if fold_wins < required:
        failed.append("fold_ndcg_consistency_below_80_percent")
    if not c_predictions.empty:
        c_model = evaluate_policy_metrics(c_predictions, score_col="policy_score", eligible_col="risk_eligible")
        c_base = evaluate_policy_metrics(c_predictions, score_col="amount_log")
        if c_model["precision_at_5"] < 0.8 * model["precision_at_5"]:
            failed.append("c_precision_below_80_percent_of_a")
        if c_model["ndcg_at_10"] < 0.8 * model["ndcg_at_10"]:
            failed.append("c_ndcg_below_80_percent_of_a")
        if c_model["precision_at_5"] < c_base["precision_at_5"] and c_model["ndcg_at_10"] < c_base["ndcg_at_10"]:
            failed.append("c_trails_amount_log_on_precision_and_ndcg")
    return failed
