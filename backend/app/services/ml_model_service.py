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

from app.evaluation.ml_readiness import assess_ml_readiness
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
    def _predict_class1_batch(model, x: pd.DataFrame) -> np.ndarray:
        prob = model.predict_proba(x)
        classes = list(getattr(model.named_steps.get("model"), "classes_", [0, 1]))
        if 1 in classes:
            return np.asarray(prob[:, classes.index(1)], dtype=float)
        return np.zeros(len(x), dtype=float)

    @staticmethod
    def _precision_at_k(y_true: np.ndarray, y_prob: np.ndarray, k: int) -> float:
        if len(y_true) == 0:
            return 0.0
        top_k = max(1, min(int(k), len(y_true)))
        order = np.argsort(y_prob)[::-1][:top_k]
        return round(float(np.mean(y_true[order])), 6)

    def _evaluate_holdout(
        self,
        model_up,
        model_dd,
        df: pd.DataFrame,
        feature_names: List[str],
    ) -> Dict[str, Any]:
        if df is None or df.empty:
            return {
                "sample_count": 0,
                "symbol_count": 0,
                "date_count": 0,
                "auc": None,
                "brier_score": None,
                "ece": None,
                "precision_at_3": 0.0,
                "precision_at_5": 0.0,
                "bucket_hit_rates": [],
            }

        x = df[feature_names].astype(float)
        y_up = df["label_up"].astype(int).to_numpy()
        y_dd = df["label_dd"].astype(int).to_numpy()
        up_prob = self._predict_class1_batch(model_up, x)
        dd_prob = self._predict_class1_batch(model_dd, x)
        up_metrics = self._evaluate_classifier(y_up, up_prob)
        dd_metrics = self._evaluate_classifier(y_dd, dd_prob)
        return {
            "sample_count": int(len(df)),
            "symbol_count": int(df["symbol"].nunique()) if "symbol" in df.columns else 0,
            "date_count": int(df["date"].nunique()) if "date" in df.columns else 0,
            "auc": up_metrics.get("auc"),
            "brier_score": up_metrics.get("brier_score"),
            "ece": up_metrics.get("ece"),
            "precision_at_3": self._precision_at_k(y_up, up_prob, 3),
            "precision_at_5": self._precision_at_k(y_up, up_prob, 5),
            "bucket_hit_rates": [
                {
                    "bucket": item.get("label"),
                    "hit_rate": item.get("hit_rate"),
                    "sample_count": item.get("sample_count"),
                }
                for item in up_metrics.get("bucket_metrics") or []
            ],
            "up_model": up_metrics,
            "dd_model": dd_metrics,
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
            model = LogisticRegression(max_iter=800, class_weight="balanced", random_state=42)
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
        dd_true: List[int] = []
        dd_prob: List[float] = []
        for train_idx, test_idx in tscv.split(ordered):
            train = ordered.iloc[train_idx]
            test = ordered.iloc[test_idx]
            x_train = train[feature_names].astype(float)
            x_test = test[feature_names].astype(float)
            up_model = self._make_pipeline(train["label_up"].astype(int).to_numpy())
            dd_model = self._make_pipeline(train["label_dd"].astype(int).to_numpy())
            up_model.fit(x_train, train["label_up"].astype(int))
            dd_model.fit(x_train, train["label_dd"].astype(int))
            up_true.extend(test["label_up"].astype(int).tolist())
            dd_true.extend(test["label_dd"].astype(int).tolist())
            up_prob.extend(self._predict_class1_batch(up_model, x_test).tolist())
            dd_prob.extend(self._predict_class1_batch(dd_model, x_test).tolist())

        return {
            "method": "walk_forward_timeseries_split",
            "split_count": split_count,
            "up_model": self._evaluate_classifier(np.array(up_true), np.array(up_prob)),
            "dd_model": self._evaluate_classifier(np.array(dd_true), np.array(dd_prob)),
        }

    @staticmethod
    def _date_text_series(df: pd.DataFrame) -> pd.Series:
        return pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str)

    def _split_dataset_for_training(self, df: pd.DataFrame, split_plan: Dict[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if not split_plan:
            return df.copy(), pd.DataFrame(), pd.DataFrame()

        date_text = self._date_text_series(df)
        symbol_text = df["symbol"].astype(str)
        training_dates = set(str(item) for item in split_plan.get("training_dates") or [])
        training_symbols = set(str(item) for item in split_plan.get("training_symbols") or [])
        final_dates = set(str(item) for item in ((split_plan.get("final_holdout") or {}).get("dates") or []))
        holdout_symbols = set(str(item) for item in ((split_plan.get("stock_holdout") or {}).get("symbols") or []))

        if not training_dates or not training_symbols:
            return df.copy(), pd.DataFrame(), pd.DataFrame()

        train_mask = date_text.isin(training_dates) & symbol_text.isin(training_symbols)
        final_mask = date_text.isin(final_dates) & symbol_text.isin(training_symbols)
        stock_mask = date_text.isin(training_dates) & symbol_text.isin(holdout_symbols)
        return (
            df.loc[train_mask].copy(),
            df.loc[final_mask].copy(),
            df.loc[stock_mask].copy(),
        )

    @staticmethod
    def _split_plan_summary(split_plan: Dict[str, Any]) -> Dict[str, Any]:
        if not split_plan:
            return {}
        final_holdout = split_plan.get("final_holdout") or {}
        stock_holdout = split_plan.get("stock_holdout") or {}
        walk_forward = split_plan.get("walk_forward") or {}
        windows = []
        for item in walk_forward.get("windows") or []:
            windows.append(
                {
                    "window": item.get("window"),
                    "train_start": item.get("train_start"),
                    "train_end": item.get("train_end"),
                    "validation_start": item.get("validation_start"),
                    "validation_end": item.get("validation_end"),
                    "train_date_count": item.get("train_date_count"),
                    "validation_date_count": item.get("validation_date_count"),
                }
            )
        return {
            "method": split_plan.get("method"),
            "training_date_count": len(split_plan.get("training_dates") or []),
            "training_symbol_count": len(split_plan.get("training_symbols") or []),
            "final_holdout": {
                "start_date": final_holdout.get("start_date"),
                "end_date": final_holdout.get("end_date"),
                "date_count": final_holdout.get("date_count") or len(final_holdout.get("dates") or []),
            },
            "stock_holdout": {
                "ratio": stock_holdout.get("ratio"),
                "symbol_count": stock_holdout.get("symbol_count") or len(stock_holdout.get("symbols") or []),
            },
            "walk_forward": {
                "split_count": walk_forward.get("split_count") or len(windows),
                "windows": windows,
            },
        }

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

        meta = dataset.get("meta") or {}
        split_plan = meta.get("split_plan") or {}
        train_df, final_holdout_df, stock_holdout_df = self._split_dataset_for_training(df, split_plan)
        if train_df is None or train_df.empty or len(train_df) < 80:
            raise ValueError("训练切分后的样本不足，无法训练模型；请扩大股票池、区间或降低 holdout 比例")

        feature_names = self.feature_builder.FEATURE_NAMES
        x = train_df[feature_names].astype(float)
        y_up = train_df["label_up"].astype(int)
        y_dd = train_df["label_dd"].astype(int)

        model_up = self._make_pipeline(y_up.to_numpy())
        model_dd = self._make_pipeline(y_dd.to_numpy())
        model_up.fit(x, y_up)
        model_dd.fit(x, y_dd)

        tree = DecisionTreeClassifier(max_depth=max(3, min(5, int(payload.get("tree_max_depth") or 4))), min_samples_leaf=30, random_state=42)
        tree.fit(x, y_up)
        tree_rules = export_text(tree, feature_names=feature_names, max_depth=4)

        metrics = self._walk_forward_metrics(train_df, feature_names)
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
        joblib.dump(model_dd, artifact_dir / "dd_model.joblib")
        joblib.dump(tree, artifact_dir / "tree_model.joblib")

        importance = self._factor_importance(model_up, model_dd, feature_names)
        sample_meta = dict(meta)
        sample_meta["split_plan"] = self._split_plan_summary(split_plan)
        full_metrics = {
            **metrics,
            "sample_count": int(meta.get("sample_count") or len(df)),
            "symbol_count": int(meta.get("symbol_count") or 0),
            "valid_symbol_count": int(meta.get("valid_symbol_count") or 0),
            "training_sample_count": int(len(train_df)),
            "training_symbol_count": int(train_df["symbol"].nunique()) if "symbol" in train_df.columns else 0,
            "training_date_count": int(train_df["date"].nunique()) if "date" in train_df.columns else 0,
            "split_plan": self._split_plan_summary(split_plan),
            "final_holdout": self._evaluate_holdout(model_up, model_dd, final_holdout_df, feature_names),
            "stock_holdout": self._evaluate_holdout(model_up, model_dd, stock_holdout_df, feature_names),
            "sample_meta": sample_meta,
            "live_ready": live_ready,
            "readiness_rules": {
                "up_high_prob_beats_low": up_metrics.get("high_beats_low"),
                "up_brier_lte_0_24": (up_metrics.get("brier_score") or 1) <= 0.24,
                "up_ece_lte_0_12": (up_metrics.get("ece") or 1) <= 0.12,
                "dd_brier_lte_0_26": (dd_metrics.get("brier_score") or 1) <= 0.26,
            },
            "tree_rules": tree_rules[:6000],
        }
        full_metrics["ml_readiness"] = assess_ml_readiness(
            {
                "train_start": meta.get("train_start"),
                "train_end": meta.get("train_end"),
                "sample_count": int(meta.get("sample_count") or len(df)),
                "train_config": payload,
                "metrics": full_metrics,
            }
        )
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
        self.store.save_ml_factor_importance(model_id, importance)
        self.store.save_ml_training_samples(model_id, train_df.to_dict(orient="records"), feature_names=feature_names)
        self._loaded_model_id = None

        return {
            "model_id": model_id,
            "status": record["status"],
            "sample_meta": sample_meta,
            "metrics": full_metrics,
            "ml_readiness": full_metrics["ml_readiness"],
            "model_validation_status": full_metrics["ml_readiness"]["status"],
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
        self._loaded_model_id = model_id
        self._loaded = loaded
        return loaded

    def get_latest_model(self) -> Dict[str, Any]:
        latest = self.store.get_latest_ml_model()
        if not latest:
            return {"available": False, "message": "暂无已训练模型"}
        latest = self._attach_readiness(latest)
        return {
            "available": True,
            **latest,
            "factor_importance": self.store.list_ml_factor_importance(latest.get("model_id"), limit=30),
            "feature_schema": self.feature_builder.describe_features(),
        }

    def get_model_metrics(self, model_id: str) -> Dict[str, Any]:
        record = self.store.get_ml_model(model_id)
        if not record:
            return {"available": False, "message": "模型不存在"}
        record = self._attach_readiness(record)
        return {
            "available": True,
            **record,
            "factor_importance": self.store.list_ml_factor_importance(model_id, limit=50),
            "feature_schema": self.feature_builder.describe_features(),
        }

    def _attach_readiness(self, record: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(record or {})
        metrics = dict(enriched.get("metrics") or {})
        readiness = assess_ml_readiness({**enriched, "metrics": metrics})
        metrics["ml_readiness"] = readiness
        enriched["metrics"] = metrics
        enriched["ml_readiness"] = readiness
        enriched["model_validation_status"] = readiness.get("status")
        enriched["production_ml_ready"] = bool(readiness.get("production_ml_ready"))
        enriched["model_role"] = readiness.get("role")
        return enriched

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

        record = self._attach_readiness(loaded["record"])
        feature_names = record.get("feature_names") or self.feature_builder.FEATURE_NAMES
        features = feature_payload.get("features") or {}
        x = pd.DataFrame([[features.get(name, 0.0) for name in feature_names]], columns=feature_names)
        model_up_prob = self._predict_class1(loaded["up_model"], x)
        model_dd_prob = self._predict_class1(loaded["dd_model"], x)

        take_profit = float((pick_context or {}).get("take_profit_ratio") or 0.14)
        stop_loss = float((pick_context or {}).get("stop_loss_ratio") or 0.08)
        liquidity = min(100.0, max(0.0, float(features.get("amount_yi", 0.0)) * 5.0))
        probability_edge = (model_up_prob * take_profit - model_dd_prob * stop_loss) * 100.0
        probability_score = max(0.0, min(100.0, 50.0 + probability_edge * 9.0))
        risk_score = max(0.0, min(100.0, (1.0 - model_dd_prob) * 100.0))
        evidence_score = 82.0 if record.get("status") == "live_ready" else 58.0
        final_score = probability_score * 0.42 + risk_score * 0.28 + evidence_score * 0.20 + liquidity * 0.10

        contributions = self._factor_contributions(loaded, features)
        similar = self._similar_evidence(record.get("model_id"), features, feature_names)
        readiness = record.get("ml_readiness") or {}
        production_ml_ready = bool(readiness.get("production_ml_ready"))
        result = {
            "model_version_id": record.get("model_id"),
            "model_readiness": readiness,
            "model_probability": {
                "model_up_prob": round(model_up_prob, 4),
                "model_dd_prob": round(model_dd_prob, 4),
                "probability_edge_pct": round(probability_edge, 4),
                "final_score": round(final_score, 2),
                "label": "机器学习校准概率" if production_ml_ready else readiness.get("label") or "弱模型参考",
                "model_code": record.get("model_code"),
                "status": record.get("status"),
                "model_validation_status": readiness.get("status"),
                "production_ml_ready": production_ml_ready,
                "role": readiness.get("role"),
                "readiness_message": readiness.get("message"),
                "train_start": record.get("train_start"),
                "train_end": record.get("train_end"),
            },
            "factor_contributions": contributions[:10],
            "similar_sample_evidence": similar,
            "calibration_metrics": {
                "up_model": (record.get("metrics") or {}).get("up_model") or {},
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
