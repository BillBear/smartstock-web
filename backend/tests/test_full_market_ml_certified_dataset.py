"""Tests for the pre-feature full-market sample certification contract."""
from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.certified_dataset import (
    build_certified_split_plan,
    certify_full_market_run,
    load_certification_dataset,
)


def _rows(*, date_count: int = 460, symbol_count: int = 50) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=date_count)
    rows = []
    for date_index, trade_date in enumerate(dates):
        for symbol_index in range(symbol_count):
            rows.append(
                {
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "symbol": f"{symbol_index:06d}",
                    "industry_l1": f"IND{symbol_index % 5}",
                    "total_mv": 1_000_000_000 + symbol_index * 100_000,
                    "amount_cny": 20_000_000 + symbol_index * 100_000,
                    "eligible_for_training": True,
                    "entry_tradeable": True,
                    "alpha_relevance_grade_10d": symbol_index % 5,
                    "alpha_top10_10d": symbol_index % 10 == 0,
                    "alpha_target_10d": symbol_index / 10_000,
                    "market_median_net_return_10d": 0.01,
                    "net_return_after_cost_10d": 0.01 + symbol_index / 10_000,
                }
            )
    return pd.DataFrame(rows)


class CertifiedSplitPlanTests(unittest.TestCase):
    def test_builds_sealed_temporal_audit_and_five_embargoed_outer_folds(self) -> None:
        plan = build_certified_split_plan(_rows())

        self.assertEqual(60, len(plan["sealed_temporal_audit_dates"]))
        self.assertEqual(5, len(plan["outer_folds"]))
        self.assertEqual(10, len(plan["stock_holdout_symbols"]))
        self.assertFalse(set(plan["training_symbols"]) & set(plan["stock_holdout_symbols"]))
        self.assertFalse(set(plan["development_dates"]) & set(plan["sealed_temporal_audit_dates"]))
        self.assertEqual("not_collected", plan["evaluation_quadrants"]["B_future_seen"]["status"])
        self.assertEqual(plan["stock_holdout_symbols"], plan["evaluation_quadrants"]["C_development_unseen"]["symbols"])
        for fold in plan["outer_folds"]:
            self.assertGreaterEqual(len(fold["fit_dates"]), 120)
            self.assertEqual(40, len(fold["validation_dates"]))
            self.assertEqual(40, len(fold["test_dates"]))
            self.assertEqual(20, fold["fit_to_validation_embargo_sessions"])
            self.assertEqual(20, fold["validation_to_test_embargo_sessions"])
            self.assertLess(fold["fit_dates"][-1], fold["validation_dates"][0])
            self.assertLess(fold["validation_dates"][-1], fold["test_dates"][0])

    def test_rejects_dataset_too_short_for_registered_outer_roles(self) -> None:
        with self.assertRaisesRegex(ValueError, "insufficient development dates"):
            build_certified_split_plan(_rows(date_count=299))

    def test_two_year_window_marks_overlapping_outer_test_windows_without_reusing_rows_within_fold(self) -> None:
        plan = build_certified_split_plan(_rows(date_count=387))

        self.assertTrue(plan["outer_test_windows_overlap"])
        self.assertEqual("fold_local_metrics_only", plan["outer_test_aggregation_policy"])
        for fold in plan["outer_folds"]:
            self.assertFalse(set(fold["fit_dates"]) & set(fold["validation_dates"]))
            self.assertFalse(set(fold["validation_dates"]) & set(fold["test_dates"]))
            self.assertFalse(set(fold["fit_dates"]) & set(fold["test_dates"]))

    def test_is_reproducible_and_excludes_ineligible_rows(self) -> None:
        rows = _rows()
        rows.loc[rows["symbol"].eq("000000"), "eligible_for_training"] = False
        first = build_certified_split_plan(rows, seed=20260718)
        second = build_certified_split_plan(rows, seed=20260718)

        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["stock_holdout_symbols"], second["stock_holdout_symbols"])
        self.assertTrue(np.isfinite(float(first["stock_holdout_ratio_actual"])))


class CertifiedDatasetTests(unittest.TestCase):
    def test_certification_reader_loads_only_sample_label_and_split_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "dataset.parquet"
            rows = _rows(date_count=2, symbol_count=2)
            rows["entry_tradeable"] = True
            rows["alpha_target_10d"] = 0.1
            rows["severe_negative_10d"] = False
            rows["sl_before_tp_10d"] = False
            rows["future_limit_down_count_10d"] = 0
            rows["large_unused_feature"] = "x" * 10_000
            rows.to_parquet(source, index=False)

            result = load_certification_dataset(source)

            self.assertNotIn("large_unused_feature", result.columns)
            self.assertIn("alpha_relevance_grade_10d", result.columns)
            self.assertIn("industry_l1", result.columns)

    def test_certifies_pre_feature_dataset_without_model_or_feature_audit_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "run"
            output_root = root / "assets"
            artifact_root = run_root / "artifacts" / "full-build"
            panel_root = run_root / "panel" / "stage=full-build"
            manifest_root = run_root / "manifests"
            artifact_root.mkdir(parents=True)
            panel_root.mkdir(parents=True)
            manifest_root.mkdir(parents=True)
            rows = _rows(symbol_count=1000)
            rows["severe_negative_10d"] = False
            rows["sl_before_tp_10d"] = False
            rows["future_limit_down_count_10d"] = 0
            rows.to_parquet(artifact_root / "dataset.parquet", index=False)
            (artifact_root / "quality_report.json").write_text(
                json.dumps({"ready": True, "row_count": len(rows), "duplicate_key_count": 0}),
                encoding="utf-8",
            )
            (panel_root / "feature_contract.json").write_text(
                json.dumps({"allowed_feature_columns": ["amount_cny", "turnover_rate"]}),
                encoding="utf-8",
            )
            (manifest_root / "full-build.json").write_text(
                json.dumps({"config_sha256": "a" * 64, "partitions": []}), encoding="utf-8"
            )

            result = certify_full_market_run(
                run_root=run_root,
                asset_root=output_root,
                code_commit="b" * 40,
            )

            self.assertEqual("certified_research_sample", result["status"])
            self.assertFalse(result["production_integration_allowed"])
            self.assertTrue(Path(result["dataset_path"]).is_file())
            self.assertTrue(Path(result["registry_path"]).is_file())
            self.assertTrue(Path(result["sample_contract_path"]).is_file())
            self.assertEqual("not_collected", result["split_plan"]["formal_future_holdout_status"])
            registry = json.loads(Path(result["registry_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["dataset_id"], registry["dataset_id"])
            self.assertNotIn("feature_audit", registry["required_inputs"])
            self.assertNotIn("candidate_manifest", registry["required_inputs"])


if __name__ == "__main__":
    unittest.main()
