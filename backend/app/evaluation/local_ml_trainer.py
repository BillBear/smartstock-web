from __future__ import annotations

import json
import importlib
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.evaluation.ml_splits import build_ml_split_plan


def train_local_models(
    df: pd.DataFrame,
    feature_names: List[str],
    label_col: str,
    return_col: str,
    split_plan: Optional[Dict[str, Any]] = None,
    random_state: int = 20260704,
    artifact_dir: str | Path | None = None,
    model_metadata: Optional[Dict[str, Any]] = None,
    prediction_output_path: str | Path | None = None,
    candidate_set: str = "default",
) -> Dict[str, Any]:
    if df is None or df.empty:
        raise ValueError("local ML training requires a non-empty dataset")
    if not feature_names:
        raise ValueError("local ML training requires feature names")

    local = df.copy()
    local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local = local[local["date"].notna()].sort_values(["date", "symbol"]).reset_index(drop=True)
    split_plan = split_plan or build_ml_split_plan(local)
    train_df, final_holdout_df, stock_holdout_df = _split_dataset(local, split_plan)
    if train_df.empty:
        raise ValueError("local ML split produced an empty training set")

    candidates = _candidate_factories(random_state, candidate_set=candidate_set)
    models: Dict[str, Any] = {}
    best_model = None
    best_model_obj = None
    best_score = (-1.0, -1.0)
    for name, factory in candidates.items():
        try:
            model = factory(train_df[label_col].astype(int).to_numpy())
            _fit_model(model, _x(train_df, feature_names), train_df[label_col].astype(int))
            final_metrics = _evaluate_model(model, final_holdout_df, feature_names, label_col, return_col)
            stock_metrics = _evaluate_model(model, stock_holdout_df, feature_names, label_col, return_col)
            walk_metrics = _walk_forward_metrics(
                local,
                split_plan,
                factory,
                feature_names,
                label_col,
                return_col,
            )
            models[name] = {
                "status": "trained",
                "final_holdout": final_metrics,
                "stock_holdout": stock_metrics,
                "walk_forward": walk_metrics,
                "feature_importance": _extract_feature_importance(model, feature_names),
            }
            score = (
                float(final_metrics.get("precision_at_5") or 0.0),
                float(stock_metrics.get("precision_at_5") or 0.0),
                float(walk_metrics.get("precision_at_5") or 0.0),
                float(final_metrics.get("ndcg_at_10") or 0.0),
            )
            if score > best_score:
                best_score = score
                best_model = name
                best_model_obj = model
        except Exception as exc:
            models[name] = {
                "status": "skipped",
                "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
            }

    if best_model is None:
        raise ValueError("no local ML model candidate could be trained")

    if prediction_output_path:
        _write_holdout_predictions(
            Path(prediction_output_path),
            model=best_model_obj,
            final_holdout_df=final_holdout_df,
            stock_holdout_df=stock_holdout_df,
            feature_names=feature_names,
            label_col=label_col,
            return_col=return_col,
        )

    result = {
        "production_enabled": False,
        "status": "paper_only",
        "best_model": best_model,
        "models": models,
        "split_summary": _split_summary(split_plan),
    }
    if artifact_dir:
        result["artifact"] = _save_best_model_artifact(
            artifact_dir=Path(artifact_dir),
            model=best_model_obj,
            metadata={
                **(model_metadata or {}),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "best_model": best_model,
                "feature_names": feature_names,
                "label_col": label_col,
                "return_col": return_col,
                "production_enabled": False,
                "status": "paper_only",
                "split_summary": result["split_summary"],
                "metrics": models.get(best_model) or {},
            },
        )
    return result


def _candidate_factories(random_state: int, candidate_set: str = "default") -> Dict[str, Callable[[np.ndarray], Any]]:
    factories: Dict[str, Callable[[np.ndarray], Any]] = {
        "logistic_baseline": lambda y: _make_logistic(y, random_state),
        "decision_tree_shallow": lambda y: _make_decision_tree(y, random_state),
        "scorecard_baseline": lambda y: _make_scorecard(y, random_state),
    }
    if str(candidate_set or "default") != "core_v2":
        factories.update({
        "sklearn_hist_gradient_boosting": lambda y: _make_hist_gradient_boosting(y, random_state),
        "xgboost_classifier": lambda y: _make_xgboost(y, random_state),
        "lightgbm_classifier": lambda y: _make_lightgbm(y, random_state),
        })
    return factories


def _make_logistic(y: np.ndarray, random_state: int):
    from sklearn.dummy import DummyClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    model = (
        DummyClassifier(strategy="prior")
        if len(set(y.tolist())) < 2
        else LogisticRegression(max_iter=800, class_weight="balanced", random_state=random_state, solver="liblinear")
    )
    return Pipeline([("scaler", StandardScaler()), ("model", model)])


def _make_hist_gradient_boosting(y: np.ndarray, random_state: int):
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import HistGradientBoostingClassifier

    if len(set(y.tolist())) < 2:
        return DummyClassifier(strategy="prior")
    return HistGradientBoostingClassifier(
        max_iter=120,
        learning_rate=0.06,
        max_leaf_nodes=31,
        random_state=random_state,
    )


def _make_decision_tree(y: np.ndarray, random_state: int):
    from sklearn.dummy import DummyClassifier
    from sklearn.tree import DecisionTreeClassifier

    if len(set(y.tolist())) < 2:
        return DummyClassifier(strategy="prior")
    return DecisionTreeClassifier(
        max_depth=4,
        min_samples_leaf=max(20, int(len(y) * 0.01)),
        class_weight="balanced",
        random_state=random_state,
    )


def _make_scorecard(y: np.ndarray, random_state: int):
    if len(set(y.tolist())) < 2:
        from sklearn.dummy import DummyClassifier

        return DummyClassifier(strategy="prior")
    return SimpleScorecardClassifier(random_state=random_state)


def _make_xgboost(y: np.ndarray, random_state: int):
    module = importlib.import_module("xgboost")
    if len(set(y.tolist())) < 2:
        from sklearn.dummy import DummyClassifier

        return DummyClassifier(strategy="prior")
    return module.XGBClassifier(
        n_estimators=120,
        max_depth=3,
        learning_rate=0.06,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=random_state,
    )


def _make_lightgbm(y: np.ndarray, random_state: int):
    module = importlib.import_module("lightgbm")
    if len(set(y.tolist())) < 2:
        from sklearn.dummy import DummyClassifier

        return DummyClassifier(strategy="prior")
    return module.LGBMClassifier(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.06,
        random_state=random_state,
        verbosity=-1,
    )


def _split_dataset(df: pd.DataFrame, split_plan: Dict[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    date_text = pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str)
    symbol_text = df["symbol"].astype(str)
    training_dates = set(str(item) for item in split_plan.get("training_dates") or [])
    training_symbols = set(str(item) for item in split_plan.get("training_symbols") or [])
    final_dates = set(str(item) for item in ((split_plan.get("final_holdout") or {}).get("dates") or []))
    holdout_symbols = set(str(item) for item in ((split_plan.get("stock_holdout") or {}).get("symbols") or []))
    train_mask = date_text.isin(training_dates) & symbol_text.isin(training_symbols)
    final_mask = date_text.isin(final_dates) & symbol_text.isin(training_symbols)
    stock_mask = date_text.isin(training_dates) & symbol_text.isin(holdout_symbols)
    return df.loc[train_mask].copy(), df.loc[final_mask].copy(), df.loc[stock_mask].copy()


def _walk_forward_metrics(
    df: pd.DataFrame,
    split_plan: Dict[str, Any],
    factory: Callable[[np.ndarray], Any],
    feature_names: List[str],
    label_col: str,
    return_col: str,
) -> Dict[str, Any]:
    windows = (split_plan.get("walk_forward") or {}).get("windows") or []
    frames = []
    for window in windows:
        train_dates = set(str(item) for item in window.get("train_dates") or [])
        validation_dates = set(str(item) for item in window.get("validation_dates") or [])
        training_symbols = set(str(item) for item in split_plan.get("training_symbols") or [])
        train = df[df["date"].isin(train_dates) & df["symbol"].astype(str).isin(training_symbols)].copy()
        validation = df[df["date"].isin(validation_dates) & df["symbol"].astype(str).isin(training_symbols)].copy()
        if train.empty or validation.empty:
            continue
        model = factory(train[label_col].astype(int).to_numpy())
        _fit_model(model, _x(train, feature_names), train[label_col].astype(int))
        scored = validation[[label_col, return_col]].copy()
        scored["date"] = validation["date"].astype(str)
        scored["_prob"] = _predict_class1(model, _x(validation, feature_names))
        frames.append(scored)
    if not frames:
        return _empty_metrics()
    combined = pd.concat(frames, ignore_index=True)
    return daily_ranking_metrics(
        combined,
        label_col=label_col,
        score_col="_prob",
        return_col=return_col,
        date_col="date",
    )


def _evaluate_model(
    model: Any,
    df: pd.DataFrame,
    feature_names: List[str],
    label_col: str,
    return_col: str,
) -> Dict[str, Any]:
    if df is None or df.empty:
        return _empty_metrics()
    y_true = df[label_col].astype(int).to_numpy()
    returns = df[return_col].astype(float).to_numpy()
    prob = _predict_class1(model, _x(df, feature_names))
    metrics = daily_ranking_metrics(
        df.assign(_prob=prob),
        label_col=label_col,
        score_col="_prob",
        return_col=return_col,
        date_col="date",
    )
    metrics.update(
        {
            "brier": _brier(y_true, prob),
            "ece": _ece(y_true, prob),
            "bucket_hit_rates": _bucket_hit_rates(y_true, prob),
        }
    )
    return metrics


def _ranking_metrics(y_true: np.ndarray, y_prob: np.ndarray, returns: np.ndarray) -> Dict[str, Any]:
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 0.001, 0.999)
    y_true = np.asarray(y_true, dtype=int)
    returns = np.asarray(returns, dtype=float)
    return {
        "sample_count": int(len(y_true)),
        "precision_at_3": _precision_at_k(y_true, y_prob, 3),
        "precision_at_5": _precision_at_k(y_true, y_prob, 5),
        "precision_at_10": _precision_at_k(y_true, y_prob, 10),
        "ndcg_at_10": _ndcg_at_k(y_true, y_prob, 10),
        "mrr": _mrr(y_true, y_prob),
        "brier": _brier(y_true, y_prob),
        "ece": _ece(y_true, y_prob),
        "topk_return": _topk_return(returns, y_prob, 5),
        "bucket_hit_rates": _bucket_hit_rates(y_true, y_prob),
    }


def daily_ranking_metrics(
    df: pd.DataFrame,
    label_col: str,
    score_col: str,
    return_col: str,
    date_col: str = "date",
) -> Dict[str, Any]:
    if df is None or df.empty:
        return _empty_metrics()
    local = df[[date_col, label_col, score_col, return_col]].copy()
    local[date_col] = pd.to_datetime(local[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    local[label_col] = pd.to_numeric(local[label_col], errors="coerce")
    local[score_col] = pd.to_numeric(local[score_col], errors="coerce")
    local[return_col] = pd.to_numeric(local[return_col], errors="coerce")
    local = local.dropna(subset=[date_col, label_col, score_col, return_col])
    if local.empty:
        return _empty_metrics()
    daily_values: Dict[str, List[float]] = {
        "precision_at_1": [],
        "precision_at_3": [],
        "precision_at_5": [],
        "precision_at_10": [],
        "ndcg_at_10": [],
        "mrr": [],
        "topk_return": [],
    }
    for _, rows in local.groupby(date_col):
        ordered = rows.sort_values(score_col, ascending=False)
        y_true = ordered[label_col].astype(int).to_numpy()
        returns = ordered[return_col].astype(float).to_numpy()
        scores = ordered[score_col].astype(float).to_numpy()
        for key, k in (("precision_at_1", 1), ("precision_at_3", 3), ("precision_at_5", 5), ("precision_at_10", 10)):
            daily_values[key].append(_precision_at_k(y_true, scores, k))
        daily_values["ndcg_at_10"].append(_ndcg_at_k(y_true, scores, 10))
        daily_values["mrr"].append(_mrr(y_true, scores))
        daily_values["topk_return"].append(_topk_return(returns, scores, 5))
    return {
        "sample_count": int(len(local)),
        "date_count": int(local[date_col].nunique()),
        "label_rate": round(float(local[label_col].mean()), 6),
        "precision_at_1": _mean(daily_values["precision_at_1"]),
        "precision_at_3": _mean(daily_values["precision_at_3"]),
        "precision_at_5": _mean(daily_values["precision_at_5"]),
        "precision_at_10": _mean(daily_values["precision_at_10"]),
        "ndcg_at_10": _mean(daily_values["ndcg_at_10"]),
        "mrr": _mean(daily_values["mrr"]),
        "topk_return": _mean(daily_values["topk_return"]),
        "brier": None,
        "ece": None,
        "bucket_hit_rates": [],
    }


def _empty_metrics() -> Dict[str, Any]:
    return {
        "sample_count": 0,
        "date_count": 0,
        "label_rate": 0.0,
        "precision_at_1": 0.0,
        "precision_at_3": 0.0,
        "precision_at_5": 0.0,
        "precision_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "mrr": 0.0,
        "brier": None,
        "ece": None,
        "topk_return": 0.0,
        "bucket_hit_rates": [],
    }


def _x(df: pd.DataFrame, feature_names: List[str]) -> pd.DataFrame:
    return df[feature_names].replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)


def _fit_model(model: Any, x: pd.DataFrame, y: pd.Series) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        model.fit(x, y)


def _predict_class1(model: Any, x: pd.DataFrame) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        prob = model.predict_proba(x)
    classes = list(getattr(model, "classes_", []))
    if not classes and hasattr(model, "named_steps"):
        classes = list(getattr(model.named_steps.get("model"), "classes_", [0, 1]))
    if 1 in classes:
        return np.asarray(prob[:, classes.index(1)], dtype=float)
    return np.zeros(len(x), dtype=float)


def _precision_at_k(y_true: np.ndarray, y_prob: np.ndarray, k: int) -> float:
    if len(y_true) == 0:
        return 0.0
    top_k = max(1, min(int(k), len(y_true)))
    order = np.argsort(y_prob)[::-1][:top_k]
    return round(float(np.mean(y_true[order])), 6)


def _ndcg_at_k(y_true: np.ndarray, y_prob: np.ndarray, k: int) -> float:
    if len(y_true) == 0:
        return 0.0
    top_k = max(1, min(int(k), len(y_true)))
    order = np.argsort(y_prob)[::-1][:top_k]
    ideal = np.argsort(y_true)[::-1][:top_k]
    dcg = _dcg(y_true[order])
    idcg = _dcg(y_true[ideal])
    return round(float(dcg / idcg), 6) if idcg else 0.0


def _dcg(gains: np.ndarray) -> float:
    return float(np.sum((2**gains - 1) / np.log2(np.arange(len(gains)) + 2)))


def _mrr(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    order = np.argsort(y_prob)[::-1]
    for rank, index in enumerate(order, start=1):
        if y_true[index] == 1:
            return round(float(1.0 / rank), 6)
    return 0.0


def _brier(y_true: np.ndarray, y_prob: np.ndarray) -> Optional[float]:
    try:
        from sklearn.metrics import brier_score_loss

        return round(float(brier_score_loss(y_true, y_prob)), 6)
    except Exception:
        return None


def _ece(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 10) -> float:
    if len(y_true) == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (y_prob >= left) & (y_prob < right if right < 1 else y_prob <= right)
        if not np.any(mask):
            continue
        ece += float(np.mean(mask)) * abs(float(np.mean(y_true[mask])) - float(np.mean(y_prob[mask])))
    return round(ece, 6)


def _topk_return(returns: np.ndarray, y_prob: np.ndarray, k: int) -> float:
    if len(returns) == 0:
        return 0.0
    top_k = max(1, min(int(k), len(returns)))
    order = np.argsort(y_prob)[::-1][:top_k]
    return round(float(np.mean(returns[order])), 6)


def _bucket_hit_rates(y_true: np.ndarray, y_prob: np.ndarray) -> List[Dict[str, Any]]:
    buckets = [(0.8, 1.01), (0.65, 0.8), (0.5, 0.65), (0.35, 0.5), (0.0, 0.35)]
    result = []
    for low, high in buckets:
        mask = (y_prob >= low) & (y_prob < high)
        count = int(np.sum(mask))
        result.append(
            {
                "min_prob": low,
                "max_prob": high,
                "sample_count": count,
                "hit_rate": round(float(np.mean(y_true[mask])), 6) if count else 0.0,
            }
        )
    return result


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(float(np.mean(values)), 6)


def _extract_feature_importance(model: Any, feature_names: List[str]) -> List[Dict[str, Any]]:
    estimator = model
    if hasattr(model, "named_steps"):
        estimator = model.named_steps.get("model") or model
    values = None
    if hasattr(estimator, "feature_importances_"):
        values = getattr(estimator, "feature_importances_")
    elif hasattr(estimator, "coef_"):
        values = np.ravel(getattr(estimator, "coef_"))
    elif hasattr(estimator, "feature_scores_"):
        values = getattr(estimator, "feature_scores_")
    if values is None:
        return []
    rows = []
    for feature, value in zip(feature_names, values):
        rows.append({"feature": feature, "importance": round(float(abs(value)), 6)})
    return sorted(rows, key=lambda item: item["importance"], reverse=True)


class SimpleScorecardClassifier:
    """Small interpretable scorecard baseline for offline local ML experiments."""

    def __init__(self, random_state: int = 0):
        self.random_state = random_state
        self.feature_names_in_: List[str] = []
        self.feature_scores_: np.ndarray = np.array([])
        self.medians_: np.ndarray = np.array([])
        self.scales_: np.ndarray = np.array([])
        self.intercept_: float = 0.0
        self.classes_ = np.array([0, 1])

    def fit(self, x: pd.DataFrame, y: pd.Series):
        local = pd.DataFrame(x).astype(float)
        target = pd.Series(y).astype(int).reset_index(drop=True)
        self.feature_names_in_ = [str(column) for column in local.columns]
        self.medians_ = local.median().fillna(0.0).to_numpy(dtype=float)
        q75 = local.quantile(0.75)
        q25 = local.quantile(0.25)
        self.scales_ = (q75 - q25).replace(0, np.nan).fillna(local.std().replace(0, np.nan)).fillna(1.0).to_numpy(dtype=float)
        weights = []
        for column in local.columns:
            corr = local[column].corr(target, method="spearman")
            weights.append(0.0 if pd.isna(corr) else float(corr))
        weights_array = np.asarray(weights, dtype=float)
        if np.sum(np.abs(weights_array)) > 0:
            weights_array = weights_array / np.sum(np.abs(weights_array))
        self.feature_scores_ = weights_array
        positive_rate = min(0.99, max(0.01, float(target.mean())))
        self.intercept_ = float(np.log(positive_rate / (1.0 - positive_rate)))
        return self

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        local = pd.DataFrame(x).astype(float)
        values = local.to_numpy(dtype=float)
        z = (values - self.medians_) / self.scales_
        score = self.intercept_ + np.dot(z, self.feature_scores_) * 2.5
        prob = 1.0 / (1.0 + np.exp(-np.clip(score, -20, 20)))
        return np.column_stack([1.0 - prob, prob])


def _split_summary(split_plan: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "training_dates": list(split_plan.get("training_dates") or []),
        "training_symbols": list(split_plan.get("training_symbols") or []),
        "final_holdout_dates": list((split_plan.get("final_holdout") or {}).get("dates") or []),
        "stock_holdout_symbols": list((split_plan.get("stock_holdout") or {}).get("symbols") or []),
    }


def _write_holdout_predictions(
    path: Path,
    model: Any,
    final_holdout_df: pd.DataFrame,
    stock_holdout_df: pd.DataFrame,
    feature_names: List[str],
    label_col: str,
    return_col: str,
) -> None:
    if model is None:
        raise ValueError("cannot write local ML predictions without a trained best model")
    frames = [
        _prediction_frame(model, final_holdout_df, feature_names, label_col, return_col, "final_holdout"),
        _prediction_frame(model, stock_holdout_df, feature_names, label_col, return_col, "stock_holdout"),
    ]
    output = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False)


def _prediction_frame(
    model: Any,
    df: pd.DataFrame,
    feature_names: List[str],
    label_col: str,
    return_col: str,
    split_name: str,
) -> pd.DataFrame:
    columns = [
        "split",
        "date",
        "symbol",
        "name",
        "label",
        "future_return_pct",
        "probability",
        "is_false_positive",
        "is_false_negative",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    local = df.copy()
    probability = _predict_class1(model, _x(local, feature_names))
    result = pd.DataFrame(
        {
            "split": split_name,
            "date": local["date"].astype(str),
            "symbol": local["symbol"].astype(str),
            "name": local["name"].astype(str) if "name" in local.columns else local["symbol"].astype(str),
            "label": local[label_col].astype(int),
            "future_return_pct": local[return_col].astype(float),
            "probability": probability,
        }
    )
    result["is_false_positive"] = (result["probability"] >= 0.65) & (result["label"] == 0)
    result["is_false_negative"] = (result["probability"] < 0.35) & (result["label"] == 1)
    return result.sort_values(["split", "probability", "date", "symbol"], ascending=[True, False, True, True]).reset_index(drop=True)


def _save_best_model_artifact(artifact_dir: Path, model: Any, metadata: Dict[str, Any]) -> Dict[str, Any]:
    if model is None:
        raise ValueError("cannot save local ML artifact without a trained best model")
    try:
        import joblib
    except Exception as exc:
        raise RuntimeError("saving local ML artifacts requires joblib") from exc

    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "model.joblib"
    metadata_path = artifact_dir / "metadata.json"
    joblib.dump(model, model_path)
    metadata_path.write_text(json.dumps(_json_safe(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "artifact_dir": str(artifact_dir),
        "model_path": str(model_path),
        "metadata_path": str(metadata_path),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.ndarray,)):
        return [_json_safe(item) for item in value.tolist()]
    return value
