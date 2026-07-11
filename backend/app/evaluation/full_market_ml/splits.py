"""Deterministic, sealed evaluation splits for full-market ML research."""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd

from .config import FullMarketMLConfig


STOCK_HOLDOUT_RATIO = 0.20
STOCK_HOLDOUT_SEED = 42
RARE_STRATUM_MIN_SYMBOLS = 5


class FinalHoldoutAccessError(PermissionError):
    """Raised when final-time quadrants are accessed before model freeze."""


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    training_dates: tuple[str, ...]
    validation_dates: tuple[str, ...]
    training_symbols: tuple[str, ...]
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.fold,
            "training_dates": list(self.training_dates),
            "validation_dates": list(self.validation_dates),
            "training_symbols": list(self.training_symbols),
            "train_start": self.train_start,
            "train_end": self.train_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
        }


@dataclass(frozen=True)
class SplitPlan:
    """Exact split membership, with final-time data gated by model freeze."""

    development_dates: tuple[str, ...]
    final_dates: tuple[str, ...]
    stock_holdout_symbols: tuple[str, ...]
    A_dev_train_symbols: tuple[str, ...]
    B_final_train_symbols: tuple[str, ...]
    C_dev_unseen_symbols: tuple[str, ...]
    D_final_unseen_symbols: tuple[str, ...]
    walk_forward: tuple[WalkForwardFold, ...]
    stratum_counts_before: dict[str, int]
    stratum_counts_after: dict[str, int]
    split_sha256: str
    final_holdout_frozen_model_sha: str | None = None

    def seal_final_holdout(self, model_sha256: str) -> "SplitPlan":
        """Return a plan carrying the immutable SHA of the frozen model manifest."""
        model_sha256 = str(model_sha256).strip()
        if not model_sha256:
            raise ValueError("model_sha256 is required to seal the final holdout")
        return replace(self, final_holdout_frozen_model_sha=model_sha256)

    def load_quadrant(self, quadrant: str, *, frozen_model_sha: str | None) -> tuple[str, ...]:
        """Expose quadrant membership, blocking final-time quadrants until freeze."""
        quadrant = str(quadrant).upper()
        quadrants = {
            "A": self.A_dev_train_symbols,
            "B": self.B_final_train_symbols,
            "C": self.C_dev_unseen_symbols,
            "D": self.D_final_unseen_symbols,
        }
        if quadrant not in quadrants:
            raise ValueError("quadrant must be one of A, B, C, or D")
        if quadrant in {"B", "D"} and (
            not self.final_holdout_frozen_model_sha or frozen_model_sha != self.final_holdout_frozen_model_sha
        ):
            raise FinalHoldoutAccessError("final holdout is sealed until the matching model freeze manifest exists")
        return quadrants[quadrant]

    def to_dict(self) -> dict[str, Any]:
        return {
            "development_dates": list(self.development_dates),
            "final_dates": list(self.final_dates),
            "stock_holdout_symbols": list(self.stock_holdout_symbols),
            "quadrants": {
                "A_dev_train_symbols": list(self.A_dev_train_symbols),
                "B_final_train_symbols": list(self.B_final_train_symbols),
                "C_dev_unseen_symbols": list(self.C_dev_unseen_symbols),
                "D_final_unseen_symbols": list(self.D_final_unseen_symbols),
            },
            "walk_forward": [fold.to_dict() for fold in self.walk_forward],
            "stratum_counts_before": dict(sorted(self.stratum_counts_before.items())),
            "stratum_counts_after": dict(sorted(self.stratum_counts_after.items())),
            "split_sha256": self.split_sha256,
            "final_holdout_frozen_model_sha": self.final_holdout_frozen_model_sha,
        }


def build_split_plan(config: FullMarketMLConfig, labeled_dataset: pd.DataFrame) -> SplitPlan:
    """Build reproducible development folds and sealed final-time quadrants."""
    dataset = _normalize_labeled_dataset(labeled_dataset)
    final_dates = tuple(sorted(dataset.loc[dataset["trade_date"].between(config.dates.holdout_start, config.dates.holdout_end), "trade_date"].unique()))
    development = dataset.loc[dataset["trade_date"] < config.dates.holdout_start].copy()
    development_dates = tuple(sorted(development["trade_date"].unique()))
    if not development_dates or not final_dates:
        raise ValueError("split plan requires both development and final holdout rows")

    strata, stratum_counts_before = _development_strata(development)
    holdout_symbols, stratum_counts_after = _select_stock_holdout(strata)
    all_symbols = tuple(sorted(strata))
    training_symbols = tuple(symbol for symbol in all_symbols if symbol not in set(holdout_symbols))
    folds = _walk_forward_folds(config, development_dates, training_symbols)
    payload = {
        "config_sha256": config.sha256,
        "development_dates": list(development_dates),
        "final_dates": list(final_dates),
        "stock_holdout_symbols": list(holdout_symbols),
        "training_symbols": list(training_symbols),
        "walk_forward": [fold.to_dict() for fold in folds],
        "stratum_counts_before": dict(sorted(stratum_counts_before.items())),
        "stratum_counts_after": dict(sorted(stratum_counts_after.items())),
    }
    split_sha256 = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return SplitPlan(
        development_dates=development_dates,
        final_dates=final_dates,
        stock_holdout_symbols=holdout_symbols,
        A_dev_train_symbols=training_symbols,
        B_final_train_symbols=training_symbols,
        C_dev_unseen_symbols=holdout_symbols,
        D_final_unseen_symbols=holdout_symbols,
        walk_forward=folds,
        stratum_counts_before=stratum_counts_before,
        stratum_counts_after=stratum_counts_after,
        split_sha256=split_sha256,
    )


def _normalize_labeled_dataset(labeled_dataset: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(labeled_dataset, pd.DataFrame):
        raise TypeError("labeled_dataset must be a pandas DataFrame")
    required = {"trade_date", "symbol", "industry_l1", "total_mv", "amount_cny"}
    missing = sorted(required - set(labeled_dataset.columns))
    if missing:
        raise ValueError("labeled_dataset missing columns: " + ", ".join(missing))
    dataset = labeled_dataset.copy()
    dataset["trade_date"] = pd.to_datetime(dataset["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    dataset["symbol"] = dataset["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    dataset["industry_l1"] = dataset["industry_l1"].astype("string").fillna("UNKNOWN")
    dataset["total_mv"] = pd.to_numeric(dataset["total_mv"], errors="coerce")
    dataset["amount_cny"] = pd.to_numeric(dataset["amount_cny"], errors="coerce")
    if "eligible_for_training" in dataset:
        dataset = dataset.loc[dataset["eligible_for_training"].eq(True)].copy()
    dataset = dataset.dropna(subset=["trade_date", "total_mv", "amount_cny"])
    dataset = dataset.loc[dataset["symbol"].ne("") & dataset["total_mv"].ge(0) & dataset["amount_cny"].ge(0)]
    if dataset.empty:
        raise ValueError("labeled_dataset has no eligible rows for split planning")
    return dataset.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _development_strata(development: pd.DataFrame) -> tuple[dict[str, str], dict[str, int]]:
    summary = development.groupby("symbol", sort=True).agg(
        industry_l1=("industry_l1", "first"),
        median_market_cap=("total_mv", "median"),
        median_liquidity=("amount_cny", "median"),
    )
    summary["board"] = summary.index.to_series().map(_board_for_symbol)
    summary["size_tertile"] = _tertiles(summary["median_market_cap"])
    summary["liquidity_tertile"] = _tertiles(summary["median_liquidity"])
    full = summary.apply(lambda row: _stratum_key(row["board"], row["industry_l1"], row["size_tertile"], row["liquidity_tertile"]), axis=1)
    full_counts = full.value_counts().to_dict()
    selected = {}
    for symbol, row in summary.iterrows():
        full_key = full.loc[symbol]
        selected[symbol] = full_key if full_counts[full_key] >= RARE_STRATUM_MIN_SYMBOLS else _fallback_stratum_key(row["board"], row["size_tertile"], row["liquidity_tertile"])
    return selected, {str(key): int(value) for key, value in sorted(full_counts.items())}


def _tertiles(values: pd.Series) -> pd.Series:
    ranked = sorted((float(value), str(symbol)) for symbol, value in values.items())
    count = len(ranked)
    labels = {symbol: min(2, index * 3 // count) for index, (_, symbol) in enumerate(ranked)}
    return pd.Series(labels).reindex(values.index).astype("int64")


def _select_stock_holdout(strata: dict[str, str]) -> tuple[tuple[str, ...], dict[str, int]]:
    by_stratum: dict[str, list[str]] = {}
    for symbol, stratum in strata.items():
        by_stratum.setdefault(stratum, []).append(symbol)
    for symbols in by_stratum.values():
        symbols.sort()
    symbol_count = len(strata)
    target = min(symbol_count - 1, max(1, round(symbol_count * STOCK_HOLDOUT_RATIO)))
    quotas = {stratum: int(len(symbols) * STOCK_HOLDOUT_RATIO) for stratum, symbols in by_stratum.items()}
    remaining = target - sum(quotas.values())
    remainders = sorted(
        ((len(symbols) * STOCK_HOLDOUT_RATIO - quotas[stratum], stratum) for stratum, symbols in by_stratum.items()),
        key=lambda item: (-item[0], item[1]),
    )
    for _, stratum in remainders[:remaining]:
        quotas[stratum] += 1

    generator = random.Random(STOCK_HOLDOUT_SEED)
    selected = []
    for stratum in sorted(by_stratum):
        candidates = by_stratum[stratum]
        selected.extend(generator.sample(candidates, quotas[stratum]))
    return tuple(sorted(selected)), {stratum: quotas[stratum] for stratum in sorted(quotas)}


def _walk_forward_folds(
    config: FullMarketMLConfig, development_dates: tuple[str, ...], training_symbols: tuple[str, ...]
) -> tuple[WalkForwardFold, ...]:
    fold_count = config.splits.walk_forward_folds
    embargo = config.splits.embargo_trade_days
    if fold_count != 5:
        raise ValueError("full-market split plan requires exactly five walk-forward folds")
    validation_count = len(development_dates) // (fold_count + 1)
    first_validation_index = len(development_dates) - validation_count * fold_count
    if validation_count <= 0 or first_validation_index <= embargo:
        raise ValueError("development calendar is too short for five embargoed walk-forward folds")
    folds = []
    for index in range(fold_count):
        validation_start_index = first_validation_index + index * validation_count
        validation_dates = development_dates[validation_start_index:validation_start_index + validation_count]
        training_dates = development_dates[:validation_start_index - embargo]
        if not training_dates or not validation_dates:
            raise ValueError("development calendar cannot form an embargoed expanding fold")
        folds.append(
            WalkForwardFold(
                fold=index + 1,
                training_dates=training_dates,
                validation_dates=validation_dates,
                training_symbols=training_symbols,
                train_start=training_dates[0],
                train_end=training_dates[-1],
                validation_start=validation_dates[0],
                validation_end=validation_dates[-1],
            )
        )
    return tuple(folds)


def _board_for_symbol(symbol: str) -> str:
    if symbol.startswith(("300", "301")):
        return "CHINEXT"
    if symbol.startswith(("688", "689")):
        return "STAR"
    return "MAIN"


def _stratum_key(board: str, industry: str, size_tertile: int, liquidity_tertile: int) -> str:
    return f"{board}|{industry}|size={size_tertile}|liquidity={liquidity_tertile}"


def _fallback_stratum_key(board: str, size_tertile: int, liquidity_tertile: int) -> str:
    return f"{board}|size={size_tertile}|liquidity={liquidity_tertile}"
