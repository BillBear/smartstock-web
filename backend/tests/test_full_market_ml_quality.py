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
        report = audit_panel_quality(self.config, pd.concat([panel, panel.iloc[[0]]], ignore_index=True), valid_manifest(self.config))

        self.assertFalse(report.ready)
        self.assertEqual(report.duplicate_key_count, 1)
        self.assertIn("duplicate_primary_keys", report.blocking_codes)
        with self.assertRaises(TrainingBlockedError) as error:
            report.require_ready()
        self.assertEqual(error.exception.blocking_codes, ("duplicate_primary_keys",))

    def test_optional_moneyflow_coverage_removes_feature_group_without_blocking(self):
        report = audit_panel_quality(self.config, valid_panel(moneyflow_coverage=0.60), valid_manifest(self.config))

        self.assertTrue(report.ready)
        self.assertIn("moneyflow", report.disabled_feature_groups)
        self.assertEqual(report.moneyflow_coverage, 0.60)

    def test_core_missing_or_invalid_fields_block_before_training(self):
        panel = valid_panel()
        panel.loc[0, "adjusted_close"] = None
        panel.loc[1, "adjusted_high"] = 9.0
        report = audit_panel_quality(self.config, panel, valid_manifest(self.config))

        self.assertFalse(report.ready)
        self.assertIn("required_feature_missingness", report.blocking_codes)
        self.assertIn("invalid_ohlc", report.blocking_codes)
        self.assertEqual(report.missingness["adjusted_close"], 1 / len(panel))

    def test_missing_required_join_and_manifest_failure_block_training(self):
        panel = valid_panel()
        panel.loc[0, "listing_age_trade_days"] = None
        manifest = valid_manifest(self.config)
        manifest.blocking_codes.append("daily_collection_failed")
        report = audit_panel_quality(self.config, panel, manifest)

        self.assertIn("manifest_not_ready", report.blocking_codes)
        self.assertIn("required_join_coverage_incomplete", report.blocking_codes)
        self.assertIn("manifest:daily_collection_failed", report.exclusion_reasons)

    def test_daily_universe_and_required_coverage_block_training(self):
        panel = valid_panel().query("trade_date != '2025-01-03'").reset_index(drop=True)
        report = audit_panel_quality(self.config, panel, valid_manifest(self.config))

        self.assertIn("required_date_coverage_incomplete", report.blocking_codes)
        self.assertIn("minimum_daily_universe_not_met", report.blocking_codes)
        self.assertEqual(report.per_date_universe_count["2025-01-02"], 5)
        self.assertEqual(report.required_date_coverage, 0.5)

    def test_listing_board_industry_and_sample_estimate_are_audited(self):
        panel = valid_panel()
        panel.loc[:, "listing_age_trade_days"] = 0
        panel.loc[:, "industry_l1"] = None
        panel.loc[:, "symbol"] = ["000001"] * len(panel)
        report = audit_panel_quality(self.config, panel, valid_manifest(self.config))

        self.assertIn("listing_coverage_incomplete", report.blocking_codes)
        self.assertIn("industry_coverage_incomplete", report.blocking_codes)
        self.assertIn("board_coverage_incomplete", report.blocking_codes)
        self.assertIn("insufficient_training_samples", report.blocking_codes)
        self.assertEqual(report.sample_estimates["eligible_signal_rows"], 0)
        self.assertEqual(report.board_coverage["STAR"], 0.0)

    def test_report_is_serializable_without_persisting_it(self):
        report = audit_panel_quality(self.config, valid_panel(), valid_manifest(self.config))

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
        manifest = valid_manifest(self.config)
        manifest.industry_relative_enabled = False
        report = audit_panel_quality(self.config, panel, manifest)
        self.assertTrue(report.ready)
        self.assertIn("industry_relative", report.disabled_feature_groups)
        self.assertNotIn("required_feature_missingness", report.blocking_codes)

    def test_calendar_open_sessions_not_daily_records_define_required_coverage(self):
        manifest = valid_manifest(self.config)
        manifest.partitions = [record for record in manifest.partitions if record.endpoint != "daily"]
        report = audit_panel_quality(self.config, valid_panel(), manifest)

        self.assertEqual(report.expected_trade_dates, ("2025-01-02", "2025-01-03"))
        self.assertIn("daily_manifest_missing", report.blocking_codes)

    def test_panel_rows_cannot_spoof_persisted_open_calendar_evidence(self):
        manifest = valid_manifest(self.config)
        manifest.trade_cal_open_dates = ("2025-01-02",)
        panel = valid_panel().query("trade_date == '2025-01-03'").reset_index(drop=True)
        report = audit_panel_quality(self.config, panel, manifest)

        self.assertEqual(report.expected_trade_dates, ("2025-01-02",))
        self.assertIn("required_date_coverage_incomplete", report.blocking_codes)

    def test_failed_daily_record_blocks_without_legacy_manifest_code(self):
        manifest = valid_manifest(self.config)
        manifest.partitions[2].status = "failed"
        report = audit_panel_quality(self.config, valid_panel(), manifest)

        self.assertIn("daily_manifest_failed", report.blocking_codes)
        self.assertNotIn("manifest_not_ready", report.blocking_codes)

    def test_partial_daily_manifest_coverage_blocks_training(self):
        manifest = valid_manifest(self.config)
        manifest.partitions = [
            record for record in manifest.partitions if not (record.endpoint == "daily" and record.key == "20250103")
        ]
        report = audit_panel_quality(self.config, valid_panel(), manifest)

        self.assertIn("daily_manifest_incomplete", report.blocking_codes)

    def test_partial_daily_record_status_blocks_without_legacy_manifest_code(self):
        manifest = valid_manifest(self.config)
        manifest.partitions[2].status = "partial"
        report = audit_panel_quality(self.config, valid_panel(), manifest)

        self.assertIn("daily_manifest_incomplete", report.blocking_codes)

    def test_manifest_config_mismatch_blocks_quality_gate(self):
        manifest = valid_manifest(self.config)
        manifest.config_sha256 = "different-config"
        report = audit_panel_quality(self.config, valid_panel(), manifest)

        self.assertIn("manifest_config_mismatch", report.blocking_codes)

    def test_board_coverage_is_required_for_every_expected_trade_date(self):
        panel = valid_panel().query("trade_date != '2025-01-02' or symbol.str.startswith('000')").reset_index(drop=True)
        report = audit_panel_quality(self.config, panel, valid_manifest(self.config))

        self.assertIn("daily_board_coverage_incomplete", report.blocking_codes)
        self.assertEqual(report.per_date_board_coverage["2025-01-02"]["CHINEXT"], 0.0)
        self.assertEqual(report.per_date_board_coverage["2025-01-02"]["STAR"], 0.0)


def valid_manifest(config) -> CollectionManifest:
    manifest = CollectionManifest(
        stage="quality-test",
        config_sha256=config.sha256,
        request_pacing_seconds=0.01,
        partitions=[
            PartitionRecord("trade_cal", "20250102", "unused", 1, "", ""),
            PartitionRecord("trade_cal", "20250103", "unused", 1, "", ""),
            PartitionRecord("daily", "20250102", "unused", 3, "", ""),
            PartitionRecord("daily", "20250103", "unused", 3, "", ""),
        ],
    )
    manifest.trade_cal_open_dates = ("2025-01-02", "2025-01-03")
    return manifest


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
