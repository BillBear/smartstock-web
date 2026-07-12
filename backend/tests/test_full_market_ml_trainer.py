from __future__ import annotations

from dataclasses import replace

from app.evaluation.full_market_ml.trainer import (
    FIXED_RANKER_GRID,
    FIXED_SEEDS,
    run_development_training,
    run_final_holdout_evaluation,
)
from app.evaluation.full_market_ml.splits import FinalHoldoutAccessError, SplitPlan
from tests.full_market_ml_fixtures import predictive_fixture, random_label_fixture, sealed_split_fixture
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLTrainerTests(FullMarketMLTestCase):
    @staticmethod
    def _split():
        return sealed_split_fixture(symbols_per_date=220)

    def test_model_selection_uses_only_oof_development_predictions(self):
        candidate = run_development_training(self.config, predictive_fixture(), self._split())

        self.assertEqual(candidate.selection_sources, ["A_walk_forward_oof"])
        self.assertNotIn("B_final_train_symbols", candidate.selection_sources)
        self.assertNotIn("D_final_unseen_symbols", candidate.selection_sources)
        self.assertEqual(set(candidate.oof_predictions["trade_date"]), set(self._split().development_dates[2:5]))

    def test_random_labels_cannot_receive_research_status(self):
        candidate = run_development_training(self.config, random_label_fixture(seed=42), self._split())

        self.assertEqual(candidate.preliminary_status, "research_only_failed_gate")
        self.assertTrue(candidate.failed_gates)

    def test_final_holdout_rows_are_rejected_before_training(self):
        dataset = predictive_fixture()
        final_rows = dataset.loc[dataset["trade_date"].eq(dataset["trade_date"].iloc[-1])].copy()
        final_rows["trade_date"] = "2025-02-03"
        with self.assertRaises(FinalHoldoutAccessError):
            run_development_training(self.config, final_rows, self._split())

    def test_predictive_rank_signal_beats_random_baseline(self):
        candidate = run_development_training(self.config, predictive_fixture(), self._split())

        self.assertGreater(candidate.oof_metrics["ndcg_at_10"], candidate.baselines["random"]["ndcg_at_10"])

    def test_uses_pre_registered_grid_seeds_calibration_risk_alphas_and_group_ablations(self):
        candidate = run_development_training(self.config, predictive_fixture(), self._split())

        self.assertEqual(candidate.fixed_ranker_grid, FIXED_RANKER_GRID)
        self.assertEqual(candidate.seeds, FIXED_SEEDS)
        self.assertEqual(set(candidate.calibrators), {"strong", "severe_negative"})
        self.assertEqual(candidate.risk_alphas, (0.0, 0.1, 0.2, 0.3))
        self.assertEqual([row["group"] for row in candidate.group_ablations], [
            "momentum", "amount_turnover", "technical", "risk", "market_industry", "moneyflow",
        ])
        self.assertTrue(all(row["status"] in {"accepted", "rejected", "unavailable"} for row in candidate.group_ablations))

    def test_frozen_candidate_manifest_records_the_exact_split_and_reproducible_selection_contract(self):
        split = self._split()
        candidate = run_development_training(self.config, predictive_fixture(), split)

        manifest = candidate.manifest(
            config_sha256="config-sha",
            data_sha256="data-sha",
            feature_schema_sha256="feature-schema-sha",
        )

        self.assertEqual(manifest["frozen_model_sha"], candidate.frozen_model_sha256)
        self.assertEqual(manifest["split_sha256"], split.split_sha256)
        self.assertEqual(manifest["selected_features"], list(candidate.selected_features))
        self.assertEqual(manifest["selected_ranker_params"], candidate.selected_ranker_params)

    def test_frozen_candidate_can_be_reconstructed_without_repeating_development_selection(self):
        candidate = run_development_training(self.config, predictive_fixture(), self._split())
        manifest = candidate.manifest(config_sha256="config", data_sha256="data", feature_schema_sha256="schema")

        restored = candidate.from_manifest(manifest)

        self.assertTrue(restored.oof_predictions.empty)
        self.assertEqual(restored.frozen_model_sha256, candidate.frozen_model_sha256)
        self.assertEqual(restored.selected_features, candidate.selected_features)
        self.assertEqual(restored.selected_ranker_params, candidate.selected_ranker_params)
        self.assertEqual(restored.calibrators, candidate.calibrators)

    def test_final_holdout_evaluation_requires_exactly_frozen_candidate_and_reports_all_quadrants(self):
        development = predictive_fixture(symbols_per_date=300)
        base_split = self._split()
        training_symbols = tuple(f"{index + 1:06d}" for index in range(240))
        unseen_symbols = tuple(f"{index + 1:06d}" for index in range(240, 300))
        split = SplitPlan(
            development_dates=base_split.development_dates,
            final_dates=("2025-02-03",),
            stock_holdout_symbols=unseen_symbols,
            A_dev_train_symbols=training_symbols,
            B_final_train_symbols=training_symbols,
            C_dev_unseen_symbols=unseen_symbols,
            D_final_unseen_symbols=unseen_symbols,
            walk_forward=tuple(replace(fold, training_symbols=training_symbols) for fold in base_split.walk_forward),
            stratum_counts_before={},
            stratum_counts_after={},
            split_sha256="final-holdout-fixture-split",
        )
        candidate = run_development_training(self.config, development, split)
        final_rows = development.loc[development["trade_date"].eq(development["trade_date"].iloc[-1])].copy()
        final_rows["trade_date"] = "2025-02-03"
        complete = __import__("pandas").concat([development, final_rows], ignore_index=True)

        with self.assertRaises(FinalHoldoutAccessError):
            run_final_holdout_evaluation(
                self.config,
                complete,
                split,
                candidate,
                frozen_model_sha="wrong-frozen-sha",
            )

        report = run_final_holdout_evaluation(
            self.config,
            complete,
            split,
            candidate,
            frozen_model_sha=candidate.frozen_model_sha256,
        )

        self.assertEqual(report.selection_sources, ["A_walk_forward_oof"])
        self.assertEqual(set(report.quadrant_metrics), {"B_time_holdout", "C_stock_holdout", "D_joint_holdout"})
        self.assertEqual(report.quadrant_metrics["B_time_holdout"]["date_count"], 1)
        self.assertEqual(report.quadrant_metrics["D_joint_holdout"]["date_count"], 1)
        self.assertTrue(report.predictions["quadrant"].isin({"B_time_holdout", "C_stock_holdout", "D_joint_holdout"}).all())


if __name__ == "__main__":
    import unittest

    unittest.main()
