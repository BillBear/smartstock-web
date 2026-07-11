"""Development-only, OOF-gated candidate training for full-market ML research."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from statistics import median
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .evaluator import evaluate_ranking, simulate_daily_topk_portfolio
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
    preliminary_status: str
    failed_gates: list[str]
    fixed_ranker_grid: tuple[dict[str, int], ...]
    seeds: tuple[int, ...]
    risk_alphas: tuple[float, ...]
    selected_risk_alpha: float
    group_ablations: list[dict[str, Any]]
    selected_features: tuple[str, ...]


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
        preliminary_status="research_only_failed_gate" if failed_gates else "research_only_candidate",
        failed_gates=failed_gates,
        fixed_ranker_grid=FIXED_RANKER_GRID,
        seeds=seeds,
        risk_alphas=RISK_ALPHAS,
        selected_risk_alpha=risk_selected["alpha"],
        group_ablations=group_ablations,
        selected_features=selected_features,
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
        return calibrated, {"selected": "constant", "brier": float(np.mean((calibrated - labels) ** 2)), "source": "A_walk_forward_oof"}
    sigmoid = LogisticRegression(random_state=17, solver="liblinear").fit(clipped.reshape(-1, 1), labels).predict_proba(clipped.reshape(-1, 1))[:, 1]
    isotonic = IsotonicRegression(out_of_bounds="clip").fit_transform(clipped, labels)
    sigmoid_brier = float(np.mean((sigmoid - labels) ** 2))
    isotonic_brier = float(np.mean((isotonic - labels) ** 2))
    selected, calibrated = ("sigmoid", sigmoid) if sigmoid_brier <= isotonic_brier else ("isotonic", isotonic)
    return calibrated, {"selected": selected, "brier": min(sigmoid_brier, isotonic_brier), "sigmoid_brier": sigmoid_brier, "isotonic_brier": isotonic_brier, "source": "A_walk_forward_oof"}


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
