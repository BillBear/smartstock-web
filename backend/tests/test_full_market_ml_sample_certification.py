from __future__ import annotations

import copy
import unittest

from app.evaluation.full_market_ml.sample_certification import (
    CertificationConfig,
    certify_training_sample,
)


def valid_evidence() -> dict:
    return {
        "input_hashes": {
            "dataset_registry": "a" * 64,
            "full_build_manifest": "b" * 64,
            "label_report": "c" * 64,
            "split_plan": "d" * 64,
        },
        "panel": {
            "ready": True,
            "row_count": 12_000,
            "date_count": 60,
            "symbol_count": 200,
            "duplicate_key_count": 0,
            "required_date_coverage": 1.0,
        },
        "quality": {"disabled_feature_groups": []},
        "labels": {
            "signal_time": "after_close",
            "entry_time": "next_session_open",
            "eligible_ambiguous_path_count": 0,
            "canonical_daily": [
                {"trade_date": "2025-01-02", "eligible_count": 100, "grade_3_or_higher_count": 10},
                {"trade_date": "2025-01-03", "eligible_count": 100, "grade_3_or_higher_count": 10},
            ],
            "secondary_daily": [
                {"trade_date": "2025-01-02", "eligible_count": 100, "alpha_top10_prevalence": 0.10},
                {"trade_date": "2025-01-03", "eligible_count": 100, "alpha_top10_prevalence": 0.10},
            ],
        },
        "security_state": {
            "provenance": {
                "sha256": "e" * 64,
                "covers": ["listing", "delisting", "st", "suspension", "industry"],
            },
            "eligible_status_violation_count": 0,
            "listing_age_nonmonotonic_count": 0,
        },
        "features": {
            "coverage": {"adjusted_return_20d": 1.0, "amount_log": 1.0},
            "groups": {"adjusted_return_20d": "price_return", "amount_log": "volume_liquidity"},
        },
        "splits": {
            "development_dates": ["2025-01-02", "2025-01-03"],
            "final_dates": ["2025-04-01"],
            "A_symbols": ["000001", "000002"],
            "C_symbols": ["000003"],
            "final_holdout_reserved": True,
        },
    }


class SampleCertificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = CertificationConfig.from_mapping(
            {
                "dataset_id": "fixture-dataset",
                "minimum_coverage": 0.95,
                "minimum_feature_coverage": 0.95,
                "minimum_listing_sessions": 120,
                "production_integration_allowed": False,
            }
        )

    def test_rejects_configuration_that_allows_production_integration(self):
        with self.assertRaisesRegex(ValueError, "production integration"):
            CertificationConfig.from_mapping(
                {
                    "dataset_id": "fixture-dataset",
                    "minimum_coverage": 0.95,
                    "minimum_feature_coverage": 0.95,
                    "minimum_listing_sessions": 120,
                    "production_integration_allowed": True,
                }
            )

    def test_certifies_complete_leak_free_evidence(self):
        result = certify_training_sample(self.config, valid_evidence(), ["adjusted_return_20d", "amount_log"])

        self.assertEqual(result["status"], "certified_research_sample")
        self.assertEqual(result["blocking_codes"], [])
        self.assertFalse(result["production_integration_allowed"])

    def test_blocks_selected_feature_from_disabled_moneyflow_group(self):
        evidence = valid_evidence()
        evidence["quality"]["disabled_feature_groups"] = ["moneyflow"]
        evidence["features"]["coverage"]["moneyflow_20d_mean"] = 1.0
        evidence["features"]["groups"]["moneyflow_20d_mean"] = "moneyflow"

        result = certify_training_sample(self.config, evidence, ["moneyflow_20d_mean"])

        self.assertIn("feature_group_disabled:moneyflow", result["blocking_codes"])

    def test_blocks_cross_section_moneyflow_alias_when_moneyflow_is_disabled(self):
        evidence = valid_evidence()
        evidence["quality"]["disabled_feature_groups"] = ["moneyflow"]
        evidence["features"]["coverage"]["main_net_inflow_ratio_rank"] = 1.0
        evidence["features"]["groups"]["main_net_inflow_ratio_rank"] = "cross_section_moneyflow"

        result = certify_training_sample(self.config, evidence, ["main_net_inflow_ratio_rank"])

        self.assertIn("feature_group_disabled:moneyflow", result["blocking_codes"])

    def test_blocks_ambiguous_path_that_remains_training_eligible(self):
        evidence = valid_evidence()
        evidence["labels"]["eligible_ambiguous_path_count"] = 1

        result = certify_training_sample(self.config, evidence, ["adjusted_return_20d"])

        self.assertIn("labels:ambiguous_path_training_rows", result["blocking_codes"])

    def test_blocks_when_ambiguity_eligibility_is_not_proven(self):
        evidence = valid_evidence()
        evidence["labels"]["eligible_ambiguous_path_count"] = None

        result = certify_training_sample(self.config, evidence, ["adjusted_return_20d"])

        self.assertIn("labels:ambiguous_path_eligibility_unproven", result["blocking_codes"])

    def test_blocks_missing_point_in_time_security_provenance(self):
        evidence = valid_evidence()
        evidence["security_state"]["provenance"] = None

        result = certify_training_sample(self.config, evidence, ["adjusted_return_20d"])

        self.assertIn("security_state:point_in_time_provenance_missing", result["blocking_codes"])

    def test_blocks_daily_label_scope_disagreement(self):
        evidence = valid_evidence()
        evidence["labels"]["secondary_daily"][1]["alpha_top10_prevalence"] = 0.08

        result = certify_training_sample(self.config, evidence, ["adjusted_return_20d"])

        self.assertIn("labels:secondary_daily_reconciliation_failed:2025-01-03", result["blocking_codes"])

    def test_blocks_feature_below_registered_coverage(self):
        evidence = valid_evidence()
        evidence["features"]["coverage"]["amount_log"] = 0.94

        result = certify_training_sample(self.config, evidence, ["amount_log"])

        self.assertIn("features:coverage_below_0_95:amount_log", result["blocking_codes"])

    def test_blocks_overlapping_stock_holdout(self):
        evidence = valid_evidence()
        evidence["splits"]["C_symbols"] = ["000002"]

        result = certify_training_sample(self.config, evidence, ["adjusted_return_20d"])

        self.assertIn("splits:A_C_symbols_overlap", result["blocking_codes"])

    def test_blocks_future_field_in_selected_feature_schema(self):
        evidence = valid_evidence()
        evidence["features"]["coverage"]["future_return_10d"] = 1.0
        evidence["features"]["groups"]["future_return_10d"] = "price_return"

        result = certify_training_sample(self.config, evidence, ["future_return_10d"])

        self.assertIn("features:post_signal_schema", result["blocking_codes"])


if __name__ == "__main__":
    unittest.main()
