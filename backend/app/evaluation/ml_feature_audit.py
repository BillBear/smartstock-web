from __future__ import annotations

import warnings
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


def audit_features(
    df: pd.DataFrame,
    feature_names: Iterable[str],
    label_col: str,
    return_col: str,
    date_col: str = "date",
) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"features": {}, "leakage_violations": [], "row_count": 0}

    local = df.copy()
    local[date_col] = pd.to_datetime(local[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    features: Dict[str, Any] = {}
    leakage = []
    for feature in feature_names:
        if _is_leakage_feature(feature):
            leakage.append(feature)
            features[feature] = {
                "missing_rate": _missing_rate(local, feature),
                "spearman": None,
                "univariate_auc": None,
                "buckets": [],
                "stability": {},
                "classification": "leakage_blocked",
            }
            continue
        metrics = _feature_metrics(local, feature, label_col, return_col, date_col)
        features[feature] = metrics

    return {
        "row_count": int(len(local)),
        "label_col": label_col,
        "return_col": return_col,
        "features": features,
        "leakage_violations": leakage,
    }


def _feature_metrics(df: pd.DataFrame, feature: str, label_col: str, return_col: str, date_col: str) -> Dict[str, Any]:
    missing_rate = _missing_rate(df, feature)
    if feature not in df.columns:
        return {
            "missing_rate": 1.0,
            "spearman": None,
            "univariate_auc": None,
            "buckets": [],
            "stability": {},
            "classification": "missing_too_high",
        }

    clean = df[[date_col, feature, label_col, return_col]].copy()
    clean[feature] = pd.to_numeric(clean[feature], errors="coerce")
    clean[label_col] = pd.to_numeric(clean[label_col], errors="coerce")
    clean[return_col] = pd.to_numeric(clean[return_col], errors="coerce")
    clean = clean.dropna(subset=[feature, label_col, return_col])
    if clean.empty:
        classification = "missing_too_high" if missing_rate > 0.4 else "weak_or_unstable"
        return {
            "missing_rate": missing_rate,
            "spearman": None,
            "univariate_auc": None,
            "buckets": [],
            "stability": {},
            "classification": classification,
        }

    spearman = _safe_corr(clean[feature], clean[return_col], method="spearman")
    auc = _safe_auc(clean[label_col].astype(int).to_numpy(), clean[feature].to_numpy(dtype=float))
    buckets = _bucket_metrics(clean, feature, label_col, return_col)
    stability = _stability(clean, feature, return_col, date_col)
    classification = _classify_feature(missing_rate, spearman, auc)
    return {
        "missing_rate": missing_rate,
        "spearman": spearman,
        "univariate_auc": auc,
        "buckets": buckets,
        "stability": stability,
        "classification": classification,
    }


def _bucket_metrics(df: pd.DataFrame, feature: str, label_col: str, return_col: str) -> List[Dict[str, Any]]:
    try:
        bucket_ids = pd.qcut(df[feature], q=min(5, len(df)), labels=False, duplicates="drop")
    except Exception:
        return []
    local = df.copy()
    local["_bucket"] = bucket_ids
    result = []
    for bucket, rows in local.groupby("_bucket"):
        if pd.isna(bucket):
            continue
        result.append(
            {
                "bucket": int(bucket),
                "sample_count": int(len(rows)),
                "hit_rate": round(float(rows[label_col].mean()), 6),
                "avg_return": round(float(rows[return_col].mean()), 6),
                "min_value": round(float(rows[feature].min()), 6),
                "max_value": round(float(rows[feature].max()), 6),
            }
        )
    return result


def _stability(df: pd.DataFrame, feature: str, return_col: str, date_col: str) -> Dict[str, Any]:
    ordered = df.sort_values(date_col).reset_index(drop=True)
    if len(ordered) < 4:
        return {"split_count": 0}
    midpoint = len(ordered) // 2
    first = ordered.iloc[:midpoint]
    second = ordered.iloc[midpoint:]
    return {
        "split_count": 2,
        "first_spearman": _safe_corr(first[feature], first[return_col], method="spearman"),
        "second_spearman": _safe_corr(second[feature], second[return_col], method="spearman"),
    }


def _classify_feature(missing_rate: float, spearman: Optional[float], auc: Optional[float]) -> str:
    if missing_rate > 0.4:
        return "missing_too_high"
    auc_edge = abs(float(auc) - 0.5) if auc is not None else 0.0
    corr_edge = abs(float(spearman)) if spearman is not None else 0.0
    if auc_edge >= 0.05 or corr_edge >= 0.05:
        return "core_candidate"
    return "weak_or_unstable"


def _missing_rate(df: pd.DataFrame, feature: str) -> float:
    if feature not in df.columns or len(df) == 0:
        return 1.0
    return round(float(pd.to_numeric(df[feature], errors="coerce").isna().mean()), 6)


def _is_leakage_feature(feature: str) -> bool:
    return str(feature).startswith("future_") or str(feature).startswith("label_")


def _safe_corr(left: pd.Series, right: pd.Series, method: str) -> Optional[float]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            value = left.corr(right, method=method)
        if pd.isna(value):
            return None
        return round(float(value), 6)
    except Exception:
        return None


def _safe_auc(y_true: np.ndarray, score: np.ndarray) -> Optional[float]:
    try:
        from sklearn.metrics import roc_auc_score

        if len(set(y_true.tolist())) < 2:
            return None
        return round(float(roc_auc_score(y_true, score)), 6)
    except Exception:
        return None
