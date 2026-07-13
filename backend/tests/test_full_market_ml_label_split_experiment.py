from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pandas as pd

from app.evaluation.full_market_ml import label_split_experiment as experiment_module
from app.evaluation.full_market_ml.label_split_experiment import (
    FROZEN_V3_RANKER_PARAMS,
    run_label_split_experiment,
)
from app.evaluation.full_market_ml.splits import FinalHoldoutAccessError
from app.evaluation.full_market_ml.trainer import FIXED_SEEDS
from tests.full_market_ml_fixtures import predictive_fixture, sealed_split_fixture
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLLabelSplitExperimentTests(FullMarketMLTestCase):
    def _split(self):
        base = sealed_split_fixture(symbols_per_date=220)
        train_symbols = tuple(f"{index + 1:06d}" for index in range(200))
        unseen_symbols = tuple(f"{index + 201:06d}" for index in range(20))
        return replace(
            base,
            A_dev_train_symbols=train_symbols,
            C_dev_unseen_symbols=unseen_symbols,
            walk_forward=tuple(replace(fold, training_symbols=train_symbols) for fold in base.walk_forward),
        )

    @staticmethod
    def _features():
        return ("adjusted_return_20d", "amount_log")

    def _source_contract(self, split, features=None):
        return {
            "split_sha256": split.split_sha256,
            "selected_features": list(features or self._features()),
            "selected_ranker_params": dict(FROZEN_V3_RANKER_PARAMS),
            "seeds": list(FIXED_SEEDS),
        }

    @staticmethod
    def _dataset():
        dataset = predictive_fixture(symbols_per_date=220)
        dataset["net_return_after_cost_10d"] = dataset["future_return_10d"]
        return dataset

    def test_runner_uses_only_return_label_and_preserves_a_c_quadrants(self):
        split = self._split()
        with patch.object(experiment_module, "_ranker_oof", wraps=experiment_module._ranker_oof) as ranker, patch.object(
            experiment_module, "_unseen_stock_oof", wraps=experiment_module._unseen_stock_oof
        ) as unseen_ranker:
            report = run_label_split_experiment(
                self._dataset(),
                split,
                self._features(),
                checkpoint_dir=self.temp_path / "checkpoints",
                source_contract=self._source_contract(split),
            )

        self.assertEqual(set(report.predictions["quadrant"]), {"A_time_oof", "C_dev_unseen"})
        self.assertEqual(report.ranking_label, "return_relevance_grade_10d")
        self.assertEqual(report.strong_label, "label_return_top10_10d")
        self.assertEqual(set(report.quadrant_metrics), {"A_time_oof", "C_dev_unseen"})
        self.assertFalse(report.predictions["trade_date"].isin(split.final_dates).any())
        self.assertEqual(ranker.call_args.kwargs["ranking_label_col"], "return_relevance_grade_10d")
        self.assertEqual(unseen_ranker.call_args.kwargs["ranking_label_col"], "return_relevance_grade_10d")

    def test_runner_rejects_nonfrozen_parameters(self):
        split = self._split()
        contract = self._source_contract(split)
        contract["selected_ranker_params"]["num_leaves"] = 31

        with self.assertRaisesRegex(ValueError, "frozen V3"):
            run_label_split_experiment(
                self._dataset(),
                split,
                self._features(),
                checkpoint_dir=self.temp_path / "checkpoints",
                source_contract=contract,
            )

    def test_runner_rejects_final_dates_and_missing_frozen_features(self):
        split = self._split()
        final_row = self._dataset().iloc[[0]].copy()
        final_row["trade_date"] = split.final_dates[0]
        with self.assertRaises(FinalHoldoutAccessError):
            run_label_split_experiment(
                pd.concat([self._dataset(), final_row], ignore_index=True),
                split,
                self._features(),
                checkpoint_dir=self.temp_path / "checkpoints",
                source_contract=self._source_contract(split),
            )

        with self.assertRaisesRegex(ValueError, "missing frozen V3 features"):
            run_label_split_experiment(
                self._dataset().drop(columns=["amount_log"]),
                split,
                self._features(),
                checkpoint_dir=self.temp_path / "checkpoints",
                source_contract=self._source_contract(split),
            )
