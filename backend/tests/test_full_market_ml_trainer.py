from __future__ import annotations

from app.evaluation.full_market_ml.trainer import FIXED_RANKER_GRID, FIXED_SEEDS, run_development_training
from app.evaluation.full_market_ml.splits import FinalHoldoutAccessError
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


if __name__ == "__main__":
    import unittest

    unittest.main()
