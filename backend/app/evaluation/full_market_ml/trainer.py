"""Development-only, OOF-gated candidate training for full-market ML research."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import weakref
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from types import SimpleNamespace
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
from .feature_audit import FeatureAuditResult, _audit_allowed_features
from .features import CORE_FEATURE_SPECS, OPTIONAL_FEATURE_SPECS
from .splits import FinalHoldoutAccessError, SplitPlan


FIXED_SEEDS = (17, 42, 73)
FIXED_RANKER_GRID = tuple(
    {"num_leaves": leaves, "max_depth": depth, "min_data_in_leaf": leaf}
    for leaves in (15, 31)
    for depth in (4, 6)
    for leaf in (200, 500)
)
RISK_ALPHAS = (0.0, 0.1, 0.2, 0.3)
PRE_REGISTERED_RISK_ALPHA = 0.2
_GROUP_SEQUENCE = ("momentum", "amount_turnover", "technical", "risk", "market_industry", "moneyflow")
_GROUPS = {spec.name: spec.feature_group for spec in (*CORE_FEATURE_SPECS, *OPTIONAL_FEATURE_SPECS)}
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
    *,
    checkpoint_dir: str | Path | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> FrozenCandidate:
    """Train only on A walk-forward folds and freeze an OOF-selected research candidate."""
    data = _development_dataset(dataset, split_plan)
    development_with_unseen = _development_dataset(
        dataset,
        split_plan,
        symbols=tuple(sorted(set(split_plan.A_dev_train_symbols) | set(split_plan.C_dev_unseen_symbols))),
    )
    seeds = tuple(config.training.seeds)
    if seeds != FIXED_SEEDS:
        raise ValueError(f"training seeds must be fixed at {FIXED_SEEDS}")
    features = _audit_allowed_features(_available_features(data), feature_audit)
    if feature_audit is not None:
        features = tuple(feature for feature in features if _audit_allows(_training_group(feature), feature_audit))
    features = list(features)
    if not features:
        raise ValueError("development dataset has no supported leak-free features")
    checkpoint_contract = (
        _development_checkpoint_contract(data, split_plan, features, seeds, config)
        if checkpoint_dir is not None
        else None
    )

    ranker_dataset_cache: dict[tuple[tuple[str, ...], int], tuple[lgb.Dataset, list[lgb.Dataset]]] = {}
    baselines = _baselines(_oof_rows(data, split_plan))
    rank_predictions, nested_selection, selected_params = _nested_ranker_oof(
        data,
        split_plan,
        features,
        seeds,
        dataset_cache=ranker_dataset_cache,
        checkpoint_dir=checkpoint_dir,
        checkpoint_contract=checkpoint_contract,
        on_progress=on_progress,
    )
    selected = {
        "params": selected_params,
        "metrics": evaluate_ranking(rank_predictions),
        "median_fold_ndcg_at_10": median(row["ndcg_at_10"] for row in _fold_metrics(rank_predictions)),
        "median_fold_precision_at_5": median(row["precision_at_5"] for row in _fold_metrics(rank_predictions)),
    }
    grid_reports = [{"selection_protocol": "nested_inner_oof", **row} for row in nested_selection]
    group_ablations = _run_group_ablations(
        data,
        split_plan,
        tuple(features),
        selected["params"],
        seeds,
        dataset_cache=ranker_dataset_cache,
        checkpoint_dir=checkpoint_dir,
        checkpoint_contract=checkpoint_contract,
        on_progress=on_progress,
        baseline_prediction=rank_predictions,
    )
    selected_features = tuple(features)
    unseen_predictions = _unseen_stock_oof(
        development_with_unseen,
        split_plan,
        selected_features,
        selected["params"],
        seeds,
        dataset_cache=ranker_dataset_cache,
        checkpoint_dir=checkpoint_dir,
        checkpoint_key="unseen-stocks",
        checkpoint_contract=checkpoint_contract,
        on_progress=on_progress,
    )
    strong_prob, strong_calibrator = _classifier_oof(
        data,
        split_plan,
        selected_features,
        "label_strong_path_10d",
        selected["params"],
        seeds,
        checkpoint_dir=checkpoint_dir,
        checkpoint_key="classifier-strong",
        checkpoint_contract=checkpoint_contract,
        on_progress=on_progress,
    )
    severe_prob, severe_calibrator = _classifier_oof(
        data,
        split_plan,
        selected_features,
        "label_severe_negative_10d",
        selected["params"],
        seeds,
        checkpoint_dir=checkpoint_dir,
        checkpoint_key="classifier-severe",
        checkpoint_contract=checkpoint_contract,
        on_progress=on_progress,
    )
    rank_predictions["strong_probability"] = strong_prob
    rank_predictions["severe_negative_probability"] = severe_prob
    risk_trials = []
    for alpha in RISK_ALPHAS:
        trial = rank_predictions.copy()
        trial["score"] = trial["score"] - alpha * trial["severe_negative_probability"]
        metrics = evaluate_ranking(trial)
        risk_trials.append({"alpha": alpha, "metrics": metrics})
    risk_selected = next(row for row in risk_trials if row["alpha"] == PRE_REGISTERED_RISK_ALPHA)
    risk_selected["selection_protocol"] = "pre_registered_before_outer_oof"
    rank_predictions["score"] = rank_predictions["score"] - risk_selected["alpha"] * rank_predictions["severe_negative_probability"]
    oof_metrics = evaluate_ranking(rank_predictions)
    development_quadrant_metrics = {
        "A_time_oof": oof_metrics,
        "C_stock_oof": evaluate_ranking(unseen_predictions) if not unseen_predictions.empty else {"status": "unavailable"},
    }
    seed_sensitivity = _seed_sensitivity(
        data, split_plan, selected_features, selected["params"], seeds, dataset_cache=ranker_dataset_cache
    )
    error_samples = _top_ranked_error_samples(rank_predictions)
    importances = _feature_importance(data, split_plan, selected_features, selected["params"], seeds)
    failed_gates = _failed_gates(oof_metrics, baselines["random"])
    payload = {
        "split_sha256": split_plan.split_sha256,
        "features": list(selected_features),
        "params": selected["params"],
        "risk_alpha": risk_selected["alpha"],
        "oof_metrics": oof_metrics,
        "development_quadrant_metrics": development_quadrant_metrics,
    }
    frozen_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    oof_output = pd.concat([rank_predictions, unseen_predictions], ignore_index=True, sort=False)
    return FrozenCandidate(
        selection_sources=["A_walk_forward_oof"],
        oof_predictions=oof_output.sort_values(["quadrant", "trade_date", "symbol"], kind="stable").reset_index(drop=True),
        oof_metrics=oof_metrics,
        baselines=baselines,
        model_selection_report=[*grid_reports, {"risk_alpha_trials": risk_trials}, {"development_quadrant_metrics": development_quadrant_metrics}],
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


def _development_dataset(
    dataset: pd.DataFrame, split_plan: SplitPlan, *, symbols: tuple[str, ...] | None = None
) -> pd.DataFrame:
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
    allowed_symbols = set(split_plan.A_dev_train_symbols if symbols is None else symbols)
    data = data.loc[data["symbol"].isin(allowed_symbols)].copy()
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
    keys = (
        "17:"
        + data["trade_date"].astype("string").fillna("")
        + ":"
        + data["symbol"].astype("string").fillna("")
    )
    return pd.Series(pd.util.hash_pandas_object(keys, index=False).to_numpy(), index=data.index, dtype="uint64")


def _nested_ranker_oof(
    data,
    split_plan,
    features,
    seeds,
    *,
    dataset_cache=None,
    checkpoint_dir: str | Path | None = None,
    checkpoint_contract: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
):
    """Select ranker parameters inside each outer fold, then score that fold."""
    rows = []
    selection_report = []
    selected_by_fold = []
    for outer_fold in split_plan.walk_forward:
        train, outer_valid = _fold_data(data, outer_fold)
        if train.empty or outer_valid.empty:
            continue
        selection_path = _selection_checkpoint_path(
            checkpoint_dir,
            outer_fold.fold,
            checkpoint_contract=checkpoint_contract,
        )
        if selection_path is not None and selection_path.is_file():
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            if selection.get("checkpoint_contract") != checkpoint_contract:
                raise ValueError("nested selection checkpoint contract does not match this development run")
            params = {key: int(value) for key, value in selection["params"].items()}
            inner_reports = list(selection.get("inner_reports", []))
            selection_report.append(selection)
        else:
            inner_split = _inner_selection_plan(train, outer_fold)
            if inner_split.walk_forward:
                params, inner_reports = _select_ranker_params(
                    train,
                    inner_split,
                    features,
                    seeds,
                    dataset_cache={},
                )
                selection = {
                    "fold": int(outer_fold.fold),
                    "params": params,
                    "inner_reports": inner_reports,
                    "checkpoint_contract": checkpoint_contract,
                }
            else:
                params = dict(FIXED_RANKER_GRID[0])
                inner_reports = []
                selection = {
                    "fold": int(outer_fold.fold),
                    "params": params,
                    "inner_reports": [],
                    "fallback": "insufficient_pre_outer_dates",
                    "checkpoint_contract": checkpoint_contract,
                }
            if selection_path is not None:
                _write_json_atomic(selection, selection_path)
            selection_report.append(selection)
        _report_progress(on_progress, "nested-selection", outer_fold.fold, len(split_plan.walk_forward), status="complete")
        selected_by_fold.append(tuple(sorted(params.items())))
        outer_only = SimpleNamespace(walk_forward=(outer_fold,))
        fold_predictions = _ranker_oof(
            data,
            outer_only,
            features,
            params,
            seeds,
            dataset_cache=dataset_cache,
            checkpoint_dir=checkpoint_dir,
            checkpoint_key=f"nested-outer-fold-{outer_fold.fold}",
            checkpoint_contract=checkpoint_contract,
            on_progress=on_progress,
            progress_total=len(split_plan.walk_forward),
        )
        rows.append(fold_predictions)
    if not rows:
        raise ValueError("nested walk-forward plan produced no OOF rows")
    selected = dict(Counter(selected_by_fold).most_common(1)[0][0])
    return pd.concat(rows, ignore_index=True), selection_report, selected


def _inner_selection_plan(train: pd.DataFrame, outer_fold) -> SimpleNamespace:
    """Build time-only inner folds strictly before one outer validation fold."""
    dates = tuple(sorted(train["trade_date"].dropna().astype(str).unique()))
    embargo = 20
    if len(dates) < 60:
        return SimpleNamespace(walk_forward=())
    validation_count = max(5, min(20, len(dates) // 8))
    folds = []
    for index, start in enumerate((len(dates) // 2, (len(dates) * 3) // 4), start=1):
        validation_start = start + embargo
        validation_end = min(validation_start + validation_count, len(dates))
        if start < 10 or validation_start >= validation_end:
            continue
        folds.append(
            type(outer_fold)(
                fold=index,
                training_dates=dates[:start],
                validation_dates=dates[validation_start:validation_end],
                training_symbols=tuple(sorted(train["symbol"].astype(str).unique())),
                train_start=dates[0],
                train_end=dates[start - 1],
                validation_start=dates[validation_start],
                validation_end=dates[validation_end - 1],
            )
        )
    return SimpleNamespace(walk_forward=tuple(folds))


def _ranker_oof(
    data,
    split_plan,
    features,
    params,
    seeds,
    *,
    dataset_cache=None,
    checkpoint_dir: str | Path | None = None,
    checkpoint_key: str = "ranker",
    checkpoint_contract: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    progress_total: int | None = None,
) -> pd.DataFrame:
    features = list(features)
    rows = []
    for fold in split_plan.walk_forward:
        train, outer_valid = _fold_data(data, fold)
        if train.empty or outer_valid.empty:
            continue
        checkpoint = _fold_checkpoint_path(
            checkpoint_dir,
            checkpoint_key,
            features,
            params,
            seeds,
            fold.fold,
            checkpoint_contract=checkpoint_contract,
        )
        if checkpoint is not None and checkpoint.is_file():
            cached = pd.read_parquet(checkpoint)
            _validate_fold_checkpoint(cached, outer_valid, fold.fold, "A_time_oof")
            rows.append(cached)
            _report_progress(on_progress, checkpoint_key, fold.fold, progress_total or len(split_plan.walk_forward), status="reused")
            continue
        fit_train, fit_valid = _inner_time_split(train)
        cache_key = (tuple(features), int(fold.fold))
        cached = None if dataset_cache is None else dataset_cache.get(cache_key)
        if cached is None:
            cached = _build_ranker_datasets(fit_train, fit_valid, features)
            if dataset_cache is not None:
                dataset_cache[cache_key] = cached
        train_set, validation_sets = cached
        scores = []
        for seed in seeds:
            model = _train_ranker(
                fit_train,
                features,
                params,
                seed,
                fit_valid,
                train_set=train_set,
                validation_sets=validation_sets,
            )
            scores.append(model.predict(outer_valid[features], num_iteration=_model_iteration(model)))
        result = outer_valid.assign(score=np.median(np.vstack(scores), axis=0), fold=fold.fold, quadrant="A_time_oof")
        if checkpoint is not None:
            _write_parquet_atomic(result, checkpoint)
        rows.append(result)
        _report_progress(on_progress, checkpoint_key, fold.fold, progress_total or len(split_plan.walk_forward), status="complete")
    if not rows:
        raise ValueError("walk-forward plan produced no OOF rows")
    return pd.concat(rows, ignore_index=True)


def _unseen_stock_oof(
    data,
    split_plan,
    features,
    params,
    seeds,
    *,
    dataset_cache=None,
    checkpoint_dir: str | Path | None = None,
    checkpoint_key: str = "unseen-stocks",
    checkpoint_contract: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
):
    """Score development validation dates for symbols excluded from A training."""
    features = list(features)
    unseen_symbols = set(split_plan.C_dev_unseen_symbols)
    if not unseen_symbols:
        return data.iloc[0:0].copy().assign(
            score=pd.Series(dtype=float), fold=pd.Series(dtype=int), quadrant=pd.Series(dtype=str)
        )
    rows = []
    for fold in split_plan.walk_forward:
        train = data.loc[data["trade_date"].isin(fold.training_dates) & data["symbol"].isin(fold.training_symbols)].copy()
        outer_valid = data.loc[data["trade_date"].isin(fold.validation_dates) & data["symbol"].isin(unseen_symbols)].copy()
        if train.empty or outer_valid.empty:
            continue
        checkpoint = _fold_checkpoint_path(
            checkpoint_dir,
            checkpoint_key,
            features,
            params,
            seeds,
            fold.fold,
            checkpoint_contract=checkpoint_contract,
        )
        if checkpoint is not None and checkpoint.is_file():
            cached = pd.read_parquet(checkpoint)
            _validate_fold_checkpoint(cached, outer_valid, fold.fold, "C_dev_unseen")
            rows.append(cached)
            _report_progress(on_progress, checkpoint_key, fold.fold, len(split_plan.walk_forward), status="reused")
            continue
        fit_train, fit_valid = _inner_time_split(train)
        cache_key = ("C_dev_unseen", tuple(features), int(fold.fold))
        cached = None if dataset_cache is None else dataset_cache.get(cache_key)
        if cached is None:
            cached = _build_ranker_datasets(fit_train, fit_valid, features)
            if dataset_cache is not None:
                dataset_cache[cache_key] = cached
        train_set, validation_sets = cached
        scores = []
        for seed in seeds:
            model = _train_ranker(
                fit_train,
                features,
                params,
                seed,
                fit_valid,
                train_set=train_set,
                validation_sets=validation_sets,
            )
            scores.append(model.predict(outer_valid[features], num_iteration=_model_iteration(model)))
        result = outer_valid.assign(score=np.median(np.vstack(scores), axis=0), fold=fold.fold, quadrant="C_dev_unseen")
        if checkpoint is not None:
            _write_parquet_atomic(result, checkpoint)
        rows.append(result)
        _report_progress(on_progress, checkpoint_key, fold.fold, len(split_plan.walk_forward), status="complete")
    if not rows:
        return data.iloc[0:0].copy().assign(
            score=pd.Series(dtype=float), fold=pd.Series(dtype=int), quadrant=pd.Series(dtype=str)
        )
    return pd.concat(rows, ignore_index=True)


def _inner_time_split(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Create a time-only early-stopping split inside an outer training window."""
    dates = tuple(sorted(train["trade_date"].dropna().unique()))
    if len(dates) < 22:
        return train.copy(), None
    validation_count = max(1, len(dates) // 5)
    validation_start = len(dates) - validation_count
    train_end = validation_start - 20
    if train_end <= 0:
        return train.copy(), None
    fit_dates = dates[:train_end]
    validation_dates = dates[validation_start:]
    fit_train = train.loc[train["trade_date"].isin(fit_dates)].copy()
    fit_valid = train.loc[train["trade_date"].isin(validation_dates)].copy()
    return fit_train, fit_valid if not fit_valid.empty else None


def _fold_checkpoint_path(
    checkpoint_dir: str | Path | None,
    checkpoint_key: str,
    features: list[str],
    params: dict[str, Any],
    seeds: tuple[int, ...],
    fold: int,
    *,
    checkpoint_contract: str | None = None,
) -> Path | None:
    if checkpoint_dir is None:
        return None
    payload = {
        "key": checkpoint_key,
        "features": features,
        "params": params,
        "seeds": list(seeds),
        "checkpoint_contract": checkpoint_contract,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]
    root = Path(checkpoint_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{checkpoint_key}-{digest}-fold-{int(fold):02d}.parquet"


def _selection_checkpoint_path(
    checkpoint_dir: str | Path | None,
    fold: int,
    *,
    checkpoint_contract: str | None = None,
) -> Path | None:
    if checkpoint_dir is None:
        return None
    root = Path(checkpoint_dir)
    root.mkdir(parents=True, exist_ok=True)
    contract_digest = hashlib.sha256(str(checkpoint_contract or "unbound").encode()).hexdigest()[:16]
    return root / f"nested-selection-{contract_digest}-fold-{int(fold):02d}.json"


def _development_checkpoint_contract(data, split_plan: SplitPlan, features, seeds, config: Any) -> str:
    """Bind resumable artifacts to the immutable inputs that determine their predictions."""
    required = ["trade_date", "symbol", "relevance_grade_10d"]
    columns = list(dict.fromkeys([*required, *features]))
    missing = sorted(set(columns) - set(data.columns))
    if missing:
        raise ValueError("development checkpoint contract missing columns: " + ", ".join(missing))
    digest = hashlib.sha256()
    for start in range(0, len(data), 10_000):
        chunk = data.loc[:, columns].iloc[start:start + 10_000]
        row_hashes = pd.util.hash_pandas_object(chunk, index=False, categorize=True).to_numpy(dtype="uint64")
        digest.update(row_hashes.tobytes())
    payload = {
        "schema_version": 1,
        "config_sha256": str(getattr(config, "sha256", "")),
        "split_sha256": split_plan.split_sha256,
        "features": list(features),
        "seeds": [int(seed) for seed in seeds],
        "signal_label_feature_sha256": digest.hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _write_json_atomic(value: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".selection-", suffix=".tmp", delete=False
    ) as temporary:
        temporary.write(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, default=str) + "\n")
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _validate_fold_checkpoint(cached: pd.DataFrame, expected: pd.DataFrame, fold: int, quadrant: str) -> None:
    required = {"trade_date", "symbol", "score", "fold", "quadrant"}
    if not required.issubset(cached.columns):
        raise ValueError("fold checkpoint is missing required columns")
    if not cached["fold"].eq(fold).all() or not cached["quadrant"].eq(quadrant).all():
        raise ValueError("fold checkpoint metadata does not match the requested fold")
    expected_keys = set(zip(expected["trade_date"].astype(str), expected["symbol"].astype(str)))
    cached_keys = set(zip(cached["trade_date"].astype(str), cached["symbol"].astype(str)))
    if cached_keys != expected_keys or len(cached) != len(expected):
        raise ValueError("fold checkpoint rows do not match the requested validation rows")


def _write_parquet_atomic(value: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fold-checkpoint-", dir=path.parent) as temporary:
        temporary_path = Path(temporary) / path.name
        value.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, path)


def _report_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    substep: str,
    fold: int,
    total_folds: int,
    *,
    status: str,
) -> None:
    if callback is None:
        return
    callback(
        {
            "substep": substep,
            "current_fold": int(fold),
            "total_folds": int(total_folds),
            "status": status,
        }
    )


def _model_iteration(model: Any) -> int | None:
    best_iteration = getattr(model, "best_iteration", None)
    if best_iteration:
        return best_iteration
    current_iteration = getattr(model, "current_iteration", None)
    return current_iteration() if callable(current_iteration) else None


def _seed_sensitivity(data, split_plan, features, params, seeds, *, dataset_cache=None) -> list[dict[str, Any]]:
    """Measure the frozen ranker configuration per fixed seed on the same OOF rows."""
    result = []
    for seed in seeds:
        predictions = _ranker_oof(data, split_plan, features, params, (seed,), dataset_cache=dataset_cache)
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


def _build_ranker_datasets(train, valid, features):
    features = list(features)
    ordered = train.sort_values(["trade_date", "symbol"], kind="stable")
    groups = ordered.groupby("trade_date", sort=True).size().tolist()
    train_set = lgb.Dataset(
        ordered[features],
        label=pd.to_numeric(ordered["relevance_grade_10d"], errors="coerce").fillna(0),
        group=groups,
        free_raw_data=False,
    )
    validation_sets = []
    if valid is not None and not valid.empty:
        validation = valid.sort_values(["trade_date", "symbol"], kind="stable")
        validation_sets = [
            lgb.Dataset(
                validation[features],
                label=pd.to_numeric(validation["relevance_grade_10d"], errors="coerce").fillna(0),
                group=validation.groupby("trade_date", sort=True).size().tolist(),
                reference=train_set,
                free_raw_data=False,
            )
        ]
    train_set.construct()
    for validation_set in validation_sets:
        validation_set.construct()
    return train_set, validation_sets


def _train_ranker(train, features, params, seed, valid=None, *, train_set=None, validation_sets=None):
    features = list(features)
    if train_set is None:
        train_set, default_validation_sets = _build_ranker_datasets(train, valid, features)
        validation_sets = default_validation_sets
    validation_sets = validation_sets or []
    model = lgb.train(
        {"objective": "lambdarank", "metric": ["ndcg"], "ndcg_eval_at": [5, 10], "learning_rate": 0.03, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "verbosity": -1, "seed": seed, "feature_fraction_seed": seed, "bagging_seed": seed, **params},
        train_set,
        num_boost_round=120,
        valid_sets=validation_sets or None,
        callbacks=[lgb.early_stopping(100, verbose=False)] if validation_sets else [],
    )
    return model


def _fold_metrics(predictions):
    return [evaluate_ranking(rows) for _, rows in predictions.groupby("fold", sort=True)]


def _classifier_oof(
    data,
    split_plan,
    features,
    label,
    params,
    seeds,
    *,
    checkpoint_dir: str | Path | None = None,
    checkpoint_key: str = "classifier",
    checkpoint_contract: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
):
    features = list(features)
    raw_rows = []
    for fold in split_plan.walk_forward:
        train, valid = _fold_data(data, fold)
        if train.empty or valid.empty:
            continue
        checkpoint = _fold_checkpoint_path(
            checkpoint_dir,
            checkpoint_key,
            features,
            params,
            seeds,
            fold.fold,
            checkpoint_contract=checkpoint_contract,
        )
        if checkpoint is not None and checkpoint.is_file():
            cached = pd.read_parquet(checkpoint)
            required = {"trade_date", "symbol", label, "raw_probability", "fold"}
            if not required.issubset(cached.columns) or not cached["fold"].eq(fold.fold).all():
                raise ValueError("classifier fold checkpoint metadata is invalid")
            expected_keys = set(zip(valid["trade_date"].astype(str), valid["symbol"].astype(str)))
            cached_keys = set(zip(cached["trade_date"].astype(str), cached["symbol"].astype(str)))
            if cached_keys != expected_keys or len(cached) != len(valid):
                raise ValueError("classifier fold checkpoint rows do not match validation rows")
            raw_rows.append(cached)
            _report_progress(on_progress, checkpoint_key, fold.fold, len(split_plan.walk_forward), status="reused")
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
        result = valid[["trade_date", "symbol", label]].assign(raw_probability=probability, fold=fold.fold)
        if checkpoint is not None:
            _write_parquet_atomic(result, checkpoint)
        raw_rows.append(result)
        _report_progress(on_progress, checkpoint_key, fold.fold, len(split_plan.walk_forward), status="complete")
    raw = pd.concat(raw_rows, ignore_index=True)
    calibrated_parts = []
    cross_fitted_brier = []
    for fold in sorted(raw["fold"].unique()):
        current = raw.loc[raw["fold"].eq(fold)]
        history = raw.loc[raw["fold"].lt(fold)]
        if history.empty or history[label].nunique() < 2:
            calibrated_fold = np.clip(current["raw_probability"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        else:
            _, history_report = _calibrate_oof(
                history["raw_probability"].to_numpy(), history[label].astype(bool).astype(int).to_numpy()
            )
            calibrated_fold = _apply_calibrator(current["raw_probability"].to_numpy(), history_report)
        calibrated_parts.append(pd.Series(calibrated_fold, index=current.index))
        cross_fitted_brier.extend(
            (calibrated_fold - current[label].astype(bool).astype(int).to_numpy()) ** 2
        )
    calibrated = pd.concat(calibrated_parts).sort_index().to_numpy(dtype=float)
    # Fit one final calibrator on all development OOF rows for the future
    # holdout contract. Its own fit metric is diagnostic only; the acceptance
    # metric above is the cross-fitted score.
    _, report = _calibrate_oof(raw["raw_probability"].to_numpy(), raw[label].astype(bool).astype(int).to_numpy())
    report["cross_fitted_brier"] = float(np.mean(cross_fitted_brier)) if cross_fitted_brier else None
    report["calibration_selection"] = "prior_outer_folds_only"
    # The classifier loop visits the same fold validation rows in the same stable
    # order as the ranker OOF loop. Re-training a ranker only to align keys
    # multiplied the full-market runtime without adding information.
    return calibrated.astype(float), report


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


def _run_group_ablations(
    data,
    split_plan,
    features,
    params,
    seeds,
    *,
    dataset_cache=None,
    checkpoint_dir: str | Path | None = None,
    checkpoint_contract: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    baseline_prediction: pd.DataFrame | None = None,
):
    report = []
    if baseline_prediction is None:
        baseline_prediction = _ranker_oof(
            data,
            split_plan,
            features,
            params,
            seeds,
            dataset_cache=dataset_cache,
            checkpoint_dir=checkpoint_dir,
            checkpoint_key="ablation-all-features",
            checkpoint_contract=checkpoint_contract,
            on_progress=on_progress,
        )
    baseline_metrics = evaluate_ranking(baseline_prediction)
    for group in _GROUP_SEQUENCE:
        group_features = [feature for feature in features if _training_group(feature) == group]
        available = bool(group_features)
        if not available:
            report.append({"group": group, "status": "unavailable", "reason": "missing_features_or_audit_gate"})
            continue
        trial_features = tuple(feature for feature in features if _training_group(feature) != group)
        if not trial_features:
            report.append({"group": group, "status": "unavailable", "reason": "leave_one_group_out_has_no_features"})
            continue
        # Ablations are diagnostics, not a second model-selection loop.  Reusing
        # the frozen candidate parameters keeps the comparison bounded and
        # avoids selecting against the same outer OOF rows twice.
        trial_params = dict(params)
        tuning = []
        prediction = _ranker_oof(
            data,
            split_plan,
            trial_features,
            trial_params,
            seeds,
            dataset_cache=dataset_cache,
            checkpoint_dir=checkpoint_dir,
            checkpoint_key=f"ablation-without-{group}",
            checkpoint_contract=checkpoint_contract,
            on_progress=on_progress,
        )
        metrics = evaluate_ranking(prediction)
        portfolio = _portfolio_or_empty(prediction)
        removal_is_better = (
            metrics["ndcg_at_10"] > baseline_metrics["ndcg_at_10"]
            and metrics["precision_at_5"] >= baseline_metrics["precision_at_5"]
        )
        status = "rejected" if removal_is_better else "accepted"
        report.append(
            {
                "group": group,
                "status": status,
                "comparison": "all_features_vs_leave_one_group_out",
                "features": group_features,
                "without_group_features": list(trial_features),
                "all_features_metrics": baseline_metrics,
                "metrics": metrics,
                "portfolio": portfolio,
                "selected_params": trial_params,
                "retuned_grid": tuning,
            }
        )
    return report


def _select_ranker_params(data, split_plan, features, seeds, *, dataset_cache=None):
    reports = []
    for params in FIXED_RANKER_GRID:
        predictions = _ranker_oof(data, split_plan, features, params, seeds, dataset_cache=dataset_cache)
        metrics = evaluate_ranking(predictions)
        fold_metrics = _fold_metrics(predictions)
        reports.append(
            {
                "params": dict(params),
                "metrics": metrics,
                "median_fold_ndcg_at_10": median(row["ndcg_at_10"] for row in fold_metrics),
                "median_fold_precision_at_5": median(row["precision_at_5"] for row in fold_metrics),
            }
        )
    selected = max(reports, key=lambda row: (row["median_fold_ndcg_at_10"], row["median_fold_precision_at_5"], -row["params"]["min_data_in_leaf"]))
    return dict(selected["params"]), reports


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
    execution_contracts = (
        {"entry_price", "exit_price", "exit_trade_date"},
        {"entry_price_10d", "exit_price_10d", "exit_trade_date_10d"},
        {"adjusted_next_open", "adjusted_exit_close", "exit_trade_date"},
    )
    if any(contract.issubset(predictions.columns) for contract in execution_contracts):
        return simulate_daily_topk_portfolio(predictions)
    return {"maximum_drawdown": 0.0}


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
