from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd


def diagnose_feature_effectiveness(
    df: pd.DataFrame,
    feature_names: Iterable[str],
    label_col: str,
    return_col: str,
    date_col: str = "date",
    split_col: str = "split",
    max_depth: int = 3,
    min_samples_leaf: int = 50,
    random_state: int = 42,
) -> Dict[str, Any]:
    """Diagnose feature usefulness with daily-ranking metrics.

    This is intentionally offline/read-only. It evaluates whether features can
    separate future winners inside each daily cross-section, which matches the
    recommender use case better than a global top-k metric.
    """

    feature_list = [str(item) for item in feature_names or []]
    if df is None or df.empty:
        return {
            "row_count": 0,
            "feature_count": len(feature_list),
            "warnings": ["empty_dataset"],
            "tree": {"status": "skipped", "reason": "empty_dataset"},
            "permutation_importance": {"final_holdout": [], "stock_holdout": []},
            "daily_univariate": {},
            "correlation_pairs": [],
        }

    local = df.copy()
    local[date_col] = pd.to_datetime(local[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    local[label_col] = pd.to_numeric(local[label_col], errors="coerce")
    local[return_col] = pd.to_numeric(local[return_col], errors="coerce")
    local = local[local[date_col].notna()].copy()

    present_features = [feature for feature in feature_list if feature in local.columns]
    warnings: List[str] = []
    missing_features = [feature for feature in feature_list if feature not in local.columns]
    if missing_features:
        warnings.append("missing_features")

    for feature in present_features:
        local[feature] = pd.to_numeric(local[feature], errors="coerce")

    daily_univariate = {
        feature: _daily_univariate_metrics(local, feature, label_col, return_col, date_col)
        for feature in present_features
    }
    correlation_pairs = _correlation_pairs(local, present_features)

    tree_report: Dict[str, Any] = {"status": "skipped", "reason": "insufficient_data"}
    permutation_report: Dict[str, List[Dict[str, Any]]] = {"final_holdout": [], "stock_holdout": []}

    if split_col not in local.columns:
        warnings.append("missing_split_column")
        return {
            "row_count": int(len(local)),
            "feature_count": len(present_features),
            "missing_features": missing_features,
            "warnings": sorted(set(warnings)),
            "tree": tree_report,
            "permutation_importance": permutation_report,
            "daily_univariate": daily_univariate,
            "correlation_pairs": correlation_pairs,
        }

    train = _clean_model_frame(local[local[split_col].astype(str) == "train"], present_features, label_col)
    holdouts = {
        "final_holdout": _clean_model_frame(local[local[split_col].astype(str) == "final_holdout"], present_features, label_col),
        "stock_holdout": _clean_model_frame(local[local[split_col].astype(str) == "stock_holdout"], present_features, label_col),
    }
    if not present_features:
        warnings.append("no_numeric_features")
    if train.empty or len(set(train[label_col].astype(int).tolist())) < 2:
        warnings.append("insufficient_train_classes")
    if all(frame.empty for frame in holdouts.values()):
        warnings.append("missing_holdout_split")

    has_holdout = any(not frame.empty for frame in holdouts.values())
    if present_features and has_holdout and not train.empty and len(set(train[label_col].astype(int).tolist())) >= 2:
        tree_report, permutation_report = _fit_tree_diagnostic(
            train=train,
            holdouts=holdouts,
            feature_names=present_features,
            label_col=label_col,
            return_col=return_col,
            date_col=date_col,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            random_state=random_state,
        )
        if tree_report.get("status") == "skipped":
            warnings.append(str(tree_report.get("reason") or "tree_skipped"))

    return {
        "audit_type": "ml_feature_effectiveness",
        "row_count": int(len(local)),
        "feature_count": len(present_features),
        "missing_features": missing_features,
        "warnings": sorted(set(warnings)),
        "tree": tree_report,
        "permutation_importance": permutation_report,
        "daily_univariate": daily_univariate,
        "correlation_pairs": correlation_pairs,
    }


def _fit_tree_diagnostic(
    train: pd.DataFrame,
    holdouts: Dict[str, pd.DataFrame],
    feature_names: List[str],
    label_col: str,
    return_col: str,
    date_col: str,
    max_depth: int,
    min_samples_leaf: int,
    random_state: int,
) -> tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    try:
        from sklearn.inspection import permutation_importance
        from sklearn.metrics import make_scorer, roc_auc_score
        from sklearn.tree import DecisionTreeClassifier, export_text
    except Exception as exc:  # pragma: no cover - depends on local env
        return (
            {"status": "skipped", "reason": "sklearn_unavailable", "error": str(exc)},
            {"final_holdout": [], "stock_holdout": []},
        )

    x_train, medians = _feature_matrix(train, feature_names)
    y_train = train[label_col].astype(int)
    model = DecisionTreeClassifier(
        max_depth=max(1, int(max_depth)),
        min_samples_leaf=max(1, int(min_samples_leaf)),
        class_weight="balanced",
        random_state=int(random_state),
    )
    model.fit(x_train, y_train)

    tree_report: Dict[str, Any] = {
        "status": "trained",
        "max_depth": int(max_depth),
        "min_samples_leaf": int(min_samples_leaf),
        "rules": export_text(model, feature_names=feature_names),
        "train": _evaluate_scored_frame(train, model.predict_proba(x_train)[:, 1], label_col, return_col, date_col),
    }
    permutation_report: Dict[str, List[Dict[str, Any]]] = {"final_holdout": [], "stock_holdout": []}

    def auc_scorer(y_true: Sequence[int], y_score: Sequence[float]) -> float:
        if len(set(np.asarray(y_true, dtype=int).tolist())) < 2:
            return 0.0
        return float(roc_auc_score(y_true, y_score))

    scorer = make_scorer(auc_scorer, response_method="predict_proba")
    for split_name, split_df in holdouts.items():
        if split_df.empty:
            tree_report[split_name] = _empty_daily_metrics()
            continue
        x_holdout, _ = _feature_matrix(split_df, feature_names, medians)
        scores = model.predict_proba(x_holdout)[:, 1]
        tree_report[split_name] = _evaluate_scored_frame(split_df, scores, label_col, return_col, date_col)
        if len(set(split_df[label_col].astype(int).tolist())) < 2:
            continue
        importance = permutation_importance(
            model,
            x_holdout,
            split_df[label_col].astype(int),
            scoring=scorer,
            n_repeats=5,
            random_state=int(random_state),
        )
        items = []
        for idx, feature in enumerate(feature_names):
            items.append(
                {
                    "feature": feature,
                    "importance_mean": round(float(importance.importances_mean[idx]), 6),
                    "importance_std": round(float(importance.importances_std[idx]), 6),
                }
            )
        permutation_report[split_name] = sorted(items, key=lambda item: item["importance_mean"], reverse=True)

    return tree_report, permutation_report


def _clean_model_frame(df: pd.DataFrame, feature_names: List[str], label_col: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    local = df.copy()
    local[label_col] = pd.to_numeric(local[label_col], errors="coerce")
    for feature in feature_names:
        local[feature] = pd.to_numeric(local[feature], errors="coerce")
    return local.dropna(subset=[label_col]).copy()


def _feature_matrix(
    df: pd.DataFrame,
    feature_names: List[str],
    medians: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    x = df[feature_names].replace([np.inf, -np.inf], np.nan).astype(float)
    if medians is None:
        medians = x.median(numeric_only=True).fillna(0.0)
    return x.fillna(medians).fillna(0.0), medians


def _evaluate_scored_frame(
    df: pd.DataFrame,
    scores: Sequence[float],
    label_col: str,
    return_col: str,
    date_col: str,
) -> Dict[str, Any]:
    local = df[[date_col, label_col, return_col]].copy()
    local["_score"] = np.asarray(scores, dtype=float)
    return _daily_ranking_metrics(local, "_score", label_col, return_col, date_col)


def _daily_univariate_metrics(
    df: pd.DataFrame,
    feature: str,
    label_col: str,
    return_col: str,
    date_col: str,
) -> Dict[str, Any]:
    clean = df[[date_col, feature, label_col, return_col]].copy()
    clean[feature] = pd.to_numeric(clean[feature], errors="coerce")
    clean[label_col] = pd.to_numeric(clean[label_col], errors="coerce")
    clean[return_col] = pd.to_numeric(clean[return_col], errors="coerce")
    clean = clean.dropna(subset=[feature, label_col, return_col])
    if clean.empty:
        return {
            "sample_count": 0,
            "date_count": 0,
            "best_direction": "none",
            "precision_at_5": 0.0,
            "top5_return": 0.0,
            "ascending": _empty_daily_metrics(),
            "descending": _empty_daily_metrics(),
        }

    ascending = _daily_ranking_metrics(clean, feature, label_col, return_col, date_col, ascending=True)
    descending = _daily_ranking_metrics(clean, feature, label_col, return_col, date_col, ascending=False)
    if (descending["precision_at_5"], descending["top5_return"]) >= (ascending["precision_at_5"], ascending["top5_return"]):
        best_direction = "descending"
        best = descending
    else:
        best_direction = "ascending"
        best = ascending
    return {
        "sample_count": int(len(clean)),
        "date_count": int(clean[date_col].nunique()),
        "best_direction": best_direction,
        "precision_at_3": best["precision_at_3"],
        "precision_at_5": best["precision_at_5"],
        "precision_at_10": best["precision_at_10"],
        "ndcg_at_10": best["ndcg_at_10"],
        "mrr": best["mrr"],
        "top5_return": best["top5_return"],
        "ascending": ascending,
        "descending": descending,
    }


def _daily_ranking_metrics(
    df: pd.DataFrame,
    score_col: str,
    label_col: str,
    return_col: str,
    date_col: str,
    ascending: bool = False,
) -> Dict[str, Any]:
    if df.empty:
        return _empty_daily_metrics()
    metrics = {
        "precision_at_3": [],
        "precision_at_5": [],
        "precision_at_10": [],
        "ndcg_at_10": [],
        "mrr": [],
        "top5_return": [],
    }
    valid_days = 0
    for _, rows in df.dropna(subset=[score_col, label_col, return_col]).groupby(date_col):
        if rows.empty:
            continue
        valid_days += 1
        ordered = rows.sort_values(score_col, ascending=ascending)
        labels = ordered[label_col].astype(int).to_numpy()
        returns = ordered[return_col].astype(float).to_numpy()
        for k in (3, 5, 10):
            top = labels[: min(k, len(labels))]
            metrics[f"precision_at_{k}"].append(float(top.mean()) if len(top) else 0.0)
        metrics["ndcg_at_10"].append(_ndcg_at_k(labels, 10))
        metrics["mrr"].append(_mrr(labels))
        top_returns = returns[: min(5, len(returns))]
        metrics["top5_return"].append(float(np.mean(top_returns)) if len(top_returns) else 0.0)

    if valid_days == 0:
        return _empty_daily_metrics()
    return {
        "sample_count": int(len(df)),
        "date_count": int(valid_days),
        "label_rate": round(float(pd.to_numeric(df[label_col], errors="coerce").mean()), 6),
        "precision_at_3": _mean(metrics["precision_at_3"]),
        "precision_at_5": _mean(metrics["precision_at_5"]),
        "precision_at_10": _mean(metrics["precision_at_10"]),
        "ndcg_at_10": _mean(metrics["ndcg_at_10"]),
        "mrr": _mean(metrics["mrr"]),
        "top5_return": _mean(metrics["top5_return"]),
    }


def _empty_daily_metrics() -> Dict[str, Any]:
    return {
        "sample_count": 0,
        "date_count": 0,
        "label_rate": 0.0,
        "precision_at_3": 0.0,
        "precision_at_5": 0.0,
        "precision_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "mrr": 0.0,
        "top5_return": 0.0,
    }


def _ndcg_at_k(labels: np.ndarray, k: int) -> float:
    top_k = min(int(k), len(labels))
    if top_k <= 0:
        return 0.0
    gains = labels[:top_k].astype(float)
    ideal = np.sort(labels.astype(float))[::-1][:top_k]
    dcg = _dcg(gains)
    idcg = _dcg(ideal)
    return float(dcg / idcg) if idcg else 0.0


def _dcg(gains: np.ndarray) -> float:
    return float(np.sum((2**gains - 1) / np.log2(np.arange(len(gains)) + 2)))


def _mrr(labels: np.ndarray) -> float:
    for rank, value in enumerate(labels.astype(int), start=1):
        if value == 1:
            return float(1.0 / rank)
    return 0.0


def _correlation_pairs(df: pd.DataFrame, feature_names: List[str], threshold: float = 0.85) -> List[Dict[str, Any]]:
    if len(feature_names) < 2:
        return []
    numeric = df[feature_names].replace([np.inf, -np.inf], np.nan).astype(float)
    corr = numeric.corr(method="spearman").abs()
    pairs: List[Dict[str, Any]] = []
    for left_idx, left in enumerate(feature_names):
        for right in feature_names[left_idx + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value) and float(value) >= float(threshold):
                pairs.append({"left": left, "right": right, "abs_spearman": round(float(value), 6)})
    return sorted(pairs, key=lambda item: item["abs_spearman"], reverse=True)


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(float(np.mean(values)), 6)
