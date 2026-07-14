from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.ablation import run_nested_block_ablation
from app.evaluation.full_market_ml.baseline_model import RegisteredBaselineTrainer
from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold


class NestedBlockAblationTests(unittest.TestCase):
    def test_strong_feature_passes_and_noise_feature_fails_actual_oof_gate(self):
        rows, plan = _fixture()

        decisions = run_nested_block_ablation(
            rows,
            plan,
            ("base",),
            {"strong": ("signal",), "noise": ("noise",)},
            RegisteredBaselineTrainer(),
        )

        by_name = {decision.name: decision for decision in decisions}
        self.assertEqual(by_name["strong"].status, "accepted_alpha")
        self.assertEqual(by_name["noise"].status, "rejected")

    def test_high_coverage_stable_block_is_rejected_when_actual_oof_uplift_is_negative(self):
        rows, plan = _fixture()

        decision = run_nested_block_ablation(
            rows,
            plan,
            ("signal",),
            {"harmful": ("harmful",)},
            _HarmfulTrainer(),
        )[0]

        self.assertEqual(decision.coverage, 1.0)
        self.assertEqual(decision.status, "rejected")
        self.assertIn("negative_actual_oof_uplift", decision.reasons)

    def test_every_outer_fold_reselects_block_using_inner_dates_only(self):
        rows, plan = _fixture()
        trainer = _RecordingTrainer()

        run_nested_block_ablation(
            rows,
            plan,
            ("base",),
            {"strong": ("signal",)},
            trainer,
        )

        self.assertEqual(len({fold for fold, _ in trainer.inner_calls}), 5)
        self.assertTrue(all(train_end < validation_start for _, (train_end, validation_start) in trainer.inner_calls))
        self.assertTrue(all(validation_start < outer_start for _, (_, validation_start, outer_start) in trainer.outer_calls))


class _HarmfulTrainer:
    def fit_predict(self, train_rows, validation_rows, feature_schema):
        result = validation_rows.copy()
        result["score"] = result["signal"] if "harmful" not in feature_schema else -result["signal"]
        return result


class _RecordingTrainer(RegisteredBaselineTrainer):
    def __init__(self):
        super().__init__()
        self.inner_calls = []
        self.outer_calls = []

    def fit_predict(self, train_rows, validation_rows, feature_schema):
        fold = int(validation_rows["fold"].iloc[0])
        train_end = str(train_rows["trade_date"].max())
        validation_start = str(validation_rows["trade_date"].min())
        if validation_rows["role"].eq("inner").all():
            self.inner_calls.append((fold, (train_end, validation_start)))
        else:
            self.outer_calls.append((fold, (train_end, str(train_rows["trade_date"].min()), validation_start)))
        return super().fit_predict(train_rows, validation_rows, feature_schema)


def _fixture() -> tuple[pd.DataFrame, SplitPlan]:
    dates = tuple(pd.bdate_range("2024-01-02", periods=220).strftime("%Y-%m-%d"))
    symbols = tuple(f"{index + 1:06d}" for index in range(30))
    rows = []
    rng = np.random.default_rng(17)
    for date_index, trade_date in enumerate(dates):
        random_order = rng.permutation(len(symbols))
        for index, symbol in enumerate(symbols):
            signal = index / len(symbols)
            base = ((index * 7 + date_index) % len(symbols)) / len(symbols)
            noise = random_order[index] / len(symbols)
            alpha = signal / 10.0
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "fold": 0,
                    "role": "outer",
                    "base": base,
                    "signal": signal,
                    "noise": noise,
                    "harmful": signal,
                    "alpha_target_10d": alpha,
                    "alpha_top10_10d": index >= 27,
                    "alpha_relevance_grade_10d": 4 if index >= 29 else (3 if index >= 27 else 0),
                    "net_return_after_cost_10d": alpha,
                    "severe_negative_10d": index < 3,
                }
            )
    folds = []
    for index in range(5):
        validation_start = 120 + index * 20
        validation = dates[validation_start:validation_start + 20]
        train = dates[: validation_start - 20]
        folds.append(
            WalkForwardFold(
                fold=index + 1,
                training_dates=train,
                validation_dates=validation,
                training_symbols=symbols,
                train_start=train[0],
                train_end=train[-1],
                validation_start=validation[0],
                validation_end=validation[-1],
            )
        )
    plan = SplitPlan(
        development_dates=dates,
        final_dates=("2026-01-02",),
        stock_holdout_symbols=(),
        A_dev_train_symbols=symbols,
        B_final_train_symbols=symbols,
        C_dev_unseen_symbols=(),
        D_final_unseen_symbols=(),
        walk_forward=tuple(folds),
        stratum_counts_before={},
        stratum_counts_after={},
        split_sha256="ablation-fixture",
    )
    return pd.DataFrame(rows), plan


if __name__ == "__main__":
    unittest.main()
