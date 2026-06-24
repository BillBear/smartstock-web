"""
Train, persist and serve explainable probability models for SmartStock picks.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.ml_dataset_builder import MLDatasetBuilder
from app.services.ml_feature_builder import MLFeatureBuilder


class MLModelService:
    """Small, explainable ML layer around the existing rule strategy."""

    def __init__(self, data_source_manager, store, artifact_root: Optional[str] = None):
        self.data_source_manager = data_source_manager
        self.store = store
        self.feature_builder = MLFeatureBuilder()
        self.dataset_builder = MLDatasetBuilder(data_source_manager, self.feature_builder)
        base = Path(artifact_root) if artifact_root else Path(__file__).resolve().parents[2] / "data" / "ml_models"
        base.mkdir(parents=True, exist_ok=True)
        self.artifact_root = base
        self._loaded_model_id: Optional[str] = None
        self._loaded: Dict[str, Any] = {}

    @staticmethod
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

    @staticmethod
    def _bucket_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> List[Dict[str, Any]]:
        buckets = [
            ("80%以上", 0.80, 1.01),
            ("65-80%", 0.65, 0.80),
            ("50-65%", 0.50, 0.65),
            ("35-50%", 0.35, 0.50),
            ("35%以下", 0.0, 0.35),
        ]
        result = []
        for label, low, high in buckets:
            mask = (y_prob >= low) & (y_prob < high)
            count = int(np.sum(mask))
            hit_rate = float(np.mean(y_true[mask])) if count else 0.0
            result.append({"label": label, "min_prob": low, "max_prob": high, "sample_count": count, "hit_rate": round(hit_rate, 4)})
        return result

    @staticmethod
    def _safe_auc(y_true: np.ndarray, y_prob: np.ndarray) -> Optional[float]:
        try:
            from sklearn.metrics import roc_auc_score

            if len(set(y_true.tolist())) < 2:
                return None
            return round(float(roc_auc_score(y_true, y_prob)), 6)
        except Exception:
            return None

    def _evaluate_classifier(self, y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, Any]:
        from sklearn.metrics import brier_score_loss, log_loss

        y_prob = np.clip(y_prob, 0.001, 0.999)
        buckets = self._bucket_metrics(y_true, y_prob)
        high = next((b for b in buckets if b["label"] == "80%以上"), None) or {}
        low = next((b for b in buckets if b["label"] == "35%以下"), None) or {}
        return {
            "auc": self._safe_auc(y_true, y_prob),
            "brier_score": round(float(brier_score_loss(y_true, y_prob)), 6),
            "log_loss": round(float(log_loss(y_true, y_prob, labels=[0, 1])), 6),
            "ece": self._ece(y_true, y_prob),
            "bucket_metrics": buckets,
            "high_prob_hit_rate": high.get("hit_rate", 0.0),
            "low_prob_hit_rate": low.get("hit_rate", 0.0),
            "high_beats_low": bool((high.get("sample_count", 0) >= 5 and low.get("sample_count", 0) >= 5 and high.get("hit_rate", 0) > low.get("hit_rate", 0))),
        }

    @staticmethod
    def _make_pipeline(label: np.ndarray):
        from sklearn.dummy import DummyClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        if len(set(label.tolist())) < 2:
            model = DummyClassifier(strategy="prior")
        else:
            model = LogisticRegression(max_iter=800, class_weight="balanced", random_state=42, solver="liblinear")
        return Pipeline([("scaler", StandardScaler()), ("model", model)])

    def _walk_forward_metrics(self, df: pd.DataFrame, feature_names: List[str]) -> Dict[str, Any]:
        from sklearn.model_selection import TimeSeriesSplit

        ordered = df.sort_values(["date", "symbol"]).reset_index(drop=True)
        split_count = min(5, max(2, len(ordered) // 300))
        if len(ordered) < 120:
            split_count = 2
        tscv = TimeSeriesSplit(n_splits=split_count)
        up_true: List[int] = []
        up_prob: List[float] = []
        short_true: List[int] = []
        short_prob: List[float] = []
        dd_true: List[int] = []
        dd_prob: List[float] = []
        has_short_label = "label_short_continuation_3d" in ordered.columns
        for train_idx, test_idx in tscv.split(ordered):
            train = ordered.iloc[train_idx]
            test = ordered.iloc[test_idx]
            x_train = train[feature_names].astype(float)
            x_test = test[feature_names].astype(float)
            up_model = self._make_pipeline(train["label_up"].astype(int).to_numpy())
            short_model = self._make_pipeline(train["label_short_continuation_3d"].astype(int).to_numpy()) if has_short_label else None
            dd_model = self._make_pipeline(train["label_dd"].astype(int).to_numpy())
            up_model.fit(x_train, train["label_up"].astype(int))
            if short_model is not None:
                short_model.fit(x_train, train["label_short_continuation_3d"].astype(int))
            dd_model.fit(x_train, train["label_dd"].astype(int))
            up_true.extend(test["label_up"].astype(int).tolist())
            dd_true.extend(test["label_dd"].astype(int).tolist())
            up_prob.extend(up_model.predict_proba(x_test)[:, 1].tolist())
            if short_model is not None:
                short_true.extend(test["label_short_continuation_3d"].astype(int).tolist())
                short_prob.extend(short_model.predict_proba(x_test)[:, 1].tolist())
            dd_prob.extend(dd_model.predict_proba(x_test)[:, 1].tolist())

        metrics = {
            "method": "walk_forward_timeseries_split",
            "split_count": split_count,
            "up_model": self._evaluate_classifier(np.array(up_true), np.array(up_prob)),
            "dd_model": self._evaluate_classifier(np.array(dd_true), np.array(dd_prob)),
        }
        if short_true:
            metrics["short_continuation_model"] = self._evaluate_classifier(np.array(short_true), np.array(short_prob))
        return metrics

    def train_model(self, payload: Dict[str, Any], user_id: str = "default") -> Dict[str, Any]:
        try:
            import joblib
            from sklearn.tree import DecisionTreeClassifier, export_text
        except Exception as exc:
            raise RuntimeError("训练模型需要安装 scikit-learn 和 joblib，请先更新 backend/requirements.txt 并安装依赖") from exc

        dataset = self.dataset_builder.build_dataset(payload)
        df = dataset.get("df")
        if df is None or df.empty or len(df) < 80:
            raise ValueError("历史样本不足，无法训练模型；请扩大股票池、区间或降低 sample_step")

        feature_names = self.feature_builder.FEATURE_NAMES
        x = df[feature_names].astype(float)
        y_up = df["label_up"].astype(int)
        y_short = df["label_short_continuation_3d"].astype(int) if "label_short_continuation_3d" in df.columns else None
        y_dd = df["label_dd"].astype(int)

        model_up = self._make_pipeline(y_up.to_numpy())
        model_short = self._make_pipeline(y_short.to_numpy()) if y_short is not None else None
        model_dd = self._make_pipeline(y_dd.to_numpy())
        model_up.fit(x, y_up)
        if model_short is not None:
            model_short.fit(x, y_short)
        model_dd.fit(x, y_dd)

        tree = DecisionTreeClassifier(max_depth=max(3, min(5, int(payload.get("tree_max_depth") or 4))), min_samples_leaf=30, random_state=42)
        tree.fit(x, y_up)
        tree_rules = export_text(tree, feature_names=feature_names, max_depth=4)

        metrics = self._walk_forward_metrics(df, feature_names)
        up_metrics = metrics.get("up_model") or {}
        dd_metrics = metrics.get("dd_model") or {}
        live_ready = bool(
            up_metrics.get("high_beats_low")
            and (up_metrics.get("brier_score") or 1) <= 0.24
            and (up_metrics.get("ece") or 1) <= 0.12
            and (dd_metrics.get("brier_score") or 1) <= 0.26
        )

        model_id = f"ml_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        artifact_dir = self.artifact_root / model_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(model_up, artifact_dir / "up_model.joblib")
        if model_short is not None:
            joblib.dump(model_short, artifact_dir / "short_model.joblib")
        joblib.dump(model_dd, artifact_dir / "dd_model.joblib")
        joblib.dump(tree, artifact_dir / "tree_model.joblib")

        importance = self._factor_importance(model_up, model_dd, feature_names)
        meta = dataset.get("meta") or {}
        full_metrics = {
            **metrics,
            "live_ready": live_ready,
            "readiness_rules": {
                "up_high_prob_beats_low": up_metrics.get("high_beats_low"),
                "up_brier_lte_0_24": (up_metrics.get("brier_score") or 1) <= 0.24,
                "up_ece_lte_0_12": (up_metrics.get("ece") or 1) <= 0.12,
                "dd_brier_lte_0_26": (dd_metrics.get("brier_score") or 1) <= 0.26,
                "short_continuation_reported": bool(metrics.get("short_continuation_model")),
            },
            "tree_rules": tree_rules[:6000],
        }
        record = {
            "model_id": model_id,
            "model_code": "explainable_lr_v1",
            "strategy_code": payload.get("strategy_code") or "all",
            "status": "live_ready" if live_ready else "paper_only",
            "artifact_path": str(artifact_dir),
            "feature_names": feature_names,
            "metrics": full_metrics,
            "train_config": payload,
            "train_start": meta.get("train_start"),
            "train_end": meta.get("train_end"),
            "sample_count": int(meta.get("sample_count") or len(df)),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.store.save_ml_model_version(record)
        if hasattr(self.store, "save_ml_model_metrics"):
            self.store.save_ml_model_metrics(model_id, full_metrics)
        self.store.save_ml_factor_importance(model_id, importance)
        self.store.save_ml_training_samples(model_id, dataset.get("samples") or [], feature_names=feature_names)
        self._loaded_model_id = None

        return {
            "model_id": model_id,
            "status": record["status"],
            "sample_meta": meta,
            "metrics": full_metrics,
            "factor_importance": importance[:12],
            "feature_schema": self.feature_builder.describe_features(),
        }

    def _factor_importance(self, model_up, model_dd, feature_names: List[str]) -> List[Dict[str, Any]]:
        def _coef(model) -> np.ndarray:
            estimator = model.named_steps.get("model")
            if hasattr(estimator, "coef_"):
                return estimator.coef_[0]
            return np.zeros(len(feature_names))

        up_coef = _coef(model_up)
        dd_coef = _coef(model_dd)
        rows = []
        for idx, name in enumerate(feature_names):
            spec = self.feature_builder.FEATURE_MAP.get(name)
            score = abs(float(up_coef[idx])) + abs(float(dd_coef[idx])) * 0.7
            rows.append(
                {
                    "feature": name,
                    "label": spec.label if spec else name,
                    "category": spec.category if spec else "unknown",
                    "up_coef": round(float(up_coef[idx]), 6),
                    "dd_coef": round(float(dd_coef[idx]), 6),
                    "importance": round(score, 6),
                }
            )
        rows.sort(key=lambda x: x["importance"], reverse=True)
        return rows

    def _load_latest(self) -> Optional[Dict[str, Any]]:
        import joblib

        latest = self.store.get_latest_ml_model()
        if not latest:
            return None
        model_id = latest.get("model_id")
        if self._loaded_model_id == model_id and self._loaded:
            return self._loaded
        artifact_path = Path(latest.get("artifact_path") or "")
        loaded = {
            "record": latest,
            "up_model": joblib.load(artifact_path / "up_model.joblib"),
            "dd_model": joblib.load(artifact_path / "dd_model.joblib"),
        }
        short_path = artifact_path / "short_model.joblib"
        if short_path.exists():
            loaded["short_model"] = joblib.load(short_path)
        self._loaded_model_id = model_id
        self._loaded = loaded
        return loaded

    def get_latest_model(self) -> Dict[str, Any]:
        latest = self.store.get_latest_ml_model()
        if not latest:
            return {"available": False, "message": "暂无已训练模型"}
        return {
            "available": True,
            **latest,
            "factor_importance": self.store.list_ml_factor_importance(latest.get("model_id"), limit=30),
            "metric_rows": self.store.list_ml_model_metrics(latest.get("model_id"), limit=200)
            if hasattr(self.store, "list_ml_model_metrics")
            else [],
            "feature_schema": self.feature_builder.describe_features(),
        }

    def get_model_metrics(self, model_id: str) -> Dict[str, Any]:
        record = self.store.get_ml_model(model_id)
        if not record:
            return {"available": False, "message": "模型不存在"}
        return {
            "available": True,
            **record,
            "factor_importance": self.store.list_ml_factor_importance(model_id, limit=50),
            "metric_rows": self.store.list_ml_model_metrics(model_id, limit=200)
            if hasattr(self.store, "list_ml_model_metrics")
            else [],
            "feature_schema": self.feature_builder.describe_features(),
        }

    @staticmethod
    def _predict_class1(model, x: pd.DataFrame) -> float:
        prob = model.predict_proba(x)[0]
        classes = list(getattr(model.named_steps.get("model"), "classes_", [0, 1]))
        if 1 in classes:
            return float(prob[classes.index(1)])
        return float(prob[-1])

    def _factor_contributions(self, loaded: Dict[str, Any], features: Dict[str, float]) -> List[Dict[str, Any]]:
        feature_names = loaded["record"].get("feature_names") or self.feature_builder.FEATURE_NAMES
        x = pd.DataFrame([[features.get(name, 0.0) for name in feature_names]], columns=feature_names)
        scaler = loaded["up_model"].named_steps.get("scaler")
        z = scaler.transform(x)[0] if scaler else x.to_numpy()[0]

        def _coef(model) -> np.ndarray:
            estimator = model.named_steps.get("model")
            if hasattr(estimator, "coef_"):
                return estimator.coef_[0]
            return np.zeros(len(feature_names))

        up_coef = _coef(loaded["up_model"])
        dd_coef = _coef(loaded["dd_model"])
        rows = []
        for idx, name in enumerate(feature_names):
            spec = self.feature_builder.FEATURE_MAP.get(name)
            contribution = float(up_coef[idx] * z[idx] - dd_coef[idx] * z[idx] * 0.65)
            rows.append(
                {
                    "feature": name,
                    "label": spec.label if spec else name,
                    "category": spec.category if spec else "unknown",
                    "value": round(float(features.get(name, 0.0)), 4),
                    "contribution": round(contribution, 6),
                    "direction": "positive" if contribution >= 0 else "negative",
                    "description": spec.description if spec else "",
                }
            )
        rows.sort(key=lambda x: abs(x["contribution"]), reverse=True)
        return rows

    def _similar_evidence(self, model_id: str, features: Dict[str, float], feature_names: List[str]) -> Dict[str, Any]:
        samples = self.store.list_ml_training_samples(model_id, limit=2500)
        if not samples:
            return {"sample_count": 0, "message": "模型样本未落库，暂无相似样本证据"}
        matrix = []
        rows = []
        for item in samples:
            f = item.get("features") or {}
            matrix.append([float(f.get(name, 0.0)) for name in feature_names])
            rows.append(item)
        arr = np.array(matrix, dtype=float)
        target = np.array([float(features.get(name, 0.0)) for name in feature_names], dtype=float)
        std = np.std(arr, axis=0)
        std[std < 1e-6] = 1.0
        dist = np.sqrt(np.mean(((arr - target) / std) ** 2, axis=1))
        top_idx = np.argsort(dist)[: max(1, min(40, len(rows)))]
        selected = [rows[int(i)] for i in top_idx]
        up_hits = [int((row.get("labels") or {}).get("label_up") or 0) for row in selected]
        dd_hits = [int((row.get("labels") or {}).get("label_dd") or 0) for row in selected]
        returns = [float((row.get("labels") or {}).get("future_return_pct") or 0.0) for row in selected]
        return {
            "sample_count": len(selected),
            "win_rate": round(float(np.mean(up_hits)), 4) if up_hits else 0.0,
            "drawdown_hit_rate": round(float(np.mean(dd_hits)), 4) if dd_hits else 0.0,
            "avg_future_return_pct": round(float(np.mean(returns)), 4) if returns else 0.0,
            "message": "基于训练集中最相似的历史特征样本统计，非实盘承诺。",
        }

    def predict_live(
        self,
        feature_payload: Dict[str, Any],
        pick_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            loaded = self._load_latest()
        except Exception:
            return None
        if not loaded:
            return None

        record = loaded["record"]
        feature_names = record.get("feature_names") or self.feature_builder.FEATURE_NAMES
        features = feature_payload.get("features") or {}
        x = pd.DataFrame([[features.get(name, 0.0) for name in feature_names]], columns=feature_names)
        model_up_prob = self._predict_class1(loaded["up_model"], x)
        model_short_prob = self._predict_class1(loaded["short_model"], x) if loaded.get("short_model") is not None else None
        model_dd_prob = self._predict_class1(loaded["dd_model"], x)

        take_profit = float((pick_context or {}).get("take_profit_ratio") or 0.14)
        stop_loss = float((pick_context or {}).get("stop_loss_ratio") or 0.08)
        liquidity = min(100.0, max(0.0, float(features.get("amount_yi", 0.0)) * 5.0))
        probability_edge = (model_up_prob * take_profit - model_dd_prob * stop_loss) * 100.0
        continuation_lift = ((model_short_prob or model_up_prob) - 0.5) * 8.0
        probability_score = max(0.0, min(100.0, 50.0 + probability_edge * 9.0 + continuation_lift))
        risk_score = max(0.0, min(100.0, (1.0 - model_dd_prob) * 100.0))
        evidence_score = 82.0 if record.get("status") == "live_ready" else 58.0
        final_score = probability_score * 0.42 + risk_score * 0.28 + evidence_score * 0.20 + liquidity * 0.10

        contributions = self._factor_contributions(loaded, features)
        similar = self._similar_evidence(record.get("model_id"), features, feature_names)
        result = {
            "model_version_id": record.get("model_id"),
            "model_probability": {
                "model_up_prob": round(model_up_prob, 4),
                "model_short_continuation_prob": round(model_short_prob, 4) if model_short_prob is not None else None,
                "model_dd_prob": round(model_dd_prob, 4),
                "probability_edge_pct": round(probability_edge, 4),
                "final_score": round(final_score, 2),
                "label": "机器学习校准概率",
                "model_code": record.get("model_code"),
                "status": record.get("status"),
                "train_start": record.get("train_start"),
                "train_end": record.get("train_end"),
            },
            "factor_contributions": contributions[:10],
            "similar_sample_evidence": similar,
            "calibration_metrics": {
                "up_model": (record.get("metrics") or {}).get("up_model") or {},
                "short_continuation_model": (record.get("metrics") or {}).get("short_continuation_model") or {},
                "dd_model": (record.get("metrics") or {}).get("dd_model") or {},
                "walk_forward": {
                    "method": (record.get("metrics") or {}).get("method"),
                    "split_count": (record.get("metrics") or {}).get("split_count"),
                },
            },
            "feature_snapshot": {
                "as_of_date": feature_payload.get("as_of_date"),
                "features": features,
                "missing_flags": feature_payload.get("missing_flags") or {},
            },
        }
        try:
            self.store.save_ml_prediction(
                {
                    "model_id": record.get("model_id"),
                    "symbol": (pick_context or {}).get("symbol"),
                    "trade_date": datetime.now().strftime("%Y-%m-%d"),
                    "prediction": result,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        except Exception:
            pass
        return result
