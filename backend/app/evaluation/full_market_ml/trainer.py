"""Development-only, OOF-gated candidate training for full-market ML research."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import weakref
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .evaluator import (
    bootstrap_uplift,
    evaluate_calibration,
    evaluate_ranking,
    simulate_daily_topk_portfolio,
)
from .feature_audit import FeatureAuditResult
from .features import CORE_FEATURE_SPECS
from .splits import FinalHoldoutAccessError, SplitPlan


FIXED_SEEDS = (17, 42, 73)
FIXED_RANKER_GRID = tuple(
    {"num_leaves": leaves, "max_depth": depth, "min_data_in_leaf": leaf}
    for leaves in (15, 31)
    for depth in (4, 6)
    for leaf in (200, 500)
)
RISK_ALPHAS = (0.0, 0.1, 0.2, 0.3)
_GROUP_SEQUENCE = ("momentum", "amount_turnover", "technical", "risk", "market_industry", "moneyflow")
_GROUPS = {spec.name: spec.feature_group for spec in CORE_FEATURE_SPECS}
_LOADED_FINAL_FITS: weakref.WeakKeyDictionary["FinalFit", tuple[Path, str]] = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class FrozenCandidate:
    """A development-only candidate; it cannot authorize final-holdout access."""

    selection_sources: list[str]
    oof_predictions: pd.DataFrame
    oof_metrics: dict[str, Any]
    baselines: dict[str, dict[str, Any]]
    model_selection_report: list[dict[str, Any]]
    calibrators: dict[str, dict[str, Any]]
    feature_importance: dict[str, float]
    frozen_model_sha256: str
    split_sha256: str
    preliminary_status: str
    failed_gates: list[str]
    fixed_ranker_grid: tuple[dict[str, int], ...]
    seeds: tuple[int, ...]
    risk_alphas: tuple[float, ...]
    selected_risk_alpha: float
    selected_ranker_params: dict[str, int]
    group_ablations: list[dict[str, Any]]
    selected_features: tuple[str, ...]
    seed_sensitivity: list[dict[str, Any]]
    error_samples: pd.DataFrame

    @property
    def can_open_final_holdout(self) -> bool:
        """Final holdout is reserved for development candidates that passed every fixed gate."""
        return self.preliminary_status == "research_only_candidate" and not self.failed_gates

    def manifest(self, *, config_sha256: str, data_sha256: str, feature_schema_sha256: str) -> dict[str, Any]:
        """Return the complete, non-model-binary contract required for one final evaluation."""
        return {
            "frozen_model_sha": self.frozen_model_sha256,
            "config_sha256": config_sha256,
            "data_sha256": data_sha256,
            "feature_schema_sha256": feature_schema_sha256,
            "split_sha256": self.split_sha256,
            "selection_sources": list(self.selection_sources),
            "selected_features": list(self.selected_features),
            "selected_ranker_params": dict(self.selected_ranker_params),
            "selected_risk_alpha": self.selected_risk_alpha,
            "seeds": list(self.seeds),
            "calibrators": self.calibrators,
            "preliminary_status": self.preliminary_status,
            "failed_gates": list(self.failed_gates),
        }

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "FrozenCandidate":
        """Restore the fixed candidate contract without rerunning development OOF selection."""
        required = {
            "frozen_model_sha",
            "split_sha256",
            "selection_sources",
            "selected_features",
            "selected_ranker_params",
            "selected_risk_alpha",
            "seeds",
            "calibrators",
            "preliminary_status",
            "failed_gates",
        }
        missing = sorted(required - set(manifest))
        if missing:
            raise ValueError("frozen candidate manifest missing: " + ", ".join(missing))
        return cls(
            selection_sources=list(manifest["selection_sources"]),
            oof_predictions=pd.DataFrame(),
            oof_metrics={},
            baselines={},
            model_selection_report=[],
            calibrators=dict(manifest["calibrators"]),
            feature_importance={},
            frozen_model_sha256=str(manifest["frozen_model_sha"]),
            split_sha256=str(manifest["split_sha256"]),
            preliminary_status=str(manifest["preliminary_status"]),
            failed_gates=list(manifest["failed_gates"]),
            fixed_ranker_grid=(),
            seeds=tuple(int(seed) for seed in manifest["seeds"]),
            risk_alphas=RISK_ALPHAS,
            selected_risk_alpha=float(manifest["selected_risk_alpha"]),
            selected_ranker_params={key: int(value) for key, value in dict(manifest["selected_ranker_params"]).items()},
            group_ablations=[],
            selected_features=tuple(str(feature) for feature in manifest["selected_features"]),
            seed_sensitivity=[],
            error_samples=pd.DataFrame(),
        )

@dataclass(frozen=True)
class FinalHoldoutEvaluation:
    """One-shot sealed-quadrant evaluation of an already frozen candidate."""

    selection_sources: list[str]
    predictions: pd.DataFrame
    quadrant_metrics: dict[str, dict[str, Any]]
    baseline_metrics: dict[str, dict[str, dict[str, Any]]]
    calibration: dict[str, dict[str, Any]]
    bootstrap: dict[str, dict[str, Any]]
    portfolios: dict[str, dict[str, Any]]
    model_status: str
    failed_gates: list[str]


@dataclass(frozen=True, eq=False)
class FinalFit:
    """Models fitted once from a frozen candidate on A development rows only."""

    frozen_model_sha256: str
    split_sha256: str
    selected_features: tuple[str, ...]
    selected_risk_alpha: float
    calibrators: dict[str, dict[str, Any]]
    rank_models: tuple[Any, ...]
    strong_models: tuple[Any, ...]
    strong_constant: float | None
    severe_models: tuple[Any, ...]
    severe_constant: float | None
    artifact_manifest_sha256: str | None = None


def save_final_fit(final_fit: FinalFit, target: str | Path) -> Path:
    """Persist one immutable final-fit artifact and return its directory.

    The artifact is deliberately separate from the frozen-candidate manifest:
    candidate selection is already complete at this point, while this stage
    contains the single model fitting pass allowed before sealed evaluation.
    """
    destination = Path(target)
    if destination.exists():
        raise FileExistsError(f"final fit artifact already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        manifest = {
            "schema_version": 1,
            "frozen_model_sha": final_fit.frozen_model_sha256,
            "split_sha256": final_fit.split_sha256,
            "selected_features": list(final_fit.selected_features),
            "selected_risk_alpha": final_fit.selected_risk_alpha,
            "calibrators": final_fit.calibrators,
            "rank_models": _save_booster_models(final_fit.rank_models, "rank", temporary),
            "strong_models": _save_booster_models(final_fit.strong_models, "strong", temporary),
            "strong_constant": final_fit.strong_constant,
            "severe_models": _save_booster_models(final_fit.severe_models, "severe", temporary),
            "severe_constant": final_fit.severe_constant,
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def load_final_fit(source: str | Path, frozen_model_sha: str) -> FinalFit:
    """Load a persisted final fit only when it belongs to the frozen candidate."""
    directory = Path(source)
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"final fit manifest is missing: {manifest_path}") from error
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported final fit artifact schema")
    if manifest.get("frozen_model_sha") != frozen_model_sha:
        raise FinalHoldoutAccessError("final fit artifact SHA does not match frozen candidate")
    contract_fields = {"split_sha256", "selected_features", "selected_risk_alpha", "calibrators"}
    missing = sorted(field for field in contract_fields if field not in manifest)
    if missing:
        raise ValueError("final fit manifest missing prediction contract: " + ", ".join(missing))
    fitted = FinalFit(
        frozen_model_sha256=frozen_model_sha,
        split_sha256=str(manifest["split_sha256"]),
        selected_features=tuple(str(feature) for feature in manifest["selected_features"]),
        selected_risk_alpha=float(manifest["selected_risk_alpha"]),
        calibrators=dict(manifest["calibrators"]),
        rank_models=tuple(_load_booster_models(directory, manifest.get("rank_models"), "rank")),
        strong_models=tuple(_load_booster_models(directory, manifest.get("strong_models"), "strong")),
        strong_constant=_optional_float(manifest.get("strong_constant")),
        severe_models=tuple(_load_booster_models(directory, manifest.get("severe_models"), "severe")),
        severe_constant=_optional_float(manifest.get("severe_constant")),
        artifact_manifest_sha256=_file_sha256(manifest_path),
    )
    _LOADED_FINAL_FITS[fitted] = (manifest_path, fitted.artifact_manifest_sha256)
    return fitted


def _save_booster_models(models: tuple[Any, ...], prefix: str, directory: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for index, model in enumerate(models):
        filename = f"{prefix}_{index:02d}.txt"
        path = directory / filename
        model.save_model(str(path))
        entries.append({"file": filename, "sha256": _file_sha256(path)})
    return entries


def _load_booster_models(directory: Path, entries: Any, prefix: str) -> list[Any]:
    if not isinstance(entries, list):
        raise ValueError(f"final fit manifest has invalid {prefix} model list")
    models = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"final fit manifest has invalid {prefix} model entry")
        filename = entry.get("file")
        expected = f"{prefix}_{index:02d}.txt"
        if filename != expected:
            raise ValueError(f"final fit manifest has unexpected {prefix} model filename")
        path = directory / filename
        if not path.is_file() or _file_sha256(path) != entry.get("sha256"):
            raise ValueError(f"final fit {prefix} model checksum mismatch: {filename}")
        models.append(lgb.Booster(model_file=str(path)))
    return models


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_loaded_final_fit(final_fit: FinalFit) -> None:
    registered = _LOADED_FINAL_FITS.get(final_fit)
    if registered is None:
        raise FinalHoldoutAccessError("final holdout requires a loaded final fit artifact")
    manifest_path, expected_sha = registered
    if final_fit.artifact_manifest_sha256 != expected_sha or not manifest_path.is_file():
        raise FinalHoldoutAccessError("final holdout loaded final fit artifact is invalid")
    if _file_sha256(manifest_path) != expected_sha:
        raise FinalHoldoutAccessError("final holdout loaded final fit artifact was modified")


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def run_development_training(
    config: Any,
    dataset: pd.DataFrame,
    split_plan: SplitPlan,
    feature_audit: FeatureAuditResult | None = None,
) -> FrozenCandidate:
    """Train only on A walk-forward folds and freeze an OOF-selected research candidate."""
    data = _development_dataset(dataset, split_plan)
    seeds = tuple(config.training.seeds)
    if seeds != FIXED_SEEDS:
        raise ValueError(f"training seeds must be fixed at {FIXED_SEEDS}")
    features = _available_features(data)
    if not features:
        raise ValueError("development dataset has no supported leak-free features")

    baselines = _baselines(_oof_rows(data, split_plan))
    grid_reports = []
    for params in FIXED_RANKER_GRID:
        predictions = _ranker_oof(data, split_plan, features, params, seeds)
        metrics = evaluate_ranking(predictions)
        fold_metrics = _fold_metrics(predictions)
        grid_reports.append({"params": dict(params), "metrics": metrics, "median_fold_ndcg_at_10": median(row["ndcg_at_10"] for row in fold_metrics), "median_fold_precision_at_5": median(row["precision_at_5"] for row in fold_metrics)})
    selected = max(grid_reports, key=lambda row: (row["median_fold_ndcg_at_10"], row["median_fold_precision_at_5"], -row["params"]["min_data_in_leaf"]))
    group_ablations, selected_features = _run_group_ablations(data, split_plan, features, selected["params"], seeds, feature_audit)
    rank_predictions = _ranker_oof(data, split_plan, selected_features, selected["params"], seeds)
    strong_prob, strong_calibrator = _classifier_oof(data, split_plan, selected_features, "label_strong_path_10d", selected["params"], seeds)
    severe_prob, severe_calibrator = _classifier_oof(data, split_plan, selected_features, "label_severe_negative_10d", selected["params"], seeds)
    rank_predictions["strong_probability"] = strong_prob
    rank_predictions["severe_negative_probability"] = severe_prob
    risk_trials = []
    for alpha in RISK_ALPHAS:
        trial = rank_predictions.copy()
        trial["score"] = trial["score"] - alpha * trial["severe_negative_probability"]
        metrics = evaluate_ranking(trial)
        risk_trials.append({"alpha": alpha, "metrics": metrics})
    risk_selected = max(risk_trials, key=lambda row: (row["metrics"]["ndcg_at_10"], row["metrics"]["precision_at_5"], -row["alpha"]))
    rank_predictions["score"] = rank_predictions["score"] - risk_selected["alpha"] * rank_predictions["severe_negative_probability"]
    oof_metrics = evaluate_ranking(rank_predictions)
    seed_sensitivity = _seed_sensitivity(data, split_plan, selected_features, selected["params"], seeds)
    error_samples = _top_ranked_error_samples(rank_predictions)
    importances = _feature_importance(data, split_plan, selected_features, selected["params"], seeds)
    failed_gates = _failed_gates(oof_metrics, baselines["random"])
    payload = {
        "split_sha256": split_plan.split_sha256,
        "features": list(selected_features),
        "params": selected["params"],
        "risk_alpha": risk_selected["alpha"],
        "oof_metrics": oof_metrics,
    }
    frozen_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    return FrozenCandidate(
        selection_sources=["A_walk_forward_oof"],
        oof_predictions=rank_predictions.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True),
        oof_metrics=oof_metrics,
        baselines=baselines,
        model_selection_report=[*grid_reports, {"risk_alpha_trials": risk_trials}],
        calibrators={"strong": strong_calibrator, "severe_negative": severe_calibrator},
        feature_importance=importances,
        frozen_model_sha256=frozen_hash,
        split_sha256=split_plan.split_sha256,
        preliminary_status="research_only_failed_gate" if failed_gates else "research_only_candidate",
        failed_gates=failed_gates,
        fixed_ranker_grid=FIXED_RANKER_GRID,
        seeds=seeds,
        risk_alphas=RISK_ALPHAS,
        selected_risk_alpha=risk_selected["alpha"],
        selected_ranker_params=dict(selected["params"]),
        group_ablations=group_ablations,
        selected_features=selected_features,
        seed_sensitivity=seed_sensitivity,
        error_samples=error_samples,
    )


def fit_final_candidate(
    dataset: pd.DataFrame,
    split_plan: SplitPlan,
    candidate: FrozenCandidate,
    *,
    frozen_model_sha: str,
) -> FinalFit:
    """Fit fixed models once without re-running model selection or walk-forward."""
    if frozen_model_sha != candidate.frozen_model_sha256:
        raise FinalHoldoutAccessError("final fit requires the exact frozen candidate SHA")
    if not candidate.can_open_final_holdout:
        raise FinalHoldoutAccessError("final fit is blocked because the development gate did not pass")
    sealed = split_plan.seal_final_holdout(frozen_model_sha)
    train = _development_dataset(dataset, sealed)
    missing_features = sorted(set(candidate.selected_features) - set(train.columns))
    if missing_features:
        raise ValueError("final fit dataset missing selected features: " + ", ".join(missing_features))
    rank_models = tuple(
        _train_ranker(train, candidate.selected_features, candidate.selected_ranker_params, seed)
        for seed in candidate.seeds
    )
    strong_models, strong_constant = _train_classifier_models(
        train, candidate.selected_features, "label_strong_path_10d", candidate.selected_ranker_params, candidate.seeds
    )
    severe_models, severe_constant = _train_classifier_models(
        train, candidate.selected_features, "label_severe_negative_10d", candidate.selected_ranker_params, candidate.seeds
    )
    return FinalFit(
        frozen_model_sha256=frozen_model_sha,
        split_sha256=sealed.split_sha256,
        selected_features=tuple(candidate.selected_features),
        selected_risk_alpha=candidate.selected_risk_alpha,
        calibrators=dict(candidate.calibrators),
        rank_models=rank_models,
        strong_models=tuple(strong_models),
        strong_constant=strong_constant,
        severe_models=tuple(severe_models),
        severe_constant=severe_constant,
    )


def run_final_holdout_evaluation(
    config: Any,
    dataset: pd.DataFrame,
    split_plan: SplitPlan,
    candidate: FrozenCandidate,
    *,
    frozen_model_sha: str,
    final_fit: FinalFit | None = None,
    on_quadrant_complete: Callable[[str, pd.DataFrame], None] | None = None,
) -> FinalHoldoutEvaluation:
    """Fit the frozen candidate on development A and evaluate B/C/D exactly once.

    Candidate selection remains confined to A walk-forward OOF.  The B, C and D
    quadrants are only resolved after the supplied SHA has sealed the plan.
    """
    if frozen_model_sha != candidate.frozen_model_sha256:
        raise FinalHoldoutAccessError("final holdout requires the exact frozen candidate SHA")
    if not candidate.can_open_final_holdout:
        raise FinalHoldoutAccessError("final holdout is blocked because the development gate did not pass")
    sealed = split_plan.seal_final_holdout(frozen_model_sha)
    if final_fit is not None and final_fit.frozen_model_sha256 != frozen_model_sha:
        raise FinalHoldoutAccessError("final holdout fit SHA does not match frozen candidate")
    if final_fit is None or final_fit.artifact_manifest_sha256 is None:
        raise FinalHoldoutAccessError("final holdout requires a persisted final fit artifact")
    _verify_loaded_final_fit(final_fit)
    if final_fit is not None and (
        final_fit.split_sha256 != sealed.split_sha256
        or final_fit.selected_features != tuple(candidate.selected_features)
        or final_fit.selected_risk_alpha != candidate.selected_risk_alpha
        or final_fit.calibrators != candidate.calibrators
    ):
        raise FinalHoldoutAccessError("final holdout final fit prediction contract does not match frozen candidate")
    quadrants = {
        "B_time_holdout": (set(sealed.load_quadrant("B", frozen_model_sha=frozen_model_sha)), set(sealed.final_dates)),
        "C_stock_holdout": (set(sealed.load_quadrant("C", frozen_model_sha=frozen_model_sha)), set(sealed.development_dates)),
        "D_joint_holdout": (set(sealed.load_quadrant("D", frozen_model_sha=frozen_model_sha)), set(sealed.final_dates)),
    }
    data = _final_evaluation_dataset(dataset, sealed, candidate.selected_features)

    prediction_frames = []
    quadrant_metrics: dict[str, dict[str, Any]] = {}
    baseline_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    calibration: dict[str, dict[str, Any]] = {}
    bootstrap: dict[str, dict[str, Any]] = {}
    portfolios: dict[str, dict[str, Any]] = {}
    for quadrant, (symbols, dates) in quadrants.items():
        rows = data.loc[data["trade_date"].isin(dates) & data["symbol"].isin(symbols)].copy()
        if rows.empty:
            raise ValueError(f"final holdout quadrant {quadrant} has no eligible rows")
        predicted = _predict_frozen_candidate(
            rows,
            candidate,
            final_fit.rank_models,
            final_fit.strong_models,
            final_fit.strong_constant,
            final_fit.severe_models,
            final_fit.severe_constant,
        )
        predicted["quadrant"] = quadrant
        if on_quadrant_complete is not None:
            on_quadrant_complete(quadrant, predicted.copy())
        prediction_frames.append(predicted)
        quadrant_metrics[quadrant] = evaluate_ranking(predicted)
        baseline_metrics[quadrant] = _baselines(predicted)
        calibration[quadrant] = evaluate_calibration(predicted, score_col="strong_probability")
        baseline_column = _preferred_baseline_column(predicted)
        bootstrap[quadrant] = bootstrap_uplift(
            predicted,
            score_col="score",
            baseline_score_col=baseline_column,
            iterations=200,
        )
        portfolios[quadrant] = simulate_daily_topk_portfolio(predicted)

    failed_gates = list(candidate.failed_gates)
    if candidate.preliminary_status == "research_only_failed_gate":
        failed_gates.append("development_oof_gate_failed")
    for quadrant in ("B_time_holdout", "D_joint_holdout"):
        model = quadrant_metrics[quadrant]
        baseline = baseline_metrics[quadrant].get("momentum_60d", {})
        if baseline.get("status") != "available":
            failed_gates.append(f"{quadrant}:momentum_60d_baseline_unavailable")
        elif model["precision_at_5"] <= baseline["precision_at_5"]:
            failed_gates.append(f"{quadrant}:precision_at_5_not_above_momentum_60d")
        elif model["ndcg_at_10"] <= baseline["ndcg_at_10"]:
            failed_gates.append(f"{quadrant}:ndcg_at_10_not_above_momentum_60d")
    status = "research_only_failed_gate" if failed_gates else "research_only"
    return FinalHoldoutEvaluation(
        selection_sources=list(candidate.selection_sources),
        predictions=pd.concat(prediction_frames, ignore_index=True).sort_values(["quadrant", "trade_date", "symbol"], kind="stable").reset_index(drop=True),
        quadrant_metrics=quadrant_metrics,
        baseline_metrics=baseline_metrics,
        calibration=calibration,
        bootstrap=bootstrap,
        portfolios=portfolios,
        model_status=status,
        failed_gates=sorted(set(failed_gates)),
    )


def _development_dataset(dataset: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    required = {"trade_date", "symbol", "future_return_10d", "relevance_grade_10d", "label_strong_path_10d", "label_severe_negative_10d"}
    missing = sorted(required - set(dataset.columns))
    if missing:
        raise ValueError("development dataset missing columns: " + ", ".join(missing))
    data = dataset.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    data["symbol"] = data["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if data["trade_date"].isin(split_plan.final_dates).any() or (~data["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("development training cannot read final holdout or unplanned dates")
    if "eligible_for_training" in data:
        data = data.loc[data["eligible_for_training"].eq(True)].copy()
    data = data.loc[data["symbol"].isin(split_plan.A_dev_train_symbols)].copy()
    if data.empty:
        raise ValueError("development dataset has no eligible A-quadrant rows")
    return data.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _final_evaluation_dataset(dataset: pd.DataFrame, split_plan: SplitPlan, features: tuple[str, ...]) -> pd.DataFrame:
    required = {
        "trade_date",
        "symbol",
        "future_return_10d",
        "relevance_grade_10d",
        "label_strong_path_10d",
        "label_severe_negative_10d",
        *features,
    }
    missing = sorted(required - set(dataset.columns))
    if missing:
        raise ValueError("final holdout dataset missing columns: " + ", ".join(missing))
    data = dataset.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    data["symbol"] = data["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    allowed_dates = set(split_plan.development_dates) | set(split_plan.final_dates)
    if data["trade_date"].isna().any() or (~data["trade_date"].isin(allowed_dates)).any():
        raise FinalHoldoutAccessError("final holdout dataset contains an unplanned trading date")
    if "eligible_for_training" in data:
        data = data.loc[data["eligible_for_training"].eq(True)].copy()
    if data.empty:
        raise ValueError("final holdout dataset has no eligible rows")
    return data.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _train_classifier_models(train, features, label, params, seeds):
    target = train[label].astype(bool).astype(int)
    if target.nunique() < 2:
        return (), float(target.iloc[0])
    models = []
    for seed in seeds:
        models.append(
            lgb.train(
                {
                    "objective": "binary",
                    "metric": "binary_logloss",
                    "learning_rate": 0.03,
                    "feature_fraction": 0.8,
                    "bagging_fraction": 0.8,
                    "bagging_freq": 1,
                    "verbosity": -1,
                    "seed": seed,
                    **params,
                },
                lgb.Dataset(train[list(features)], label=target),
                num_boost_round=120,
            )
        )
    return tuple(models), None


def _predict_frozen_candidate(rows, candidate, rank_models, strong_models, strong_constant, severe_models, severe_constant):
    features = list(candidate.selected_features)
    result = rows.copy()
    result["score"] = np.median(
        np.vstack([model.predict(result[features], num_iteration=model.current_iteration()) for model in rank_models]), axis=0
    )
    strong_raw = _predict_classifier_probability(result, features, strong_models, strong_constant)
    severe_raw = _predict_classifier_probability(result, features, severe_models, severe_constant)
    result["strong_probability"] = _apply_calibrator(strong_raw, candidate.calibrators["strong"])
    result["severe_negative_probability"] = _apply_calibrator(severe_raw, candidate.calibrators["severe_negative"])
    result["score"] = result["score"] - candidate.selected_risk_alpha * result["severe_negative_probability"]
    return result


def _predict_classifier_probability(rows, features, models, constant):
    if constant is not None:
        return np.repeat(constant, len(rows))
    values = [model.predict(rows[features], num_iteration=model.current_iteration()) for model in models]
    return np.median(np.vstack(values), axis=0)


def _apply_calibrator(probabilities, report):
    values = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    selected = report.get("selected")
    if selected == "constant":
        return np.repeat(float(report["constant"]), len(values))
    if selected == "sigmoid":
        coefficient = float(report["coefficient"])
        intercept = float(report["intercept"])
        return 1.0 / (1.0 + np.exp(-(coefficient * values + intercept)))
    if selected == "isotonic":
        return np.interp(values, report["x_thresholds"], report["y_thresholds"])
    raise ValueError("unsupported frozen calibration report")


def _preferred_baseline_column(predictions: pd.DataFrame) -> str:
    for column in ("adjusted_return_60d", "adjusted_return_20d", "amount_log"):
        if column in predictions and pd.to_numeric(predictions[column], errors="coerce").notna().all():
            return column
    raise ValueError("final holdout predictions have no complete fixed baseline score")


def _available_features(data: pd.DataFrame) -> list[str]:
    return [name for name in _GROUPS if name in data and pd.api.types.is_numeric_dtype(data[name])]


def _baselines(data: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result = {}
    for name, column in (("random", None), ("momentum_20d", "adjusted_return_20d"), ("momentum_60d", "adjusted_return_60d"), ("amount", "amount_log")):
        if column is not None and column not in data:
            result[name] = {"status": "unavailable"}
            continue
        scores = _stable_random_score(data) if column is None else pd.to_numeric(data[column], errors="coerce").fillna(float("-inf"))
        result[name] = {"status": "available", **evaluate_ranking(data.assign(score=scores))}
    production = "production_strategy_score"
    if production not in data or data.groupby("trade_date")[production].apply(lambda values: values.notna().all()).eq(False).any():
        result["current_production_strategy"] = {"status": "unavailable"}
    else:
        result["current_production_strategy"] = {"status": "available", **evaluate_ranking(data.assign(score=data[production]))}
    return result


def _oof_rows(data: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    rows = [
        data.loc[
            data.trade_date.isin(fold.validation_dates) & data.symbol.isin(fold.training_symbols)
        ]
        for fold in split_plan.walk_forward
    ]
    return pd.concat(rows, ignore_index=True) if rows else data.iloc[0:0].copy()


def _stable_random_score(data: pd.DataFrame) -> pd.Series:
    return data.apply(lambda row: int(hashlib.sha256(f"17:{row.trade_date}:{row.symbol}".encode()).hexdigest()[:12], 16), axis=1)


def _ranker_oof(data, split_plan, features, params, seeds) -> pd.DataFrame:
    features = list(features)
    rows = []
    for fold in split_plan.walk_forward:
        train, valid = _fold_data(data, fold)
        if train.empty or valid.empty:
            continue
        scores = []
        for seed in seeds:
            model = _train_ranker(train, features, params, seed, valid)
            scores.append(model.predict(valid[features], num_iteration=model.best_iteration or model.current_iteration()))
        rows.append(valid.assign(score=np.median(np.vstack(scores), axis=0), fold=fold.fold))
    if not rows:
        raise ValueError("walk-forward plan produced no OOF rows")
    return pd.concat(rows, ignore_index=True)


def _seed_sensitivity(data, split_plan, features, params, seeds) -> list[dict[str, Any]]:
    """Measure the frozen ranker configuration per fixed seed on the same OOF rows."""
    result = []
    for seed in seeds:
        predictions = _ranker_oof(data, split_plan, features, params, (seed,))
        result.append({"seed": int(seed), **evaluate_ranking(predictions)})
    return result


def _top_ranked_error_samples(predictions: pd.DataFrame, top_k: int = 5) -> pd.DataFrame:
    ranked = (
        predictions.sort_values(["trade_date", "score", "symbol"], ascending=[True, False, True], kind="stable")
        .groupby("trade_date", sort=True)
        .head(top_k)
    )
    return ranked.loc[ranked["label_severe_negative_10d"].astype(bool)].reset_index(drop=True)


def _fold_data(data, fold):
    train = data.loc[data.trade_date.isin(fold.training_dates) & data.symbol.isin(fold.training_symbols)].copy()
    valid = data.loc[data.trade_date.isin(fold.validation_dates) & data.symbol.isin(fold.training_symbols)].copy()
    return train, valid


def _train_ranker(train, features, params, seed, valid=None):
    features = list(features)
    ordered = train.sort_values(["trade_date", "symbol"], kind="stable")
    groups = ordered.groupby("trade_date", sort=True).size().tolist()
    validation_sets = []
    if valid is not None and not valid.empty:
        validation = valid.sort_values(["trade_date", "symbol"], kind="stable")
        validation_sets = [
            lgb.Dataset(
                validation[features],
                label=pd.to_numeric(validation["relevance_grade_10d"], errors="coerce").fillna(0),
                group=validation.groupby("trade_date", sort=True).size().tolist(),
                reference=lgb.Dataset(ordered[features], label=pd.to_numeric(ordered["relevance_grade_10d"], errors="coerce").fillna(0), group=groups),
            )
        ]
    model = lgb.train(
        {"objective": "lambdarank", "metric": ["ndcg"], "ndcg_eval_at": [5, 10], "learning_rate": 0.03, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "verbosity": -1, "seed": seed, "feature_fraction_seed": seed, "bagging_seed": seed, **params},
        lgb.Dataset(ordered[features], label=pd.to_numeric(ordered["relevance_grade_10d"], errors="coerce").fillna(0), group=groups),
        num_boost_round=120,
        valid_sets=validation_sets or None,
        callbacks=[lgb.early_stopping(100, verbose=False)] if validation_sets else [],
    )
    return model


def _fold_metrics(predictions):
    return [evaluate_ranking(rows) for _, rows in predictions.groupby("fold", sort=True)]


def _classifier_oof(data, split_plan, features, label, params, seeds):
    features = list(features)
    raw_rows = []
    for fold in split_plan.walk_forward:
        train, valid = _fold_data(data, fold)
        if train.empty or valid.empty:
            continue
        target = train[label].astype(bool).astype(int)
        if target.nunique() < 2:
            probability = np.repeat(float(target.iloc[0]), len(valid))
        else:
            predictions = []
            for seed in seeds:
                model = lgb.train({"objective": "binary", "metric": "binary_logloss", "learning_rate": 0.03, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "verbosity": -1, "seed": seed, **params}, lgb.Dataset(train[features], label=target), num_boost_round=120)
                predictions.append(model.predict(valid[features]))
            probability = np.median(np.vstack(predictions), axis=0)
        raw_rows.append(valid[["trade_date", "symbol", label]].assign(raw_probability=probability))
    raw = pd.concat(raw_rows, ignore_index=True)
    calibrated, report = _calibrate_oof(raw["raw_probability"].to_numpy(), raw[label].astype(bool).astype(int).to_numpy())
    key = pd.MultiIndex.from_frame(raw[["trade_date", "symbol"]])
    values = pd.Series(calibrated, index=key)
    all_oof = _ranker_oof(data, split_plan, features, params, seeds)
    return pd.MultiIndex.from_frame(all_oof[["trade_date", "symbol"]]).map(values).to_numpy(dtype=float), report


def _calibrate_oof(probabilities, labels):
    clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    if len(np.unique(labels)) < 2:
        calibrated = np.repeat(float(labels[0]), len(labels))
        return calibrated, {
            "selected": "constant",
            "constant": float(labels[0]),
            "brier": float(np.mean((calibrated - labels) ** 2)),
            "source": "A_walk_forward_oof",
        }
    sigmoid_model = LogisticRegression(random_state=17, solver="liblinear").fit(clipped.reshape(-1, 1), labels)
    sigmoid = sigmoid_model.predict_proba(clipped.reshape(-1, 1))[:, 1]
    isotonic_model = IsotonicRegression(out_of_bounds="clip").fit(clipped, labels)
    isotonic = isotonic_model.transform(clipped)
    sigmoid_brier = float(np.mean((sigmoid - labels) ** 2))
    isotonic_brier = float(np.mean((isotonic - labels) ** 2))
    if sigmoid_brier <= isotonic_brier:
        return sigmoid, {
            "selected": "sigmoid",
            "coefficient": float(sigmoid_model.coef_[0][0]),
            "intercept": float(sigmoid_model.intercept_[0]),
            "brier": sigmoid_brier,
            "sigmoid_brier": sigmoid_brier,
            "isotonic_brier": isotonic_brier,
            "source": "A_walk_forward_oof",
        }
    return isotonic, {
        "selected": "isotonic",
        "x_thresholds": isotonic_model.X_thresholds_.tolist(),
        "y_thresholds": isotonic_model.y_thresholds_.tolist(),
        "brier": isotonic_brier,
        "sigmoid_brier": sigmoid_brier,
        "isotonic_brier": isotonic_brier,
        "source": "A_walk_forward_oof",
    }


def _run_group_ablations(data, split_plan, features, params, seeds, feature_audit):
    accepted = []
    report = []
    prior = None
    for group in _GROUP_SEQUENCE:
        group_features = [feature for feature in features if _training_group(feature) == group]
        available = bool(group_features) and _audit_allows(group, feature_audit)
        if not available:
            report.append({"group": group, "status": "unavailable", "reason": "missing_features_or_audit_gate"})
            continue
        trial_features = tuple(dict.fromkeys([*accepted, *group_features]))
        prediction = _ranker_oof(data, split_plan, trial_features, params, seeds)
        metrics = evaluate_ranking(prediction)
        fold_metrics = _fold_metrics(prediction)
        portfolio = _portfolio_or_empty(prediction)
        improved = prior is None or median(item["ndcg_at_10"] for item in fold_metrics) > prior["median_ndcg"] or median(item["precision_at_5"] for item in fold_metrics) > prior["median_precision"]
        worsens_both = prior is not None and metrics.get("severe_negative_rate", 0.0) > prior["severe"] and portfolio["maximum_drawdown"] < prior["drawdown"]
        status = "accepted" if improved and not worsens_both else "rejected"
        report.append({"group": group, "status": status, "features": group_features, "metrics": metrics, "portfolio": portfolio})
        if status == "accepted":
            accepted = list(trial_features)
            prior = {"median_ndcg": median(item["ndcg_at_10"] for item in fold_metrics), "median_precision": median(item["precision_at_5"] for item in fold_metrics), "severe": metrics.get("severe_negative_rate", 0.0), "drawdown": portfolio["maximum_drawdown"]}
    if not accepted:
        raise ValueError("no feature group passed development-only ablation gates")
    return report, tuple(accepted)


def _training_group(feature):
    original = _GROUPS.get(feature, "")
    if original == "price_return":
        return "momentum"
    if original in {"volume_liquidity", "valuation_liquidity"}:
        return "amount_turnover"
    if original == "trend":
        return "technical"
    if original == "volatility":
        return "risk"
    if original in {"industry_relative", "market_context"}:
        return "market_industry"
    return original


def _audit_allows(group, audit):
    if audit is None or group != "moneyflow":
        return True
    eligibility = audit.group_eligibility
    rows = eligibility.loc[eligibility["feature_group"].eq("moneyflow")]
    return not rows.empty and rows["eligibility"].eq("pending_oof_group_comparison").all()


def _portfolio_or_empty(predictions):
    required = {"adjusted_next_open", "adjusted_exit_close", "exit_trade_date"}
    return simulate_daily_topk_portfolio(predictions) if required.issubset(predictions.columns) else {"maximum_drawdown": 0.0}


def _feature_importance(data, split_plan, features, params, seeds):
    fold = split_plan.walk_forward[-1]
    train, _ = _fold_data(data, fold)
    values = []
    for seed in seeds:
        model = _train_ranker(train, features, params, seed)
        values.append(model.feature_importance(importance_type="gain"))
    return {feature: float(value) for feature, value in zip(features, np.median(np.vstack(values), axis=0))}


def _failed_gates(metrics, random_baseline):
    failures = []
    # A candidate must clear material fixed-baseline uplifts; three short OOF
    # folds can otherwise make randomly permuted labels look promising.
    if metrics["ndcg_at_10"] <= random_baseline["ndcg_at_10"] + 0.15:
        failures.append("ndcg_at_10_not_meaningfully_above_random")
    if metrics["precision_at_5"] <= random_baseline["precision_at_5"] + 0.20:
        failures.append("precision_at_5_not_meaningfully_above_random")
    return failures
