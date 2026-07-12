from __future__ import annotations

import json
import tempfile
import warnings
from pathlib import Path

import pandas as pd

from app.evaluation.full_market_ml.feature_audit import _audit_allowed_features, _fold_correlations, audit_features
from app.evaluation.full_market_ml.splits import FinalHoldoutAccessError
from tests.full_market_ml_fixtures import (
    dataset_with_final_rows_exposed,
    monotonic_fixture,
    sealed_split_fixture,
    three_fold_split_fixture,
)
from tests.test_full_market_ml_collector import FullMarketMLTestCase


class FullMarketMLFeatureAuditTests(FullMarketMLTestCase):
    def test_feature_audit_artifact_round_trips_for_training(self):
        from scripts.run_full_market_ml_pipeline import load_feature_audit_artifact

        audit = audit_features(monotonic_fixture(), three_fold_split_fixture())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(audit.to_csv_rows()), encoding="utf-8")

            restored = load_feature_audit_artifact(path)

        self.assertEqual(set(restored.ic.columns), set(audit.ic.columns))
        self.assertEqual(len(restored.group_eligibility), len(audit.group_eligibility))

    def test_feature_audit_can_be_restricted_to_model_schema(self):
        result = audit_features(monotonic_fixture(), three_fold_split_fixture(), feature_schema=["signal"])

        self.assertEqual(set(result.ic["feature"]), {"signal"})

    def test_optional_market_features_keep_their_audit_group(self):
        dataset = monotonic_fixture()
        dataset["market_index_return_5d"] = dataset["signal"]

        result = audit_features(
            dataset,
            three_fold_split_fixture(),
            feature_schema=["market_index_return_5d"],
        )

        self.assertEqual(set(result.ic["feature_group"]), {"market_context"})

    def test_feature_correlations_skip_constant_columns_without_warnings(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rows = _fold_correlations(1, pd.DataFrame({"signal": [1.0, 2.0], "constant": [1.0, 1.0]}), ["signal", "constant"])

        self.assertEqual(rows, [])
        self.assertFalse(any("ConstantInputWarning" in str(warning.category) for warning in caught))

    def test_feature_audit_excludes_post_signal_execution_columns(self):
        dataset = monotonic_fixture()
        dataset["next_adjusted_open"] = dataset["future_return_10d"] + 1.0
        dataset["eligible_for_training_20d"] = True
        dataset["horizon_available_20d"] = True

        result = audit_features(dataset, three_fold_split_fixture())

        audited = set(result.ic["feature"])
        self.assertNotIn("next_adjusted_open", audited)
        self.assertNotIn("eligible_for_training_20d", audited)
        self.assertNotIn("horizon_available_20d", audited)

    def test_monotonic_feature_has_positive_ic_and_bucket_spread(self):
        result = audit_features(monotonic_fixture(), three_fold_split_fixture())

        row = result.ic.query("feature == 'signal'").iloc[0]
        self.assertGreater(row["median_ic"], 0.5)
        self.assertEqual(row["sign_consistency"], 1.0)
        spread = result.bucket_returns.query("feature == 'signal'")["top_bottom_spread"].median()
        self.assertGreater(spread, 0)

    def test_stable_negative_feature_is_kept_with_explicit_direction(self):
        dataset = monotonic_fixture()
        dataset["inverse_signal"] = -dataset["signal"]

        result = audit_features(dataset, three_fold_split_fixture(), feature_schema=["inverse_signal"])
        row = result.ic.query("feature == 'inverse_signal'").iloc[0]

        self.assertEqual(row["direction"], "negative")
        self.assertEqual(row["selection"], "core_candidate")
        self.assertEqual(row["direction_consistency"], 1.0)

    def test_audit_separates_net_return_and_risk_targets(self):
        dataset = monotonic_fixture()
        dataset["net_return_after_cost"] = dataset["future_return_10d"] - 0.002
        dataset["label_severe_negative_10d"] = dataset["signal"] < 5

        result = audit_features(dataset, three_fold_split_fixture())

        self.assertEqual(set(result.ic["target"]), {"net_return_after_cost", "label_severe_negative_10d"})
        self.assertEqual(set(result.bucket_returns["target"]), {"net_return_after_cost", "label_severe_negative_10d"})

    def test_feature_audit_never_reads_final_holdout(self):
        with self.assertRaises(FinalHoldoutAccessError):
            audit_features(dataset_with_final_rows_exposed(), sealed_split_fixture())

    def test_rejected_feature_is_not_allowed_into_candidate_schema(self):
        audit = audit_features(monotonic_fixture(), three_fold_split_fixture(), feature_schema=["signal"])
        rejected = audit.ic.copy()
        rejected.loc[:, "selection"] = "exclude"
        audit = audit.__class__(audit.coverage, rejected, audit.bucket_returns, audit.correlation, audit.drift, audit.group_eligibility)

        self.assertEqual(_audit_allowed_features(("signal", "missing"), audit), ())

    def test_reports_high_correlation_psi_and_moneyflow_task_twelve_gate(self):
        result = audit_features(monotonic_fixture(), three_fold_split_fixture())

        self.assertTrue(
            result.correlation.query("feature_left == 'correlated_signal' and feature_right == 'signal'")["abs_correlation"].ge(0.95).all()
        )
        self.assertEqual(set(result.drift["fold"]), {1, 2, 3})
        self.assertEqual(set(result.group_eligibility.query("feature_group == 'moneyflow'")["fold"]), {1, 2, 3})
        moneyflow = result.group_eligibility.query("feature_group == 'moneyflow'").iloc[0]
        self.assertGreaterEqual(moneyflow["coverage"], 0.8)
        self.assertEqual(moneyflow["eligibility"], "pending_oof_group_comparison")


if __name__ == "__main__":
    import unittest

    unittest.main()
