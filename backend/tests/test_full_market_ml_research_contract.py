from __future__ import annotations

from dataclasses import replace
import unittest

from app.evaluation.full_market_ml.research_contract import (
    REQUIRED_BASELINES,
    RankingResearchContract,
    validate_inner_date_roles,
)


class FullMarketMLResearchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = RankingResearchContract(
            dataset_id="fixture-dataset",
            run_id="fixture-run",
            feature_blocks=(
                ("momentum", ("adjusted_return_20d", "adjusted_return_60d")),
                ("liquidity", ("amount_log", "turnover_rate")),
            ),
        )

    def test_contract_hash_is_canonical_and_sensitive_to_research_inputs(self):
        same = replace(self.contract)
        changed = replace(self.contract, commission_per_side=0.0004)

        self.assertEqual(self.contract.sha256(), same.sha256())
        self.assertNotEqual(self.contract.sha256(), changed.sha256())
        self.assertEqual(self.contract.canonical_payload()["future_holdout_status"], "sealed")

    def test_optional_dataset_registry_hash_must_be_sha256_and_changes_contract(self):
        bound = replace(self.contract, dataset_registry_sha256="a" * 64)

        self.assertNotEqual(self.contract.sha256(), bound.sha256())
        with self.assertRaisesRegex(ValueError, "dataset_registry_sha256"):
            replace(self.contract, dataset_registry_sha256="not-a-sha").validate()

    def test_contract_rejects_listing_history_below_120_sessions(self):
        with self.assertRaisesRegex(ValueError, "minimum_listing_sessions"):
            replace(self.contract, minimum_listing_sessions=119).validate()

    def test_contract_rejects_missing_required_baseline(self):
        with self.assertRaisesRegex(ValueError, "required_baselines"):
            replace(self.contract, required_baselines=REQUIRED_BASELINES[:-1]).validate()

    def test_baseline_score_definitions_are_hashed_and_complete(self):
        changed = replace(
            self.contract,
            baseline_definitions=tuple(
                (name, "amount_log" if name == "registered_single_feature" else source)
                for name, source in self.contract.baseline_definitions
            ),
        )

        self.assertNotEqual(self.contract.sha256(), changed.sha256())
        with self.assertRaisesRegex(ValueError, "baseline_definitions"):
            replace(self.contract, baseline_definitions=self.contract.baseline_definitions[:-1]).validate()

    def test_contract_rejects_open_or_reused_future_holdout(self):
        with self.assertRaisesRegex(ValueError, "future_holdout_status"):
            replace(self.contract, future_holdout_status="available").validate()

    def test_contract_rejects_unsafe_local_resource_or_archive_policy(self):
        with self.assertRaisesRegex(ValueError, "rss_abort_gb"):
            replace(self.contract, rss_abort_gb=16.0).validate()
        with self.assertRaisesRegex(ValueError, "archive_format"):
            replace(self.contract, archive_format="none").validate()

    def test_inner_date_roles_are_disjoint_ordered_and_large_enough(self):
        fit = tuple(f"2024-01-{day:02d}" for day in range(1, 61))
        early = tuple(f"2024-02-{day:02d}" for day in range(1, 21))
        selection = tuple(f"2024-03-{day:02d}" for day in range(1, 21))
        outer = tuple(f"2024-04-{day:02d}" for day in range(1, 21))

        validate_inner_date_roles(self.contract, fit, early, selection, outer)

        with self.assertRaisesRegex(ValueError, "minimum_inner_fit_dates"):
            validate_inner_date_roles(self.contract, fit[:-1], early, selection, outer)
        with self.assertRaisesRegex(ValueError, "disjoint"):
            validate_inner_date_roles(self.contract, fit, early, selection + outer[:1], outer)
        with self.assertRaisesRegex(ValueError, "chronological"):
            validate_inner_date_roles(self.contract, fit, outer, selection, early)


if __name__ == "__main__":
    unittest.main()
