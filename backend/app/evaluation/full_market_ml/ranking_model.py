"""Fixed baselines and nested daily cross-sectional ranking models."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .baseline_model import RegisteredBaselineTrainer, _date_rank_matrix
from .features import assert_leak_free_schema
from .splits import SplitPlan, build_inner_selection_split


@dataclass(frozen=True)
class RankingModelSpec:
    name: str
    family: str
    feature_schema: tuple[str, ...]
    parameters: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    seed: int = 17

    def parameter_dict(self) -> dict[str, Any]:
        return dict(self.parameters)


def build_fixed_baseline_predictions(
    rows: pd.DataFrame,
    baseline_definitions: Sequence[tuple[str, str]],
) -> pd.DataFrame:
    result = rows.copy()
    for name, definition in baseline_definitions:
        output = f"score__{name}"
        kind, _, source = str(definition).partition(":")
        if kind == "column":
            if source not in result:
                raise ValueError(f"baseline {name} missing source column: {source}")
            result[output] = pd.to_numeric(result[source], errors="coerce").astype("float32")
        elif kind == "column_descending":
            if source not in result:
                raise ValueError(f"baseline {name} missing source column: {source}")
            result[output] = -pd.to_numeric(result[source], errors="coerce").astype("float32")
        elif kind == "deterministic_hash":
            result[output] = [
                _hash_score(str(date), str(symbol), str(source))
                for date, symbol in zip(result["trade_date"], result["symbol"], strict=True)
            ]
        else:
            raise ValueError(f"unsupported baseline definition for {name}: {definition}")
    return result


def run_nested_ranking_oof(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    model_specs: tuple[RankingModelSpec, ...],
    *,
    checkpoint_dir: str | Path | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    if not model_specs:
        raise ValueError("model_specs cannot be empty")
    names = [spec.name for spec in model_specs]
    if len(names) != len(set(names)):
        raise ValueError("model spec names must be unique")
    data = rows.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if (~data["trade_date"].isin(split_plan.development_dates)).any():
        raise PermissionError("ranking OOF accepts development dates only")
    for spec in model_specs:
        assert_leak_free_schema(spec.feature_schema)
        missing = sorted(set(spec.feature_schema) - set(data.columns))
        if missing:
            raise ValueError(f"model {spec.name} missing features: " + ", ".join(missing))

    selection: dict[str, list[dict[str, float]]] = {spec.name: [] for spec in model_specs}
    iteration_evidence: dict[str, list[int]] = {spec.name: [] for spec in model_specs}
    for fold in split_plan.walk_forward:
        inner = build_inner_selection_split(_contract_like(model_specs, fold), fold)
        fit = _a_rows(data, inner.fit_dates, fold.training_symbols)
        early = _a_rows(data, inner.early_stop_dates, fold.training_symbols)
        select = _a_rows(data, inner.selection_dates, fold.training_symbols)
        for spec in model_specs:
            predicted, iterations = _fit_predict_spec(spec, fit, select, early_stop_rows=early)
            selection[spec.name].append(_selection_metrics(predicted))
            iteration_evidence[spec.name].append(iterations)

    selection_summary = {
        name: {
            key: float(np.mean([fold[key] for fold in folds]))
            for key in ("ndcg_at_10", "top5_return", "precision_at_5")
        }
        for name, folds in selection.items()
    }
    selected_name = max(
        sorted(selection_summary),
        key=lambda name: (
            selection_summary[name]["ndcg_at_10"],
            selection_summary[name]["top5_return"],
            selection_summary[name]["precision_at_5"],
        ),
    )
    selected_spec = next(spec for spec in model_specs if spec.name == selected_name)
    fixed_iterations = int(np.median(iteration_evidence[selected_name]))
    checkpoint_root = Path(checkpoint_dir) if checkpoint_dir is not None else None
    predictions = []
    for fold in split_plan.walk_forward:
        checkpoint = checkpoint_root / f"fold-{fold.fold}.parquet" if checkpoint_root else None
        if resume and checkpoint and checkpoint.is_file():
            fold_predictions = pd.read_parquet(checkpoint)
        else:
            train = _a_rows(data, fold.training_dates, fold.training_symbols)
            validation_symbols = set(fold.training_symbols) | set(split_plan.C_dev_unseen_symbols)
            validation = data.loc[
                data["trade_date"].isin(fold.validation_dates)
                & data["symbol"].isin(validation_symbols)
            ].copy()
            spec = selected_spec
            if spec.family == "lightgbm_lambdarank":
                parameters = dict(spec.parameters)
                parameters["n_estimators"] = fixed_iterations
                spec = RankingModelSpec(spec.name, spec.family, spec.feature_schema, tuple(sorted(parameters.items())), spec.seed)
            fold_predictions, _ = _fit_predict_spec(spec, train, validation, early_stop_rows=None)
            fold_predictions["fold"] = fold.fold
            fold_predictions["quadrant"] = np.where(
                fold_predictions["symbol"].isin(split_plan.C_dev_unseen_symbols), "C", "A"
            )
            if checkpoint:
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                fold_predictions.to_parquet(checkpoint, compression="zstd", index=False)
        predictions.append(fold_predictions)
    return {
        "selected_spec": selected_name,
        "selected_family": selected_spec.family,
        "selected_features": list(selected_spec.feature_schema),
        "fixed_iterations": fixed_iterations,
        "selection_evidence": selection_summary,
        "predictions": pd.concat(predictions, ignore_index=True),
    }


def _fit_predict_spec(
    spec: RankingModelSpec,
    train_rows: pd.DataFrame,
    validation_rows: pd.DataFrame,
    *,
    early_stop_rows: pd.DataFrame | None,
) -> tuple[pd.DataFrame, int]:
    if spec.family == "linear_scorecard":
        return RegisteredBaselineTrainer().fit_predict(train_rows, validation_rows, spec.feature_schema), 1
    if spec.family != "lightgbm_lambdarank":
        raise ValueError(f"unsupported ranking family: {spec.family}")
    try:
        import lightgbm as lgb
    except ImportError as error:
        raise RuntimeError("lightgbm is required for the registered LambdaRank candidate") from error
    parameters = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "learning_rate": 0.03,
        "n_estimators": 200,
        "num_leaves": 15,
        "max_depth": 5,
        "min_child_samples": 200,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
        "random_state": spec.seed,
        "n_jobs": 4,
        "verbosity": -1,
        **spec.parameter_dict(),
    }
    train = train_rows.sort_values(["trade_date", "symbol"], kind="stable").copy()
    validation = validation_rows.sort_values(["trade_date", "symbol"], kind="stable").copy()
    train_x = _date_rank_matrix(train, spec.feature_schema).fillna(0.5).astype("float32")
    valid_x = _date_rank_matrix(validation, spec.feature_schema).fillna(0.5).astype("float32")
    train_y = pd.to_numeric(train["alpha_relevance_grade_10d"], errors="coerce").fillna(0).astype("int32")
    model = lgb.LGBMRanker(**parameters)
    fit_kwargs: dict[str, Any] = {
        "group": train.groupby("trade_date", sort=False).size().tolist(),
        "eval_at": [5, 10],
    }
    if early_stop_rows is not None and not early_stop_rows.empty:
        early = early_stop_rows.sort_values(["trade_date", "symbol"], kind="stable").copy()
        early_x = _date_rank_matrix(early, spec.feature_schema).fillna(0.5).astype("float32")
        early_y = pd.to_numeric(early["alpha_relevance_grade_10d"], errors="coerce").fillna(0).astype("int32")
        fit_kwargs.update(
            {
                "eval_set": [(early_x, early_y)],
                "eval_group": [early.groupby("trade_date", sort=False).size().tolist()],
                "callbacks": [lgb.early_stopping(20, verbose=False)],
            }
        )
    model.fit(train_x, train_y, **fit_kwargs)
    result = validation.copy()
    result["score"] = model.predict(valid_x).astype("float32")
    return result, int(getattr(model, "best_iteration_", 0) or parameters["n_estimators"])


def _a_rows(rows: pd.DataFrame, dates: Sequence[str], symbols: Sequence[str]) -> pd.DataFrame:
    return rows.loc[rows["trade_date"].isin(dates) & rows["symbol"].isin(symbols)].copy()


def _selection_metrics(predictions: pd.DataFrame) -> dict[str, float]:
    daily = []
    for _, frame in predictions.groupby("trade_date", sort=True):
        ranked = frame.sort_values(["score", "symbol"], ascending=[False, True], kind="stable")
        grades = pd.to_numeric(ranked["alpha_relevance_grade_10d"], errors="coerce").fillna(0).to_numpy()
        ideal = np.sort(grades)[::-1][:10]
        discount = np.log2(np.arange(min(10, len(grades))) + 2)
        dcg = np.sum((2 ** grades[:10] - 1) / discount)
        idcg = np.sum((2 ** ideal - 1) / discount)
        top5 = ranked.head(5)
        daily.append(
            {
                "ndcg_at_10": float(dcg / idcg) if idcg else 0.0,
                "top5_return": float(pd.to_numeric(top5["net_return_after_cost_10d"], errors="coerce").mean()),
                "precision_at_5": float(top5["alpha_top10_10d"].astype(bool).mean()),
            }
        )
    return {key: float(np.mean([item[key] for item in daily])) for key in daily[0]} if daily else {
        "ndcg_at_10": 0.0,
        "top5_return": 0.0,
        "precision_at_5": 0.0,
    }


def _hash_score(trade_date: str, symbol: str, salt: str) -> float:
    value = hashlib.sha256(f"{trade_date}|{symbol}|{salt}".encode()).digest()[:8]
    return int.from_bytes(value, "big") / float(2**64 - 1)


def _contract_like(model_specs: tuple[RankingModelSpec, ...], fold) -> Any:
    """Build only the frozen inner-date minimum interface required by the split helper."""
    del model_specs, fold
    from .research_contract import RankingResearchContract

    return RankingResearchContract(
        dataset_id="nested-ranking",
        run_id="nested-ranking",
        feature_blocks=(("registered", ("adjusted_return_20d",)),),
    )
