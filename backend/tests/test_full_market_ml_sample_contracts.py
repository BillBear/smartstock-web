from __future__ import annotations

import unittest

from app.evaluation.full_market_ml.sample_contracts import build_label_contract


def _label_audit() -> dict:
    return {
        "passed": True,
        "audited_date_count": 2,
        "eligible_row_count": 200,
        "path_ambiguity_count": 7,
        "daily": [
            {
                "trade_date": "2025-01-02",
                "eligible_count": 100,
                "alpha_top10_prevalence": 0.10,
                "grade_3_or_higher_rate": 0.10,
            },
            {
                "trade_date": "2025-01-03",
                "eligible_count": 100,
                "alpha_top10_prevalence": 0.10,
                "grade_3_or_higher_rate": 0.10,
            },
        ],
    }


class SampleContractTests(unittest.TestCase):
    def test_build_label_contract_keeps_alpha_target_separate_from_path_risk(self) -> None:
        result = build_label_contract(_label_audit(), "a" * 64, "b" * 64)

        self.assertEqual(result["label_contract_version"], "alpha_risk_10d_v1")
        self.assertEqual(result["primary_label"]["column"], "alpha_relevance_grade_10d")
        self.assertEqual(result["primary_label"]["objective"], "cross_sectional_alpha")
        self.assertEqual(result["auxiliary_risk_labels"][0]["column"], "severe_negative_10d")
        self.assertEqual(result["primary_path_ambiguity_count"], 7)
        self.assertEqual(result["path_label_eligible_ambiguous_count"], 0)
        self.assertEqual(len(result["primary_daily"]), 2)
        self.assertEqual(len(result["sha256"]), 64)

    def test_build_label_contract_rejects_duplicate_primary_dates(self) -> None:
        audit = _label_audit()
        audit["daily"].append(dict(audit["daily"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate primary label date"):
            build_label_contract(audit, "a" * 64, "b" * 64)


if __name__ == "__main__":
    unittest.main()
