from __future__ import annotations

import copy
import unittest

from app.evaluation.full_market_ml.research_preflight import evaluate_research_preflight


CONTRACT_SHA = "a" * 64


def valid_evidence() -> dict:
    return {
        "contract_hashes": [CONTRACT_SHA] * 6,
        "data": {
            "ready": True,
            "minimum_coverage_ratio": 0.97,
            "minimum_daily_symbols": 4700,
            "duplicate_key_count": 0,
            "invalid_adjusted_price_count": 0,
            "date_count": 324,
        },
        "labels": {
            "passed": True,
            "audited_date_count": 324,
            "alpha_top10_prevalence_min": 0.099,
            "alpha_top10_prevalence_max": 0.101,
            "alpha_top10_prevalence_std": 0.001,
            "alpha_top10_market_return_correlation": 0.05,
        },
        "features": {
            "passed": True,
            "point_in_time_verified": True,
            "maximum_core_missing_ratio": 0.01,
        },
        "splits": {
            "outer_fold_count": 5,
            "roles_disjoint": True,
            "roles_chronological": True,
            "minimum_fit_dates": 60,
            "minimum_early_stop_dates": 20,
            "minimum_selection_dates": 20,
        },
        "baselines": {
            "definitions_exact": True,
            "identical_rows": True,
            "row_count": 10000,
        },
        "ablation": {
            "decisions": [
                {
                    "name": "momentum",
                    "status": "accepted_alpha",
                    "aggregate_oof_uplift": {
                        "precision_at_5_uplift": 0.02,
                        "ndcg_at_10_uplift": 0.01,
                        "top5_return_uplift": 0.01,
                    },
                    "precision_bootstrap_ci": [0.001, 0.04],
                    "inner_selected_folds": [True, True, True, True, False],
                }
            ]
        },
        "evaluation": {
            "identical_rows": True,
            "identical_risk_mask": True,
        },
    }


class FullMarketMLResearchPreflightTests(unittest.TestCase):
    def _failed(self, evidence: dict) -> set[str]:
        report = evaluate_research_preflight(evidence, expected_contract_sha=CONTRACT_SHA, phase="model")
        return set(report["failed_gates"])

    def test_valid_model_evidence_passes(self):
        report = evaluate_research_preflight(valid_evidence(), expected_contract_sha=CONTRACT_SHA, phase="model")

        self.assertTrue(report["passed"])
        self.assertEqual(report["failed_gates"], [])
        self.assertEqual(set(report["decisions"]), {"data", "labels", "features", "splits", "baselines", "evaluation"})

    def test_low_market_coverage_is_blocking(self):
        evidence = valid_evidence()
        evidence["data"]["minimum_coverage_ratio"] = 0.80

        self.assertIn("data:historical_coverage_below_0_95", self._failed(evidence))

    def test_label_regime_correlation_is_blocking(self):
        evidence = valid_evidence()
        evidence["labels"]["alpha_top10_market_return_correlation"] = 0.35

        self.assertIn("labels:prevalence_correlates_with_market", self._failed(evidence))

    def test_invalid_daily_prevalence_is_blocking(self):
        evidence = valid_evidence()
        evidence["labels"]["alpha_top10_prevalence_max"] = 0.20

        self.assertIn("labels:prevalence_outside_registered_band", self._failed(evidence))

    def test_negative_oof_feature_block_cannot_be_accepted(self):
        evidence = valid_evidence()
        decision = evidence["ablation"]["decisions"][0]
        decision["aggregate_oof_uplift"]["top5_return_uplift"] = -0.01

        self.assertIn("features:accepted_block_has_nonpositive_oof_uplift:momentum", self._failed(evidence))

    def test_insufficient_inner_dates_are_blocking(self):
        evidence = valid_evidence()
        evidence["splits"]["minimum_selection_dates"] = 12

        self.assertIn("splits:inner_selection_dates_below_20", self._failed(evidence))

    def test_shared_early_stop_and_selection_rows_are_blocking(self):
        evidence = valid_evidence()
        evidence["splits"]["roles_disjoint"] = False

        self.assertIn("splits:date_roles_not_disjoint", self._failed(evidence))

    def test_unequal_baseline_rows_are_blocking(self):
        evidence = valid_evidence()
        evidence["baselines"]["identical_rows"] = False

        self.assertIn("baselines:comparison_rows_differ", self._failed(evidence))

    def test_stale_contract_hash_is_blocking(self):
        evidence = valid_evidence()
        evidence["contract_hashes"][3] = "b" * 64

        self.assertIn("data:stale_or_mixed_contract_hash", self._failed(evidence))

    def test_no_accepted_alpha_block_stops_model_phase(self):
        evidence = valid_evidence()
        evidence["ablation"]["decisions"] = []

        self.assertIn("features:no_accepted_alpha_feature_block", self._failed(evidence))

    def test_contract_phase_does_not_claim_model_readiness(self):
        evidence = copy.deepcopy(valid_evidence())
        report = evaluate_research_preflight(
            evidence, expected_contract_sha=CONTRACT_SHA, phase="contract"
        )

        self.assertTrue(report["passed"])
        self.assertFalse(report["model_ready"])
        self.assertEqual(report["decisions"]["features"]["decision"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
