from __future__ import annotations

from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd


def evaluate_full_market_topk(
    df: pd.DataFrame,
    score_columns: Iterable[str],
    label_col: str = "label_core_strong_10d",
    return_col: str = "future_return_10d_pct",
    drawdown_col: str = "future_max_drawdown_10d_pct",
    ks: Iterable[int] | None = None,
) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"scores": {}, "date_count": 0, "sample_count": 0}
    local = df.copy()
    local["trade_date"] = pd.to_datetime(local["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local[label_col] = pd.to_numeric(local[label_col], errors="coerce").fillna(0).astype(int)
    local[return_col] = pd.to_numeric(local[return_col], errors="coerce")
    if drawdown_col not in local.columns:
        local[drawdown_col] = 0.0
    local[drawdown_col] = pd.to_numeric(local[drawdown_col], errors="coerce").fillna(0.0)
    local = local.dropna(subset=["trade_date", return_col])
    ks = sorted({int(k) for k in (ks or [3, 5, 10, 20]) if int(k) > 0})
    scores: Dict[str, Dict[str, Any]] = {}
    for score_col in score_columns:
        if score_col not in local.columns:
            continue
        frame = local[local[score_col].notna()].copy()
        daily: Dict[str, List[float]] = {f"precision_at_{k}": [] for k in ks}
        daily.update({f"top{k}_avg_return": [] for k in ks})
        daily.update({f"top{k}_max_drawdown": [] for k in ks})
        daily["ndcg_at_10"] = []
        daily["mrr"] = []
        daily["recall_at_10"] = []
        daily["limit_up_capture_at_10"] = []
        daily["limit_down_avoidance_at_10"] = []
        for _, rows in frame.groupby("trade_date"):
            ordered = rows.sort_values(score_col, ascending=False)
            labels = ordered[label_col].to_numpy(dtype=int)
            returns = ordered[return_col].to_numpy(dtype=float)
            drawdowns = ordered[drawdown_col].to_numpy(dtype=float)
            for k in ks:
                top_k = min(k, len(ordered))
                if top_k <= 0:
                    continue
                daily[f"precision_at_{k}"].append(float(np.mean(labels[:top_k])))
                daily[f"top{k}_avg_return"].append(float(np.mean(returns[:top_k])))
                daily[f"top{k}_max_drawdown"].append(float(np.min(drawdowns[:top_k])))
            daily["ndcg_at_10"].append(_ndcg(labels, 10))
            daily["mrr"].append(_mrr(labels))
            positives = int(np.sum(labels))
            daily["recall_at_10"].append(float(np.sum(labels[: min(10, len(labels))]) / positives) if positives else 0.0)
            if "future_limit_up_count_10d" in ordered.columns:
                daily["limit_up_capture_at_10"].append(float((ordered["future_limit_up_count_10d"].head(10) > 0).mean()))
            if "future_limit_down_count_10d" in ordered.columns:
                daily["limit_down_avoidance_at_10"].append(float((ordered["future_limit_down_count_10d"].head(10) <= 0).mean()))
        metrics = {
            "date_count": int(frame["trade_date"].nunique()),
            "sample_count": int(len(frame)),
        }
        for key, values in daily.items():
            metrics[key] = round(float(np.mean(values)), 6) if values else 0.0
        scores[score_col] = metrics
    return {"scores": scores, "date_count": int(local["trade_date"].nunique()), "sample_count": int(len(local))}


def _ndcg(labels: np.ndarray, k: int) -> float:
    if len(labels) == 0:
        return 0.0
    top_k = min(k, len(labels))
    gains = labels[:top_k]
    ideal = np.sort(labels)[::-1][:top_k]
    dcg = np.sum((2**gains - 1) / np.log2(np.arange(top_k) + 2))
    idcg = np.sum((2**ideal - 1) / np.log2(np.arange(top_k) + 2))
    return float(dcg / idcg) if idcg else 0.0


def _mrr(labels: np.ndarray) -> float:
    for idx, value in enumerate(labels, start=1):
        if int(value) == 1:
            return float(1.0 / idx)
    return 0.0
