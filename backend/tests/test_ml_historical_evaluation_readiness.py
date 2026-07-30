from __future__ import annotations

import unittest

from app.evaluation.ml_historical_evaluation_readiness import (
    REQUIRED_DAILY_PORTFOLIO_COLUMNS,
    REQUIRED_TOP10_EVALUATION_COLUMNS,
    assess_historical_evaluation_readiness,
)


class HistoricalEvaluationReadinessTests(unittest.TestCase):
    def test_current_asset_shape_is_blocked_without_candidate_final_holdout_or_daily_marks(self):
        report = assess_historical_evaluation_readiness(
            development_split=_split_with_ten_session_embargo(),
            future_holdout={
                "status": "awaiting_model_freeze_and_future_labels",
                "formal_evaluation_allowed": False,
                "dates": [],
            },
            candidate_screen={
                "status": "development_research_failed_gate",
                "candidate_freeze_allowed": False,
            },
            oof_columns=set(REQUIRED_TOP10_EVALUATION_COLUMNS),
        )

        self.assertEqual("blocked", report["status"])
        self.assertEqual(
            {
                "candidate_not_development_qualified",
                "final_historical_holdout_not_materialized",
                "daily_portfolio_path_not_materialized",
            },
            set(report["blocking_codes"]),
        )
        self.assertFalse(report["production_integration_allowed"])

    def test_ready_requires_all_frozen_inputs_without_relaxing_production_gate(self):
        report = assess_historical_evaluation_readiness(
            development_split=_split_with_ten_session_embargo(),
            future_holdout={
                "status": "ready_for_historical_evaluation",
                "formal_evaluation_allowed": True,
                "dates": ["2025-10-01", "2025-10-02"],
            },
            candidate_screen={
                "status": "development_candidate_for_future_holdout",
                "candidate_freeze_allowed": True,
            },
            oof_columns={
                *REQUIRED_TOP10_EVALUATION_COLUMNS,
                *REQUIRED_DAILY_PORTFOLIO_COLUMNS,
                "signal_market_regime",
            },
        )

        self.assertEqual("ready", report["status"])
        self.assertEqual([], report["blocking_codes"])
        self.assertTrue(report["market_regime_reporting_available"])
        self.assertFalse(report["production_integration_allowed"])

    def test_rejects_final_holdout_dates_that_overlap_development(self):
        report = assess_historical_evaluation_readiness(
            development_split=_split_with_ten_session_embargo(),
            future_holdout={
                "status": "ready_for_historical_evaluation",
                "formal_evaluation_allowed": True,
                "dates": ["2025-01-01"],
            },
            candidate_screen={
                "status": "development_candidate_for_future_holdout",
                "candidate_freeze_allowed": True,
            },
            oof_columns={
                *REQUIRED_TOP10_EVALUATION_COLUMNS,
                *REQUIRED_DAILY_PORTFOLIO_COLUMNS,
            },
        )

        self.assertIn("final_historical_holdout_overlaps_development", report["blocking_codes"])

    def test_rejects_final_holdout_that_is_not_later_than_development(self):
        report = assess_historical_evaluation_readiness(
            development_split=_split_with_ten_session_embargo(),
            future_holdout={
                "status": "ready_for_historical_evaluation",
                "formal_evaluation_allowed": True,
                "dates": ["2024-12-31"],
            },
            candidate_screen={
                "status": "development_candidate_for_future_holdout",
                "candidate_freeze_allowed": True,
            },
            oof_columns={
                *REQUIRED_TOP10_EVALUATION_COLUMNS,
                *REQUIRED_DAILY_PORTFOLIO_COLUMNS,
            },
        )

        self.assertIn("final_historical_holdout_not_after_development", report["blocking_codes"])

    def test_rejects_a_walk_forward_fold_without_ten_session_embargo(self):
        split = _split_with_ten_session_embargo()
        split["walk_forward"][0]["validation_dates"] = ["2025-01-12"]
        report = assess_historical_evaluation_readiness(
            development_split=split,
            future_holdout={
                "status": "ready_for_historical_evaluation",
                "formal_evaluation_allowed": True,
                "dates": ["2025-10-01"],
            },
            candidate_screen={
                "status": "development_candidate_for_future_holdout",
                "candidate_freeze_allowed": True,
            },
            oof_columns={
                *REQUIRED_TOP10_EVALUATION_COLUMNS,
                *REQUIRED_DAILY_PORTFOLIO_COLUMNS,
            },
        )

        self.assertIn("walk_forward_embargo_insufficient", report["blocking_codes"])


def _split_with_ten_session_embargo() -> dict[str, object]:
    dates = [f"2025-01-{day:02d}" for day in range(1, 32)] + [f"2025-02-{day:02d}" for day in range(1, 29)]
    folds = []
    for fold, train_end_index in enumerate((10, 16, 22, 28, 34), start=1):
        validation_start_index = train_end_index + 11
        folds.append(
            {
                "fold": fold,
                "training_dates": dates[: train_end_index + 1],
                "validation_dates": dates[validation_start_index : validation_start_index + 2],
            }
        )
    return {"development_dates": dates, "walk_forward": folds}


if __name__ == "__main__":
    unittest.main()
