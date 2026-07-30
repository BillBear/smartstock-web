from __future__ import annotations

import unittest
from pathlib import Path
import json
import tempfile
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.evaluation.ml_historical_evaluation_readiness import (
    REQUIRED_DAILY_PORTFOLIO_COLUMNS,
    REQUIRED_TOP10_EVALUATION_COLUMNS,
    assess_historical_evaluation_readiness,
    audit_historical_evaluation_readiness,
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

    def test_blocked_audit_publishes_an_atomic_research_only_report(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            label_root = root / "labels"
            candidate_root = root / "candidate"
            output_dir = root / "output"
            label_root.mkdir()
            candidate_root.mkdir()
            _write_json(
                label_root / "development_split_plan.json",
                {
                    **_split_with_ten_session_embargo(),
                    "future_holdout": {
                        "status": "awaiting_model_freeze_and_future_labels",
                        "formal_evaluation_allowed": False,
                        "dates": [],
                    },
                },
            )
            _write_json(
                candidate_root / "candidate_screen.json",
                {"status": "development_research_failed_gate", "candidate_freeze_allowed": False},
            )
            pq.write_table(
                pa.Table.from_pandas(pd.DataFrame(columns=sorted(REQUIRED_TOP10_EVALUATION_COLUMNS))),
                candidate_root / "oof_predictions.parquet",
            )
            with patch(
                "app.evaluation.ml_historical_evaluation_readiness.verify_recovery_inputs",
                return_value={"input_manifest": {"dataset_id": "fixture"}},
            ):
                report = audit_historical_evaluation_readiness(
                    label_root=label_root,
                    feature_asset_root=root / "features",
                    panel_root=root / "panel",
                    candidate_run_root=candidate_root,
                    output_dir=output_dir,
                    code_commit="test",
                )

            self.assertEqual("blocked", report["status"])
            self.assertFalse(report["production_integration_allowed"])
            persisted = json.loads((output_dir / "historical_evaluation_readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(report, persisted)
            self.assertEqual("complete", json.loads((output_dir / "progress.json").read_text(encoding="utf-8"))["status"])

    def test_audit_failure_keeps_progress_without_publishing_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            label_root = root / "labels"
            label_root.mkdir()
            _write_json(
                label_root / "development_split_plan.json",
                {
                    **_split_with_ten_session_embargo(),
                    "future_holdout": {
                        "status": "awaiting_model_freeze_and_future_labels",
                        "formal_evaluation_allowed": False,
                        "dates": [],
                    },
                },
            )
            output_dir = root / "output"
            with patch(
                "app.evaluation.ml_historical_evaluation_readiness.verify_recovery_inputs",
                return_value={"input_manifest": {"dataset_id": "fixture"}},
            ):
                with self.assertRaisesRegex(FileNotFoundError, "candidate_screen.json"):
                    audit_historical_evaluation_readiness(
                        label_root=label_root,
                        feature_asset_root=root / "features",
                        panel_root=root / "panel",
                        candidate_run_root=root / "candidate",
                        output_dir=output_dir,
                        code_commit="test",
                    )

            self.assertFalse(output_dir.exists())
            progress = json.loads((root / ".output.running" / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual("failed", progress["status"])

    def test_audit_rejects_a_candidate_path_inside_the_prospective_lockbox(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(ValueError, "prospective lockbox"):
                audit_historical_evaluation_readiness(
                    label_root=root / "labels",
                    feature_asset_root=root / "features",
                    panel_root=root / "panel",
                    candidate_run_root=root / "prospective-lockbox" / "candidate",
                    output_dir=root / "output",
                    code_commit="test",
                )

            self.assertFalse((root / "output").exists())


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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
