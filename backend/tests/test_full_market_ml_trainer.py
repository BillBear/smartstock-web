from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from app.evaluation.full_market_ml.trainer import (
    FIXED_RANKER_GRID,
    FIXED_SEEDS,
    fit_final_candidate,
    load_final_fit,
    _classifier_oof,
    _ranker_oof,
    _stable_random_score,
    run_development_training,
    run_final_holdout_evaluation,
    save_final_fit,
    _portfolio_or_empty,
    _run_group_ablations,
)
from app.evaluation.full_market_ml.splits import FinalHoldoutAccessError, SplitPlan
from tests.full_market_ml_fixtures import overlapping_portfolio_fixture, predictive_fixture, random_label_fixture, sealed_split_fixture
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLTrainerTests(FullMarketMLTestCase):
    @staticmethod
    def _split():
        return sealed_split_fixture(symbols_per_date=220)

    def test_portfolio_ablation_accepts_canonical_execution_fields(self):
        dataset = overlapping_portfolio_fixture().rename(
            columns={"adjusted_next_open": "entry_price", "adjusted_exit_close": "exit_price"}
        )

        portfolio = _portfolio_or_empty(dataset)

        self.assertEqual(portfolio["closed_trade_count"], 10)

    def test_group_ablation_is_leave_one_out_and_retunes_each_subset(self):
        dataset = predictive_fixture(symbols_per_date=220)
        calls = []

        def fake_ranker(data, _split, features, _params, _seeds, *, dataset_cache=None):
            calls.append(tuple(features))
            return data.assign(score=data[features[0]])

        with patch("app.evaluation.full_market_ml.trainer._ranker_oof", side_effect=fake_ranker), patch(
            "app.evaluation.full_market_ml.trainer._select_ranker_params",
            return_value=(dict(FIXED_RANKER_GRID[0]), [{"params": dict(FIXED_RANKER_GRID[0])}]),
        ) as retune:
            report = _run_group_ablations(
                dataset,
                self._split(),
                ("adjusted_return_20d", "amount_log"),
                dict(FIXED_RANKER_GRID[0]),
                (FIXED_SEEDS[0],),
            )

        evaluated = [row for row in report if row.get("comparison") == "all_features_vs_leave_one_group_out"]
        self.assertTrue(evaluated)
        self.assertTrue(all(len(row["without_group_features"]) < 2 for row in evaluated))
        self.assertEqual(retune.call_count, len(evaluated))

    def test_model_selection_uses_only_oof_development_predictions(self):
        candidate = run_development_training(self.config, predictive_fixture(), self._split())

        self.assertEqual(candidate.selection_sources, ["A_walk_forward_oof"])
        self.assertNotIn("B_final_train_symbols", candidate.selection_sources)
        self.assertNotIn("D_final_unseen_symbols", candidate.selection_sources)
        self.assertEqual(set(candidate.oof_predictions["trade_date"]), set(self._split().development_dates[2:5]))

    def test_classifier_oof_does_not_retrain_ranker_to_align_prediction_keys(self):
        dataset = predictive_fixture()

        with patch("app.evaluation.full_market_ml.trainer._ranker_oof", side_effect=AssertionError("ranker retrained")):
            probabilities, _report = _classifier_oof(
                dataset,
                self._split(),
                ("adjusted_return_20d",),
                "label_strong_path_10d",
                FIXED_RANKER_GRID[0],
                (FIXED_SEEDS[0],),
            )

        expected_rows = sum(
            len(dataset.loc[dataset.trade_date.isin(fold.validation_dates)])
            for fold in self._split().walk_forward
        )
        self.assertEqual(len(probabilities), expected_rows)

    def test_random_baseline_score_is_deterministic_and_index_aligned(self):
        dataset = predictive_fixture().iloc[::7].copy()

        left = _stable_random_score(dataset)
        right = _stable_random_score(dataset)

        self.assertEqual(left.index.tolist(), dataset.index.tolist())
        self.assertTrue(left.equals(right))

    def test_ranker_oof_cache_reuses_one_dataset_per_fold_and_feature_set(self):
        dataset = predictive_fixture()
        cache = {}

        first = _ranker_oof(dataset, self._split(), ("adjusted_return_20d",), FIXED_RANKER_GRID[0], (FIXED_SEEDS[0],), dataset_cache=cache)
        second = _ranker_oof(dataset, self._split(), ("adjusted_return_20d",), FIXED_RANKER_GRID[0], (FIXED_SEEDS[0],), dataset_cache=cache)

        self.assertEqual(len(cache), len(self._split().walk_forward))
        self.assertEqual(first[["trade_date", "symbol"]].to_dict("records"), second[["trade_date", "symbol"]].to_dict("records"))
        self.assertEqual(first["score"].tolist(), second["score"].tolist())

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
        self.assertEqual([row["seed"] for row in candidate.seed_sensitivity], list(FIXED_SEEDS))
        self.assertTrue(all("ndcg_at_10" in row for row in candidate.seed_sensitivity))
        self.assertTrue(candidate.error_samples["label_severe_negative_10d"].astype(bool).all())

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

    def test_failed_development_candidate_cannot_open_final_holdout(self):
        candidate = run_development_training(self.config, random_label_fixture(seed=42), self._split())

        self.assertFalse(candidate.can_open_final_holdout)

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

        final_fit = fit_final_candidate(development, split, candidate, frozen_model_sha=candidate.frozen_model_sha256)
        final_fit_dir = self.temp_path / "existing-final-fit"
        save_final_fit(final_fit, final_fit_dir)
        final_fit = load_final_fit(final_fit_dir, candidate.frozen_model_sha256)
        report = run_final_holdout_evaluation(
            self.config,
            complete,
            split,
            candidate,
            frozen_model_sha=candidate.frozen_model_sha256,
            final_fit=final_fit,
        )

        self.assertEqual(report.selection_sources, ["A_walk_forward_oof"])
        self.assertEqual(set(report.quadrant_metrics), {"B_time_holdout", "C_stock_holdout", "D_joint_holdout"})
        self.assertEqual(report.quadrant_metrics["B_time_holdout"]["date_count"], 1)
        self.assertEqual(report.quadrant_metrics["D_joint_holdout"]["date_count"], 1)
        self.assertTrue(report.predictions["quadrant"].isin({"B_time_holdout", "C_stock_holdout", "D_joint_holdout"}).all())

    def test_final_holdout_evaluation_requires_a_persisted_final_fit(self):
        development = predictive_fixture(symbols_per_date=300)
        base_split = self._split()
        train_symbols = tuple(f"{index + 1:06d}" for index in range(240))
        unseen_symbols = tuple(f"{index + 1:06d}" for index in range(240, 300))
        split = SplitPlan(
            development_dates=base_split.development_dates,
            final_dates=("2025-02-03",),
            stock_holdout_symbols=unseen_symbols,
            A_dev_train_symbols=train_symbols,
            B_final_train_symbols=train_symbols,
            C_dev_unseen_symbols=unseen_symbols,
            D_final_unseen_symbols=unseen_symbols,
            walk_forward=tuple(replace(fold, training_symbols=train_symbols) for fold in base_split.walk_forward),
            stratum_counts_before={}, stratum_counts_after={}, split_sha256="missing-final-fit-fixture",
        )
        candidate = run_development_training(self.config, development, split)
        final_rows = development.loc[development["trade_date"].eq(development["trade_date"].iloc[-1])].copy()
        final_rows["trade_date"] = "2025-02-03"
        complete = __import__("pandas").concat([development, final_rows], ignore_index=True)

        with self.assertRaisesRegex(FinalHoldoutAccessError, "requires a persisted final fit"):
            run_final_holdout_evaluation(
                self.config,
                complete,
                split,
                candidate,
                frozen_model_sha=candidate.frozen_model_sha256,
            )

    def test_final_fit_is_reusable_by_holdout_evaluation(self):
        development = predictive_fixture(symbols_per_date=300)
        base_split = self._split()
        train_symbols = tuple(f"{index + 1:06d}" for index in range(240))
        unseen_symbols = tuple(f"{index + 1:06d}" for index in range(240, 300))
        split = SplitPlan(
            development_dates=base_split.development_dates,
            final_dates=("2025-02-03",),
            stock_holdout_symbols=unseen_symbols,
            A_dev_train_symbols=train_symbols,
            B_final_train_symbols=train_symbols,
            C_dev_unseen_symbols=unseen_symbols,
            D_final_unseen_symbols=unseen_symbols,
            walk_forward=tuple(replace(fold, training_symbols=train_symbols) for fold in base_split.walk_forward),
            stratum_counts_before={}, stratum_counts_after={}, split_sha256="final-fit-fixture",
        )
        candidate = run_development_training(self.config, development, split)
        final_rows = development.loc[development["trade_date"].eq(development["trade_date"].iloc[-1])].copy()
        final_rows["trade_date"] = "2025-02-03"
        complete = __import__("pandas").concat([development, final_rows], ignore_index=True)

        fitted = fit_final_candidate(development, split, candidate, frozen_model_sha=candidate.frozen_model_sha256)
        with self.assertRaisesRegex(FinalHoldoutAccessError, "persisted final fit"):
            run_final_holdout_evaluation(
                self.config,
                complete,
                split,
                candidate,
                frozen_model_sha=candidate.frozen_model_sha256,
                final_fit=fitted,
            )
        with self.assertRaisesRegex(FinalHoldoutAccessError, "loaded final fit"):
            run_final_holdout_evaluation(
                self.config,
                complete,
                split,
                candidate,
                frozen_model_sha=candidate.frozen_model_sha256,
                final_fit=replace(fitted, artifact_manifest_sha256="forged"),
            )
        final_fit_dir = self.temp_path / "final-fit"
        save_final_fit(fitted, final_fit_dir)
        persisted_fit = load_final_fit(final_fit_dir, candidate.frozen_model_sha256)
        report = run_final_holdout_evaluation(
            self.config,
            complete,
            split,
            candidate,
            frozen_model_sha=candidate.frozen_model_sha256,
            final_fit=persisted_fit,
        )

        self.assertEqual(fitted.frozen_model_sha256, candidate.frozen_model_sha256)
        self.assertEqual(report.quadrant_metrics["D_joint_holdout"]["date_count"], 1)

    def test_final_holdout_persists_each_quadrant_through_the_completion_callback(self):
        development = predictive_fixture(symbols_per_date=300)
        base_split = self._split()
        train_symbols = tuple(f"{index + 1:06d}" for index in range(240))
        unseen_symbols = tuple(f"{index + 1:06d}" for index in range(240, 300))
        split = SplitPlan(
            development_dates=base_split.development_dates,
            final_dates=("2025-02-03",),
            stock_holdout_symbols=unseen_symbols,
            A_dev_train_symbols=train_symbols,
            B_final_train_symbols=train_symbols,
            C_dev_unseen_symbols=unseen_symbols,
            D_final_unseen_symbols=unseen_symbols,
            walk_forward=tuple(replace(fold, training_symbols=train_symbols) for fold in base_split.walk_forward),
            stratum_counts_before={}, stratum_counts_after={}, split_sha256="quadrant-callback-fixture",
        )
        candidate = run_development_training(self.config, development, split)
        final_rows = development.loc[development["trade_date"].eq(development["trade_date"].iloc[-1])].copy()
        final_rows["trade_date"] = "2025-02-03"
        complete = __import__("pandas").concat([development, final_rows], ignore_index=True)
        final_fit = fit_final_candidate(development, split, candidate, frozen_model_sha=candidate.frozen_model_sha256)
        final_fit_dir = self.temp_path / "callback-final-fit"
        save_final_fit(final_fit, final_fit_dir)
        final_fit = load_final_fit(final_fit_dir, candidate.frozen_model_sha256)
        persisted = {}

        run_final_holdout_evaluation(
            self.config,
            complete,
            split,
            candidate,
            frozen_model_sha=candidate.frozen_model_sha256,
            final_fit=final_fit,
            on_quadrant_complete=lambda quadrant, rows: persisted.setdefault(quadrant, rows.copy()),
        )

        self.assertEqual(set(persisted), {"B_time_holdout", "C_stock_holdout", "D_joint_holdout"})
        self.assertTrue(all(rows["quadrant"].eq(quadrant).all() for quadrant, rows in persisted.items()))

    def test_final_fit_model_artifacts_round_trip(self):
        dataset = predictive_fixture(symbols_per_date=300)
        split = sealed_split_fixture(symbols_per_date=300)
        candidate = run_development_training(self.config, dataset, split)
        fitted = fit_final_candidate(dataset, split, candidate, frozen_model_sha=candidate.frozen_model_sha256)
        target = self.temp_path / "final-fit"

        save_final_fit(fitted, target)
        restored = load_final_fit(target, candidate.frozen_model_sha256)

        self.assertEqual(restored.frozen_model_sha256, fitted.frozen_model_sha256)
        self.assertEqual(len(restored.rank_models), len(fitted.rank_models))
        self.assertEqual(restored.split_sha256, candidate.split_sha256)
        self.assertEqual(restored.selected_features, candidate.selected_features)
        self.assertEqual(restored.selected_risk_alpha, candidate.selected_risk_alpha)
        self.assertEqual(restored.calibrators, candidate.calibrators)

    def test_final_fit_rejects_a_tampered_model_binary(self):
        dataset = predictive_fixture(symbols_per_date=300)
        split = sealed_split_fixture(symbols_per_date=300)
        candidate = run_development_training(self.config, dataset, split)
        fitted = fit_final_candidate(dataset, split, candidate, frozen_model_sha=candidate.frozen_model_sha256)
        target = self.temp_path / "tampered-final-fit"
        save_final_fit(fitted, target)
        model_path = target / "rank_00.txt"
        model_path.write_text(model_path.read_text(encoding="utf-8") + "\ncorruption\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            load_final_fit(target, candidate.frozen_model_sha256)

    def test_final_fit_rejects_final_holdout_rows(self):
        development = predictive_fixture()
        candidate = run_development_training(self.config, development, self._split())
        final_rows = development.loc[development["trade_date"].eq(development["trade_date"].iloc[-1])].copy()
        final_rows["trade_date"] = "2025-02-03"
        contaminated = __import__("pandas").concat([development, final_rows], ignore_index=True)

        with self.assertRaises(FinalHoldoutAccessError):
            fit_final_candidate(
                contaminated,
                self._split(),
                candidate,
                frozen_model_sha=candidate.frozen_model_sha256,
            )

    def test_failed_development_candidate_cannot_be_final_fitted_or_evaluated_by_library_callers(self):
        dataset = random_label_fixture(seed=42)
        candidate = run_development_training(self.config, dataset, self._split())

        with self.assertRaisesRegex(FinalHoldoutAccessError, "development gate"):
            fit_final_candidate(
                dataset,
                self._split(),
                candidate,
                frozen_model_sha=candidate.frozen_model_sha256,
            )
        with self.assertRaisesRegex(FinalHoldoutAccessError, "development gate"):
            run_final_holdout_evaluation(
                self.config,
                dataset,
                self._split(),
                candidate,
                frozen_model_sha=candidate.frozen_model_sha256,
            )

    def test_final_holdout_rejects_a_final_fit_with_a_changed_prediction_contract(self):
        development = predictive_fixture(symbols_per_date=300)
        base_split = self._split()
        train_symbols = tuple(f"{index + 1:06d}" for index in range(240))
        unseen_symbols = tuple(f"{index + 1:06d}" for index in range(240, 300))
        split = SplitPlan(
            development_dates=base_split.development_dates,
            final_dates=("2025-02-03",),
            stock_holdout_symbols=unseen_symbols,
            A_dev_train_symbols=train_symbols,
            B_final_train_symbols=train_symbols,
            C_dev_unseen_symbols=unseen_symbols,
            D_final_unseen_symbols=unseen_symbols,
            walk_forward=tuple(replace(fold, training_symbols=train_symbols) for fold in base_split.walk_forward),
            stratum_counts_before={}, stratum_counts_after={}, split_sha256="changed-contract-fixture",
        )
        candidate = run_development_training(self.config, development, split)
        final_rows = development.loc[development["trade_date"].eq(development["trade_date"].iloc[-1])].copy()
        final_rows["trade_date"] = "2025-02-03"
        complete = __import__("pandas").concat([development, final_rows], ignore_index=True)
        fitted = fit_final_candidate(development, split, candidate, frozen_model_sha=candidate.frozen_model_sha256)
        final_fit_dir = self.temp_path / "contract-final-fit"
        save_final_fit(fitted, final_fit_dir)
        fitted = load_final_fit(final_fit_dir, candidate.frozen_model_sha256)

        with self.assertRaisesRegex(FinalHoldoutAccessError, "prediction contract"):
            run_final_holdout_evaluation(
                self.config,
                complete,
                split,
                replace(candidate, selected_risk_alpha=candidate.selected_risk_alpha + 0.1),
                frozen_model_sha=candidate.frozen_model_sha256,
                final_fit=fitted,
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
