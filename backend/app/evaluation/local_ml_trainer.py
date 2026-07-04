from __future__ import annotations

import importlib
import warnings
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

    candidates = _candidate_factories(random_state)
    models: Dict[str, Any] = {}
    best_model = None
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
            }
            score = (float(final_metrics.get("precision_at_5") or 0.0), float(final_metrics.get("ndcg_at_10") or 0.0))
            if score > best_score:
                best_score = score
                best_model = name
        except Exception as exc:
            models[name] = {
                "status": "skipped",
                "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
            }

    if best_model is None:
        raise ValueError("no local ML model candidate could be trained")

    return {
        "production_enabled": False,
        "status": "paper_only",
        "best_model": best_model,
        "models": models,
        "split_summary": _split_summary(split_plan),
    }


def _candidate_factories(random_state: int) -> Dict[str, Callable[[np.ndarray], Any]]:
    factories: Dict[str, Callable[[np.ndarray], Any]] = {
        "logistic_baseline": lambda y: _make_logistic(y, random_state),
        "sklearn_hist_gradient_boosting": lambda y: _make_hist_gradient_boosting(y, random_state),
        "xgboost_classifier": lambda y: _make_xgboost(y, random_state),
        "lightgbm_classifier": lambda y: _make_lightgbm(y, random_state),
    }
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
        scored["_prob"] = _predict_class1(model, _x(validation, feature_names))
        frames.append(scored)
    if not frames:
        return _empty_metrics()
    combined = pd.concat(frames, ignore_index=True)
    return _ranking_metrics(
        combined[label_col].astype(int).to_numpy(),
        combined["_prob"].to_numpy(dtype=float),
        combined[return_col].to_numpy(dtype=float),
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
    return _ranking_metrics(y_true, prob, returns)


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


def _empty_metrics() -> Dict[str, Any]:
    return {
        "sample_count": 0,
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


def _split_summary(split_plan: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "training_dates": list(split_plan.get("training_dates") or []),
        "training_symbols": list(split_plan.get("training_symbols") or []),
        "final_holdout_dates": list((split_plan.get("final_holdout") or {}).get("dates") or []),
        "stock_holdout_symbols": list((split_plan.get("stock_holdout") or {}).get("symbols") or []),
    }
