"""Fixed-contract, development-only return-label ranking experiment."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .evaluator import bootstrap_uplift, evaluate_ranking, simulate_daily_topk_portfolio
from .features import assert_leak_free_schema
from .label_split import add_return_only_labels
from .splits import FinalHoldoutAccessError, SplitPlan
from .trainer import FIXED_SEEDS, _development_dataset, _ranker_oof, _stable_random_score, _unseen_stock_oof


RETURN_RANKING_LABEL = "return_relevance_grade_10d"
RETURN_STRONG_LABEL = "label_return_top10_10d"
FROZEN_V3_RANKER_PARAMS = {"num_leaves": 15, "max_depth": 4, "min_data_in_leaf": 200}
_REQUIRED_DATA_COLUMNS = {
    "trade_date",
    "symbol",
    "eligible_for_training",
    "future_return_10d",
    "net_return_after_cost_10d",
    "relevance_grade_10d",
    "label_strong_path_10d",
    "label_severe_negative_10d",
}


@dataclass(frozen=True)
class LabelSplitExperiment:
    """Read-only development evidence for the pre-registered label split."""

    ranking_label: str
    strong_label: str
    source_contract_sha256: str
    checkpoint_contract: str
    predictions: pd.DataFrame
    quadrant_metrics: dict[str, dict[str, Any]]
    baseline_metrics: dict[str, dict[str, dict[str, Any]]]
    bootstrap: dict[str, dict[str, Any]]
    portfolios: dict[str, dict[str, Any]]


def run_label_split_experiment(
    dataset: pd.DataFrame,
    split_plan: SplitPlan,
    selected_features: Sequence[str],
    *,
    checkpoint_dir: str | Path,
    source_contract: Mapping[str, Any],
) -> LabelSplitExperiment:
    """Run fixed V3 rankers only on development A/C rows and return OOF evidence.

    This function deliberately refuses final-time rows before deriving the new
    target, fitting a model, or reading any B/D labels. It neither selects
    hyperparameters nor creates a final-fit artifact.
    """
    features = tuple(str(feature) for feature in selected_features)
    contract_sha256 = _validate_source_contract(source_contract, split_plan, features)
    development = _normalize_development_input(dataset, split_plan)
    missing_features = sorted(set(features) - set(development.columns))
    if missing_features:
        raise ValueError("dataset missing frozen V3 features: " + ", ".join(missing_features))
    assert_leak_free_schema(features)

    labeled = add_return_only_labels(development)
    labeled = labeled.loc[labeled[RETURN_RANKING_LABEL].notna()].copy()
    if labeled.empty:
        raise ValueError("development dataset has no finite return-only labels")

    all_development_symbols = tuple(sorted(set(split_plan.A_dev_train_symbols) | set(split_plan.C_dev_unseen_symbols)))
    a_rows = _development_dataset(labeled, split_plan)
    a_and_c_rows = _development_dataset(labeled, split_plan, symbols=all_development_symbols)
    checkpoint_contract = _label_split_checkpoint_contract(
        a_and_c_rows,
        split_plan,
        features,
        source_contract_sha256=contract_sha256,
    )
    cache: dict[tuple[Any, ...], Any] = {}
    params = dict(FROZEN_V3_RANKER_PARAMS)
    seeds = tuple(FIXED_SEEDS)
    a_predictions = _ranker_oof(
        a_rows,
        split_plan,
        features,
        params,
        seeds,
        ranking_label_col=RETURN_RANKING_LABEL,
        dataset_cache=cache,
        checkpoint_dir=checkpoint_dir,
        checkpoint_key="return-label-a-time-oof",
        checkpoint_contract=checkpoint_contract,
    )
    c_predictions = _unseen_stock_oof(
        a_and_c_rows,
        split_plan,
        features,
        params,
        seeds,
        ranking_label_col=RETURN_RANKING_LABEL,
        dataset_cache=cache,
        checkpoint_dir=checkpoint_dir,
        checkpoint_key="return-label-c-dev-unseen",
        checkpoint_contract=checkpoint_contract,
    )
    quadrants = {"A_time_oof": a_predictions, "C_dev_unseen": c_predictions}
    metrics = {
        name: _return_metrics(rows) if not rows.empty else {"status": "unavailable"}
        for name, rows in quadrants.items()
    }
    baselines = {
        name: _fixed_baselines(rows) if not rows.empty else {"status": "unavailable"}
        for name, rows in quadrants.items()
    }
    bootstrap = {
        name: _bootstrap_against_amount(rows) if not rows.empty else {"status": "unavailable"}
        for name, rows in quadrants.items()
    }
    portfolios = {
        name: _portfolio_or_unavailable(rows) if not rows.empty else {"status": "unavailable"}
        for name, rows in quadrants.items()
    }
    predictions = pd.concat([a_predictions, c_predictions], ignore_index=True, sort=False)
    return LabelSplitExperiment(
        ranking_label=RETURN_RANKING_LABEL,
        strong_label=RETURN_STRONG_LABEL,
        source_contract_sha256=contract_sha256,
        checkpoint_contract=checkpoint_contract,
        predictions=predictions.sort_values(["quadrant", "trade_date", "symbol"], kind="stable").reset_index(drop=True),
        quadrant_metrics=metrics,
        baseline_metrics=baselines,
        bootstrap=bootstrap,
        portfolios=portfolios,
    )


def _normalize_development_input(dataset: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    if not isinstance(dataset, pd.DataFrame):
        raise TypeError("dataset must be a pandas DataFrame")
    missing = sorted(_REQUIRED_DATA_COLUMNS - set(dataset.columns))
    if missing:
        raise ValueError("development dataset missing columns: " + ", ".join(missing))
    result = dataset.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if result["trade_date"].isna().any() or result["trade_date"].isin(split_plan.final_dates).any():
        raise FinalHoldoutAccessError("label-split experiment cannot read final holdout dates")
    if (~result["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("label-split experiment cannot read unplanned dates")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("development dataset contains duplicate trade_date and symbol rows")
    known_symbols = set(split_plan.A_dev_train_symbols) | set(split_plan.C_dev_unseen_symbols)
    eligible_symbols = set(result.loc[result["eligible_for_training"].eq(True), "symbol"])
    unknown_symbols = sorted(eligible_symbols - known_symbols)
    if unknown_symbols:
        raise ValueError("development dataset contains symbols outside the frozen split")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _validate_source_contract(
    source_contract: Mapping[str, Any], split_plan: SplitPlan, selected_features: tuple[str, ...]
) -> str:
    if not isinstance(source_contract, Mapping):
        raise TypeError("source_contract must be a mapping")
    if str(source_contract.get("split_sha256", "")) != split_plan.split_sha256:
        raise ValueError("frozen V3 source contract split SHA does not match the requested split")
    source_features = tuple(str(feature) for feature in source_contract.get("selected_features", ()))
    if not source_features or source_features != selected_features:
        raise ValueError("frozen V3 source contract features do not match the requested feature list")
    if len(set(selected_features)) != len(selected_features):
        raise ValueError("frozen V3 source contract contains duplicate features")
    source_params = source_contract.get("selected_ranker_params", source_contract.get("params"))
    if not isinstance(source_params, Mapping) or dict(source_params) != FROZEN_V3_RANKER_PARAMS:
        raise ValueError("label-split experiment requires the frozen V3 ranker parameters")
    source_seeds = tuple(int(seed) for seed in source_contract.get("seeds", ()))
    if source_seeds != FIXED_SEEDS:
        raise ValueError(f"label-split experiment requires the frozen V3 seeds {FIXED_SEEDS}")
    payload = json.dumps(dict(source_contract), ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _label_split_checkpoint_contract(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    features: tuple[str, ...],
    *,
    source_contract_sha256: str,
) -> str:
    columns = ["trade_date", "symbol", RETURN_RANKING_LABEL, *features]
    digest = hashlib.sha256()
    ordered = rows.loc[:, columns].sort_values(["trade_date", "symbol"], kind="stable")
    for start in range(0, len(ordered), 10_000):
        chunk = ordered.iloc[start:start + 10_000]
        digest.update(pd.util.hash_pandas_object(chunk, index=False, categorize=True).to_numpy(dtype="uint64").tobytes())
    payload = {
        "schema_version": 1,
        "source_contract_sha256": source_contract_sha256,
        "split_sha256": split_plan.split_sha256,
        "ranking_label": RETURN_RANKING_LABEL,
        "features": list(features),
        "seeds": list(FIXED_SEEDS),
        "params": FROZEN_V3_RANKER_PARAMS,
        "signal_label_feature_sha256": digest.hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _return_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    return evaluate_ranking(
        rows,
        grade_col=RETURN_RANKING_LABEL,
        strong_col=RETURN_STRONG_LABEL,
    )


def _fixed_baselines(rows: pd.DataFrame) -> dict[str, dict[str, Any]]:
    baselines: dict[str, dict[str, Any]] = {}
    baseline_columns = {
        "random": None,
        "adjusted_return_20d": "adjusted_return_20d",
        "adjusted_return_60d": "adjusted_return_60d",
        "amount_log": "amount_log",
    }
    for name, column in baseline_columns.items():
        if column is not None and column not in rows:
            baselines[name] = {"status": "unavailable"}
            continue
        score = _stable_random_score(rows) if column is None else pd.to_numeric(rows[column], errors="coerce")
        valid_rows = rows.loc[pd.Series(score, index=rows.index).notna()].copy()
        if valid_rows.empty:
            baselines[name] = {"status": "unavailable"}
            continue
        valid_score = _stable_random_score(valid_rows) if column is None else pd.to_numeric(valid_rows[column], errors="coerce")
        baselines[name] = {
            "status": "available",
            "score_valid_candidate_count": int(len(valid_rows)),
            "score_valid_date_count": int(valid_rows["trade_date"].nunique()),
            "score_coverage": float(len(valid_rows) / len(rows)),
            "model_metrics_on_matching_rows": _return_metrics(valid_rows),
            **evaluate_ranking(
                valid_rows.assign(score=valid_score),
                grade_col=RETURN_RANKING_LABEL,
                strong_col=RETURN_STRONG_LABEL,
            ),
        }
    return baselines


def _bootstrap_against_amount(rows: pd.DataFrame) -> dict[str, Any]:
    if "amount_log" not in rows or pd.to_numeric(rows["amount_log"], errors="coerce").isna().any():
        return {"status": "unavailable"}
    return {
        "status": "available",
        **bootstrap_uplift(
            rows,
            baseline_score_col="amount_log",
            grade_col=RETURN_RANKING_LABEL,
            strong_col=RETURN_STRONG_LABEL,
        ),
    }


def _portfolio_or_unavailable(rows: pd.DataFrame) -> dict[str, Any]:
    try:
        return {"status": "available", **simulate_daily_topk_portfolio(rows)}
    except ValueError as error:
        return {"status": "unavailable", "reason": str(error)}
