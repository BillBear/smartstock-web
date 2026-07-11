from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.evaluation.full_market_ml.collector import collect_full_market_raw
from app.evaluation.full_market_ml.config import DatesConfig, load_full_market_ml_config
from tests.full_market_ml_fixtures import FakeTuShareClient


class FullMarketMLTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        base = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        self.config = replace(
            base,
            dates=DatesConfig(
                signal_start="2026-07-09",
                signal_end="2026-07-09",
                holdout_start="2026-07-09",
                holdout_end="2026-07-09",
            ),
        )

    def tearDown(self):
        self.temporary_directory.cleanup()


class FullMarketMLCollectorTests(FullMarketMLTestCase):
    def test_resume_repairs_missing_endpoint_without_recollecting_daily(self):
        client = FakeTuShareClient(fail_once={"daily_basic": 1})
        with patch("app.evaluation.full_market_ml.collector.time.sleep"):
            first = collect_full_market_raw(self.config, client, self.temp_path, stage="probe", resume=True)
            second = collect_full_market_raw(self.config, client, self.temp_path, stage="probe", resume=True)

        self.assertEqual(first.endpoint_errors["daily_basic"], 1)
        self.assertEqual(second.partition_status("daily", "20260709"), "reused")
        self.assertEqual(second.partition_status("daily_basic", "20260709"), "collected")

    def test_retries_transient_request_before_marking_partition_complete(self):
        client = FakeTuShareClient(transient_failures={"daily": 2})
        with patch("app.evaluation.full_market_ml.collector.time.sleep") as sleep:
            manifest = collect_full_market_raw(self.config, client, self.temp_path, "probe")

        self.assertTrue(manifest.ready)
        self.assertEqual(client.calls["daily"], 3)
        self.assertEqual(sleep.call_args_list[0].args[0], 1)
        self.assertEqual(sleep.call_args_list[1].args[0], 2)

    def test_core_endpoint_failure_blocks_manifest_but_optional_moneyflow_does_not(self):
        with patch("app.evaluation.full_market_ml.collector.time.sleep"):
            core = collect_full_market_raw(
                self.config,
                FakeTuShareClient(always_fail={"adj_factor"}),
                self.temp_path / "core",
                "probe",
            )
            optional = collect_full_market_raw(
                self.config,
                FakeTuShareClient(always_fail={"moneyflow"}),
                self.temp_path / "optional",
                "probe",
            )

        self.assertFalse(core.ready)
        self.assertIn("adj_factor_collection_failed", core.blocking_codes)
        self.assertTrue(optional.ready)
        self.assertEqual(optional.optional_failures, ["moneyflow"])

    def test_manifest_hash_schema_and_row_count_make_partition_reusable(self):
        client = FakeTuShareClient()
        first = collect_full_market_raw(self.config, client, self.temp_path, "probe")
        partition = first.partition("daily", "20260709")

        self.assertTrue((self.temp_path / partition.path).is_file())
        self.assertEqual(partition.row_count, 2)
        self.assertTrue(partition.schema)
        self.assertEqual(len(partition.sha256), 64)

        second = collect_full_market_raw(self.config, client, self.temp_path, "probe")
        self.assertEqual(second.partition_status("daily", "20260709"), "reused")
        self.assertEqual(client.calls["daily"], 1)

    def test_static_endpoints_historical_industry_and_four_index_scope(self):
        client = FakeTuShareClient()
        manifest = collect_full_market_raw(self.config, client, self.temp_path, "probe")

        self.assertEqual(manifest.partition_status("stock_basic", "L"), "collected")
        self.assertEqual(manifest.partition_status("stock_basic", "D"), "collected")
        self.assertEqual(manifest.partition_status("stock_basic", "P"), "collected")
        self.assertEqual(client.index_daily_codes, ["000001.SH", "000300.SH", "000905.SH", "399006.SZ"])
        self.assertTrue(manifest.industry_relative_enabled)
        self.assertEqual(client.calls["index_classify"], 1)
        self.assertEqual(client.calls["index_member_all"], 2)

    def test_industry_failure_disables_relative_data_without_current_industry_fallback(self):
        with patch("app.evaluation.full_market_ml.collector.time.sleep"):
            manifest = collect_full_market_raw(
                self.config,
                FakeTuShareClient(always_fail={"index_member_all"}),
                self.temp_path,
                "probe",
            )

        self.assertTrue(manifest.ready)
        self.assertFalse(manifest.industry_relative_enabled)
        self.assertIn("historical_industry", manifest.optional_failures)
