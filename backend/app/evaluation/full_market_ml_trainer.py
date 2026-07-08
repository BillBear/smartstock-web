from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd

from app.evaluation.full_market_feature_builder import FEATURE_NAMES, build_full_market_features
from app.evaluation.full_market_label_builder import add_full_market_forward_labels
from app.evaluation.full_market_panel_builder import assess_full_market_panel_quality
from app.evaluation.full_market_topk_evaluator import evaluate_full_market_topk


def run_full_market_ml_experiment(
    panel_dir: str | Path,
    output_dir: str | Path,
    smoke: bool = False,
    label_col: str = "label_core_strong_10d",
    return_col: str = "future_return_10d_pct",
) -> Dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    panel = _read_panel(Path(panel_dir))
    if smoke and len(panel) > 120_000:
        keep_dates = sorted(panel["trade_date"].astype(str).unique())[-140:]
        panel = panel[panel["trade_date"].astype(str).isin(keep_dates)].copy()
    quality = assess_full_market_panel_quality(panel, min_daily_count=20 if smoke else 4500)
    _write_json(root / "data_quality_report.json", quality)
    labeled, label_report = add_full_market_forward_labels(panel, horizons=[3, 5, 10, 20])
    features, feature_report = build_full_market_features(labeled)
    feature_coverage = pd.DataFrame(
        [{"feature": key, "missing_rate": value} for key, value in (feature_report.get("feature_missing_rates") or {}).items()]
    )
    feature_coverage.to_csv(root / "feature_coverage.csv", index=False)
    _label_distribution(features, label_col).to_csv(root / "label_distribution.csv", index=False)

    dataset = features.dropna(subset=[label_col, return_col]).copy()
    split_plan = _build_split_plan(dataset, final_holdout_months=1 if smoke else 3, stock_holdout_ratio=0.20, walk_forward_splits=3 if smoke else 5)
    _write_json(root / "split_plan.json", split_plan)
    if not split_plan.get("train_dates") or not split_plan.get("final_holdout_dates"):
        summary = _blocked_summary("split_plan_insufficient", quality, label_report, feature_report)
        _write_artifacts(root, summary, pd.DataFrame(), pd.DataFrame())
        return summary

    train, final_holdout, stock_holdout = _split_dataset(dataset, split_plan)
    model_results = {}
    best_name = ""
    best_score = -1.0
    best_model = None
    for name, model in _candidate_models(train[label_col].astype(int).to_numpy()).items():
        try:
            fitted = _fit_model(model, train, label_col)
            final_scored = _score_frame(fitted, final_holdout)
            stock_scored = _score_frame(fitted, stock_holdout)
            walk = _walk_forward(dataset, split_plan, name, label_col, return_col)
            final_metrics = evaluate_full_market_topk(final_scored, ["model_score"], label_col=label_col, return_col=return_col)["scores"].get("model_score", {})
            stock_metrics = evaluate_full_market_topk(stock_scored, ["model_score"], label_col=label_col, return_col=return_col)["scores"].get("model_score", {})
            score = float(final_metrics.get("precision_at_5") or 0.0) + float(final_metrics.get("ndcg_at_10") or 0.0)
            model_results[name] = {
                "status": "trained",
                "final_holdout": final_metrics,
                "stock_holdout": stock_metrics,
                "walk_forward": walk,
                "feature_importance": _feature_importance(fitted),
            }
            if score > best_score:
                best_score = score
                best_name = name
                best_model = fitted
        except Exception as exc:
            model_results[name] = {"status": "skipped", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}

    if best_model is None:
        summary = _blocked_summary("no_model_trained", quality, label_report, feature_report)
        summary["model_results"] = model_results
        _write_artifacts(root, summary, pd.DataFrame(), pd.DataFrame())
        return summary

    final_scored = _score_frame(best_model, final_holdout)
    final_eval = evaluate_full_market_topk(
        final_scored,
        score_columns=["model_score", "adj_return_60d_rank", "amount_rank"],
        label_col=label_col,
        return_col=return_col,
    )
    baseline_rows = _baseline_rows(final_eval)
    baseline_df = pd.DataFrame(baseline_rows)
    baseline_df.to_csv(root / "baseline_comparison.csv", index=False)
    topk_rows = _topk_rows(final_eval)
    topk_df = pd.DataFrame(topk_rows)
    topk_df.to_csv(root / "topk_validation.csv", index=False)
    feature_importance = pd.DataFrame(model_results.get(best_name, {}).get("feature_importance") or [])
    feature_importance.to_csv(root / "feature_importance.csv", index=False)
    joblib.dump(best_model, root / "model.joblib")
    summary = {
        "experiment": "full_market_supervised_ml",
        "model_version": "ml_full_market_research_smoke" if smoke else "ml_full_market_research",
        "model_status": "research_only",
        "production_enabled": False,
        "strategy_impact": False,
        "best_model": best_name,
        "quality": quality,
        "label_report": label_report,
        "feature_report": feature_report,
        "split_plan": split_plan,
        "metrics": {
            "final_holdout": model_results.get(best_name, {}).get("final_holdout") or {},
            "stock_holdout": model_results.get(best_name, {}).get("stock_holdout") or {},
            "walk_forward": model_results.get(best_name, {}).get("walk_forward") or {},
        },
        "model_results": model_results,
        "baseline_comparison": baseline_rows,
    }
    _write_artifacts(root, summary, baseline_df, topk_df)
    return summary


def _read_panel(panel_dir: Path) -> pd.DataFrame:
    path = panel_dir / "full_market_panel.parquet"
    if path.exists():
        return pd.read_parquet(path)
    paths = sorted(panel_dir.glob("*.parquet"))
    if paths:
        return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    raise FileNotFoundError(f"No parquet panel found under {panel_dir}")


def _build_split_plan(df: pd.DataFrame, final_holdout_months: int, stock_holdout_ratio: float, walk_forward_splits: int) -> Dict[str, Any]:
    dates = sorted(df["trade_date"].astype(str).unique())
    symbols = sorted(df["symbol"].astype(str).unique())
    if len(dates) < 20 or len(symbols) < 5:
        return {"method": "time_stock_walk_forward", "train_dates": [], "final_holdout_dates": [], "stock_holdout_symbols": []}
    cutoff = pd.Timestamp(dates[-1]) - pd.DateOffset(months=max(1, int(final_holdout_months)))
    final_dates = [date for date in dates if pd.Timestamp(date) > cutoff]
    train_dates = [date for date in dates if date not in set(final_dates)]
    holdout_count = max(1, min(len(symbols) - 1, int(round(len(symbols) * stock_holdout_ratio))))
    holdout_symbols = symbols[:holdout_count]
    train_symbols = [symbol for symbol in symbols if symbol not in set(holdout_symbols)]
    windows = _walk_windows(train_dates, walk_forward_splits)
    return {
        "method": "time_stock_walk_forward_with_label_embargo",
        "train_dates": train_dates,
        "final_holdout_dates": final_dates,
        "stock_holdout_symbols": holdout_symbols,
        "train_symbols": train_symbols,
        "walk_forward": {"split_count": len(windows), "windows": windows},
    }


def _walk_windows(train_dates: List[str], splits: int) -> List[Dict[str, Any]]:
    if len(train_dates) < 6:
        return []
    count = max(1, min(int(splits), len(train_dates) // 10 or 1))
    validation_size = max(3, len(train_dates) // (count + 2))
    windows = []
    for idx in range(count):
        validation_start = len(train_dates) - validation_size * (count - idx)
        validation_dates = train_dates[validation_start : validation_start + validation_size]
        embargo_start = max(0, validation_start - 20)
        window_train = train_dates[:embargo_start]
        if window_train and validation_dates:
            windows.append({"train_dates": window_train, "validation_dates": validation_dates, "embargo_dates": train_dates[embargo_start:validation_start]})
    return windows


def _split_dataset(df: pd.DataFrame, split_plan: Dict[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = df["trade_date"].astype(str)
    symbols = df["symbol"].astype(str)
    train_dates = set(split_plan.get("train_dates") or [])
    final_dates = set(split_plan.get("final_holdout_dates") or [])
    train_symbols = set(split_plan.get("train_symbols") or [])
    holdout_symbols = set(split_plan.get("stock_holdout_symbols") or [])
    train = df[dates.isin(train_dates) & symbols.isin(train_symbols)].copy()
    final = df[dates.isin(final_dates) & symbols.isin(train_symbols)].copy()
    stock = df[dates.isin(train_dates) & symbols.isin(holdout_symbols)].copy()
    return train, final, stock


def _candidate_models(y: np.ndarray) -> Dict[str, Any]:
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier

    if len(set(y.tolist())) < 2:
        return {"dummy_prior": Pipeline([("scaler", StandardScaler()), ("model", DummyClassifier(strategy="prior"))])}
    return {
        "logistic_regression": Pipeline([("scaler", StandardScaler()), ("model", LogisticRegression(max_iter=500, class_weight="balanced", solver="liblinear"))]),
        "decision_tree_shallow": DecisionTreeClassifier(max_depth=4, min_samples_leaf=20, class_weight="balanced", random_state=42),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=80, learning_rate=0.06, max_leaf_nodes=31, random_state=42),
    }


def _fit_model(model: Any, train: pd.DataFrame, label_col: str) -> Any:
    x = _feature_matrix(train)
    y = train[label_col].astype(int)
    weights = _sample_weights(train, label_col)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module=r"sklearn\.")
        try:
            if hasattr(model, "named_steps"):
                model.fit(x, y, model__sample_weight=weights)
            else:
                model.fit(x, y, sample_weight=weights)
        except TypeError:
            model.fit(x, y)
    return model


def _score_frame(model: Any, frame: pd.DataFrame) -> pd.DataFrame:
    local = frame.copy()
    if local.empty:
        local["model_score"] = []
        return local
    x = _feature_matrix(local)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module=r"sklearn\.")
        if hasattr(model, "predict_proba"):
            prob = model.predict_proba(x)
            classes = list(getattr(model, "classes_", []))
            if not classes and hasattr(model, "named_steps"):
                classes = list(getattr(model.named_steps.get("model"), "classes_", [0, 1]))
            local["model_score"] = prob[:, classes.index(1)] if 1 in classes else prob[:, -1]
        else:
            local["model_score"] = model.predict(x)
    return local


def _feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame[FEATURE_NAMES].astype(float).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return x.clip(lower=-1_000_000.0, upper=1_000_000.0)


def _walk_forward(df: pd.DataFrame, split_plan: Dict[str, Any], model_name: str, label_col: str, return_col: str) -> Dict[str, Any]:
    frames = []
    for window in (split_plan.get("walk_forward") or {}).get("windows") or []:
        train = df[df["trade_date"].astype(str).isin(set(window.get("train_dates") or []))].copy()
        validation = df[df["trade_date"].astype(str).isin(set(window.get("validation_dates") or []))].copy()
        if train.empty or validation.empty:
            continue
        model = _candidate_models(train[label_col].astype(int).to_numpy()).get(model_name)
        if model is None:
            continue
        fitted = _fit_model(model, train, label_col)
        frames.append(_score_frame(fitted, validation))
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    metrics = evaluate_full_market_topk(combined, ["model_score"], label_col=label_col, return_col=return_col)["scores"].get("model_score", {}) if not combined.empty else {}
    return {"split_count": len(frames), **metrics}


def _sample_weights(df: pd.DataFrame, label_col: str) -> np.ndarray:
    weights = pd.Series(1.0, index=df.index)
    date_counts = df["trade_date"].astype(str).map(df["trade_date"].astype(str).value_counts()).astype(float)
    weights = weights / date_counts.replace(0, np.nan).fillna(1.0)
    label_counts = df[label_col].astype(int).map(df[label_col].astype(int).value_counts()).astype(float)
    weights = weights / label_counts.replace(0, np.nan).fillna(1.0)
    mean = float(weights.mean()) if len(weights) else 1.0
    return (weights / mean).to_numpy(dtype=float)


def _feature_importance(model: Any) -> List[Dict[str, Any]]:
    estimator = model.named_steps.get("model") if hasattr(model, "named_steps") else model
    values = getattr(estimator, "feature_importances_", None)
    if values is None and hasattr(estimator, "coef_"):
        values = np.ravel(estimator.coef_)
    if values is None:
        return []
    rows = [{"feature": feature, "importance": round(float(abs(value)), 8)} for feature, value in zip(FEATURE_NAMES, values)]
    return sorted(rows, key=lambda item: item["importance"], reverse=True)


def _label_distribution(df: pd.DataFrame, label_col: str) -> pd.DataFrame:
    rows = []
    for date, group in df.groupby("trade_date"):
        rows.append({"trade_date": date, "sample_count": len(group), "positive_rate": float(group[label_col].mean()) if label_col in group else 0.0})
    return pd.DataFrame(rows)


def _baseline_rows(topk_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for score, metrics in (topk_report.get("scores") or {}).items():
        rows.append({"score": score, **metrics})
    return rows


def _topk_rows(topk_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _baseline_rows(topk_report)


def _blocked_summary(reason: str, quality: Dict[str, Any], label_report: Dict[str, Any], feature_report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "experiment": "full_market_supervised_ml",
        "model_status": "research_only",
        "production_enabled": False,
        "strategy_impact": False,
        "blocked": True,
        "blocking_reason": reason,
        "quality": quality,
        "label_report": label_report,
        "feature_report": feature_report,
        "metrics": {},
    }


def _write_artifacts(root: Path, summary: Dict[str, Any], baseline: pd.DataFrame, topk: pd.DataFrame) -> None:
    _write_json(root / "model_metrics.json", summary)
    if not (root / "baseline_comparison.csv").exists():
        baseline.to_csv(root / "baseline_comparison.csv", index=False)
    if not (root / "topk_validation.csv").exists():
        topk.to_csv(root / "topk_validation.csv", index=False)
    model_card = [
        "# Full Market Supervised ML Model Card",
        "",
        f"model_status: `{summary.get('model_status')}`",
        f"production_enabled: `{summary.get('production_enabled')}`",
        f"best_model: `{summary.get('best_model')}`",
        "",
        "This model is research-only and is not connected to production stock selection or trading actions.",
    ]
    (root / "model_card.md").write_text("\n".join(model_card) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    return value
