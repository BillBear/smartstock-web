from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from app.evaluation.full_market_ml.config import load_full_market_ml_config
from app.evaluation.full_market_ml.manifests import CollectionManifest, PartitionRecord
from app.evaluation.full_market_ml.quality import TrainingBlockedError, audit_panel_quality


class FullMarketMLQualityTests(unittest.TestCase):
    def setUp(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        self.config = replace(config, sample=replace(config.sample, minimum_daily_symbols=3))

    def test_duplicate_primary_key_blocks_training(self):
        panel = valid_panel()
        report = audit_panel_quality(self.config, pd.concat([panel, panel.iloc[[0]]], ignore_index=True), valid_manifest())

        self.assertFalse(report.ready)
        self.assertEqual(report.duplicate_key_count, 1)
        self.assertIn("duplicate_primary_keys", report.blocking_codes)
        with self.assertRaises(TrainingBlockedError) as error:
            report.require_ready()
        self.assertEqual(error.exception.blocking_codes, ("duplicate_primary_keys",))

    def test_optional_moneyflow_coverage_removes_feature_group_without_blocking(self):
        report = audit_panel_quality(self.config, valid_panel(moneyflow_coverage=0.60), valid_manifest())

        self.assertTrue(report.ready)
        self.assertIn("moneyflow", report.disabled_feature_groups)
        self.assertEqual(report.moneyflow_coverage, 0.60)

    def test_core_missing_or_invalid_fields_block_before_training(self):
        panel = valid_panel()
        panel.loc[0, "adjusted_close"] = None
        panel.loc[1, "adjusted_high"] = 9.0
        report = audit_panel_quality(self.config, panel, valid_manifest())

        self.assertFalse(report.ready)
        self.assertIn("required_feature_missingness", report.blocking_codes)
        self.assertIn("invalid_ohlc", report.blocking_codes)
        self.assertEqual(report.missingness["adjusted_close"], 1 / len(panel))

    def test_missing_required_join_and_manifest_failure_block_training(self):
        panel = valid_panel()
        panel.loc[0, "listing_age_trade_days"] = None
        manifest = valid_manifest()
        manifest.blocking_codes.append("daily_collection_failed")
        report = audit_panel_quality(self.config, panel, manifest)

        self.assertIn("manifest_not_ready", report.blocking_codes)
        self.assertIn("required_join_coverage_incomplete", report.blocking_codes)
        self.assertIn("manifest:daily_collection_failed", report.exclusion_reasons)

    def test_daily_universe_and_required_coverage_block_training(self):
        panel = valid_panel().query("trade_date != '2025-01-03'").reset_index(drop=True)
        report = audit_panel_quality(self.config, panel, valid_manifest())

        self.assertIn("required_date_coverage_incomplete", report.blocking_codes)
        self.assertIn("minimum_daily_universe_not_met", report.blocking_codes)
        self.assertEqual(report.per_date_universe_count["2025-01-02"], 5)
        self.assertEqual(report.required_date_coverage, 0.5)

    def test_listing_board_industry_and_sample_estimate_are_audited(self):
        panel = valid_panel()
        panel.loc[:, "listing_age_trade_days"] = 0
        panel.loc[:, "industry_l1"] = None
        panel.loc[:, "symbol"] = ["000001"] * len(panel)
        report = audit_panel_quality(self.config, panel, valid_manifest())

        self.assertIn("listing_coverage_incomplete", report.blocking_codes)
        self.assertIn("industry_coverage_incomplete", report.blocking_codes)
        self.assertIn("board_coverage_incomplete", report.blocking_codes)
        self.assertIn("insufficient_training_samples", report.blocking_codes)
        self.assertEqual(report.sample_estimates["eligible_signal_rows"], 0)
        self.assertEqual(report.board_coverage["STAR"], 0.0)

    def test_report_is_serializable_without_persisting_it(self):
        report = audit_panel_quality(self.config, valid_panel(), valid_manifest())

        payload = report.to_dict()
        self.assertTrue(payload["ready"])
        self.assertIn("per_date_universe_count", payload)
        self.assertIn("blocking_codes", report.to_json())
        self.assertEqual(report.to_csv_rows()[0]["record_type"], "summary")

    def test_manifest_is_required_and_disabled_industry_is_not_silently_required(self):
        missing_manifest = audit_panel_quality(self.config, valid_panel(), None)
        self.assertIn("manifest_missing", missing_manifest.blocking_codes)

        panel = valid_panel()
        panel["industry_l1"] = None
        manifest = valid_manifest()
        manifest.industry_relative_enabled = False
        report = audit_panel_quality(self.config, panel, manifest)
        self.assertTrue(report.ready)
        self.assertIn("industry_relative", report.disabled_feature_groups)
        self.assertNotIn("required_feature_missingness", report.blocking_codes)


def valid_manifest() -> CollectionManifest:
    return CollectionManifest(
        stage="quality-test",
        config_sha256="test",
        request_pacing_seconds=0.01,
        partitions=[
            PartitionRecord("daily", "20250102", "unused", 3, "", ""),
            PartitionRecord("daily", "20250103", "unused", 3, "", ""),
        ],
    )


def valid_panel(*, moneyflow_coverage: float | None = None) -> pd.DataFrame:
    rows = []
    for trade_date in ("2025-01-02", "2025-01-03"):
        for symbol, industry in (
            ("000001", "Bank"),
            ("000002", "Bank"),
            ("000003", "Bank"),
            ("300001", "Technology"),
            ("688001", "Materials"),
        ):
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "adjusted_open": 10.0,
                    "adjusted_high": 11.0,
                    "adjusted_low": 9.0,
                    "adjusted_close": 10.0,
                    "valid_ohlc": True,
                    "listing_age_trade_days": 20,
                    "industry_l1": industry,
                    "eligible_signal_day": True,
                    "entry_tradeable": True,
                }
            )
    panel = pd.DataFrame(rows)
    if moneyflow_coverage is not None:
        count = round(len(panel) * moneyflow_coverage)
        panel["net_mf_amount"] = [1.0] * count + [None] * (len(panel) - count)
    return panel


if __name__ == "__main__":
    unittest.main()
