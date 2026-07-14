from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.evaluation.full_market_ml.collector import collect_full_market_raw, collect_point_in_time_fundamentals
from app.evaluation.full_market_ml.config import DatesConfig, load_full_market_ml_config
from app.evaluation.full_market_ml.manifests import load_manifest, manifest_path
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
    def test_fundamental_collection_is_additive_and_resumable_by_symbol(self):
        client = FakeTuShareClient()
        output = self.temp_path / "fundamentals"

        first = collect_point_in_time_fundamentals(
            client,
            ("000001.SZ", "000002.SZ"),
            output,
            start_date="20240101",
            end_date="20251231",
            pacing_seconds=0.0,
        )
        second = collect_point_in_time_fundamentals(
            client,
            ("000001.SZ", "000002.SZ"),
            output,
            start_date="20240101",
            end_date="20251231",
            pacing_seconds=0.0,
        )

        self.assertEqual(first["status"], "complete")
        self.assertEqual(second["status"], "complete")
        self.assertEqual(client.calls["fina_indicator"], 2)
        self.assertEqual(client.calls["forecast"], 2)
        self.assertEqual(client.calls["express"], 2)
        self.assertTrue((output / "endpoint=fina_indicator" / "symbol=000001.SZ" / "data.parquet").is_file())

    def test_persists_verified_open_calendar_dates_across_reload_and_resume(self):
        config = replace(
            self.config,
            dates=DatesConfig(
                signal_start="2026-07-09",
                signal_end="2026-07-10",
                holdout_start="2026-07-09",
                holdout_end="2026-07-10",
            ),
        )
        client = FakeTuShareClient(
            calendar_rows=[
                {"cal_date": "20260709", "is_open": "1"},
                {"cal_date": "20260710", "is_open": "0"},
            ]
        )

        collected = collect_full_market_raw(config, client, self.temp_path, "probe")
        reloaded = load_manifest(self.temp_path, "probe", config.sha256, config.collection.request_pacing_seconds)
        resumed = collect_full_market_raw(config, client, self.temp_path, "probe", resume=True)

        self.assertEqual(collected.trade_cal_open_dates, ("2026-07-09",))
        self.assertEqual(reloaded.trade_cal_open_dates, ("2026-07-09",))
        self.assertEqual(resumed.trade_cal_open_dates, ("2026-07-09",))
        self.assertEqual(client.calls["trade_cal"], 1)

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
        delays = [call.args[0] for call in sleep.call_args_list]
        first_backoff = delays.index(1)
        self.assertEqual(delays[first_backoff - 1:first_backoff + 3], [0.01, 1, 0.01, 2])

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
        self.assertEqual(partition.row_count, 4500)
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
        stock_basic_requests = [kwargs for endpoint, kwargs in client.request_kwargs if endpoint == "stock_basic"]
        self.assertEqual([request["list_status"] for request in stock_basic_requests], ["L", "D", "P"])
        self.assertTrue(all("delist_date" in request["fields"] for request in stock_basic_requests))
        self.assertTrue(all("list_status" in request["fields"] for request in stock_basic_requests))

    def test_namechange_collection_starts_at_configured_historical_floor(self):
        client = FakeTuShareClient()
        collect_full_market_raw(self.config, client, self.temp_path, "probe")

        namechange_requests = [kwargs for endpoint, kwargs in client.request_kwargs if endpoint == "namechange"]
        self.assertEqual(namechange_requests, [{"start_date": "19900101", "end_date": "20260709"}])

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

    def test_normalizes_index_member_dataframe_responses(self):
        import pandas as pd

        client = FakeTuShareClient()
        client.index_member_all = lambda *, l1_code: pd.DataFrame(
            [{"l1_code": l1_code, "con_code": "000001.SZ", "in_date": "20200101"}]
        )

        manifest = collect_full_market_raw(self.config, client, self.temp_path, "probe")

        self.assertTrue(manifest.industry_relative_enabled)
        self.assertEqual(manifest.partition("index_member_all", "SW2021-L1").row_count, 2)

    def test_persists_manifest_before_requests_and_after_partition_transition(self):
        client = FakeTuShareClient()
        original_result = client._result
        observed = []

        def observe(endpoint, **kwargs):
            path = manifest_path(self.temp_path, "probe")
            if endpoint == "trade_cal":
                observed.append(path.exists())
            if endpoint == "daily_basic":
                observed.append('"endpoint": "daily"' in path.read_text(encoding="utf-8"))
            return original_result(endpoint, **kwargs)

        client._result = observe
        collect_full_market_raw(self.config, client, self.temp_path, "probe")

        self.assertEqual(observed, [True, True])

    def test_resume_adopts_complete_orphan_partition_without_overwriting_it(self):
        first_client = FakeTuShareClient()
        first = collect_full_market_raw(self.config, first_client, self.temp_path, "probe")
        raw_daily = self.temp_path / first.partition("daily", "20260709").path
        original_hash = raw_daily.read_bytes()
        manifest_path(self.temp_path, "probe").unlink()

        resumed = collect_full_market_raw(
            self.config, FakeTuShareClient(always_fail={"daily"}), self.temp_path, "probe", resume=True
        )

        self.assertEqual(resumed.partition_status("daily", "20260709"), "adopted")
        self.assertEqual(raw_daily.read_bytes(), original_hash)
        self.assertTrue(resumed.ready)

    def test_non_resume_rejects_existing_stage_or_raw_content(self):
        collect_full_market_raw(self.config, FakeTuShareClient(), self.temp_path, "probe")

        with self.assertRaisesRegex(ValueError, "new stage identifier"):
            collect_full_market_raw(self.config, FakeTuShareClient(), self.temp_path, "probe", resume=False)

    def test_incomplete_trade_calendar_blocks_readiness(self):
        config = replace(
            self.config,
            dates=replace(self.config.dates, signal_end="2026-07-10"),
        )
        client = FakeTuShareClient(calendar_rows=[{"cal_date": "20260709", "is_open": "1"}])

        manifest = collect_full_market_raw(config, client, self.temp_path, "probe")

        self.assertFalse(manifest.ready)
        self.assertIn("trade_cal_incomplete", manifest.blocking_codes)

    def test_trade_calendar_with_no_open_dates_blocks_readiness(self):
        client = FakeTuShareClient(calendar_rows=[{"cal_date": "20260709", "is_open": "0"}])

        manifest = collect_full_market_raw(self.config, client, self.temp_path, "probe")

        self.assertFalse(manifest.ready)
        self.assertIn("trade_cal_no_open_dates", manifest.blocking_codes)

    def test_short_required_daily_input_blocks_readiness_but_empty_suspend_is_valid(self):
        short_daily = collect_full_market_raw(
            self.config, FakeTuShareClient(short_endpoints={"daily"}), self.temp_path / "daily", "probe"
        )
        empty_suspend = collect_full_market_raw(
            self.config, FakeTuShareClient(short_endpoints={"suspend_d"}), self.temp_path / "suspend", "probe"
        )

        self.assertIn("daily_insufficient_rows", short_daily.blocking_codes)
        self.assertFalse(short_daily.ready)
        self.assertTrue(empty_suspend.ready)

    def test_missing_allowed_index_daily_data_blocks_readiness(self):
        manifest = collect_full_market_raw(
            self.config,
            FakeTuShareClient(empty_index_daily_codes={"000905.SH"}),
            self.temp_path,
            "probe",
        )

        self.assertFalse(manifest.ready)
        self.assertIn("index_daily_collection_failed", manifest.blocking_codes)

    def test_repaired_run_retains_failure_history_and_can_become_ready(self):
        client = FakeTuShareClient(fail_once={"daily_basic": 1})
        with patch("app.evaluation.full_market_ml.collector.time.sleep"):
            first = collect_full_market_raw(self.config, client, self.temp_path, "probe")
            repaired = collect_full_market_raw(self.config, client, self.temp_path, "probe")

        self.assertFalse(first.ready)
        self.assertTrue(repaired.ready)
        self.assertGreaterEqual(repaired.endpoint_errors["daily_basic"], 1)
        self.assertTrue(any(event["status"] == "failed" for event in repaired.attempt_history))
        self.assertTrue(any(event["status"] == "collected" for event in repaired.attempt_history))

    def test_empty_historical_industry_dataframes_disable_industry_relative_data(self):
        import pandas as pd

        empty_classifications = FakeTuShareClient()
        empty_classifications.index_classify = lambda **_: pd.DataFrame(columns=["index_code", "industry_name"])
        empty_members = FakeTuShareClient()
        empty_members.index_member_all = lambda **_: pd.DataFrame(columns=["l1_code", "con_code", "in_date"])

        for name, client in (("classifications", empty_classifications), ("members", empty_members)):
            with self.subTest(name=name):
                manifest = collect_full_market_raw(self.config, client, self.temp_path / name, "probe")
                self.assertTrue(manifest.ready)
                self.assertFalse(manifest.industry_relative_enabled)
                self.assertIn("historical_industry", manifest.optional_failures)

    def test_empty_suspend_dataframe_preserves_schema_and_reuses_partition(self):
        import pandas as pd

        client = FakeTuShareClient()
        client.suspend_d = lambda **_: pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type"])

        first = collect_full_market_raw(self.config, client, self.temp_path, "probe")
        partition = first.partition("suspend_d", "20260709")
        second = collect_full_market_raw(self.config, client, self.temp_path, "probe")

        self.assertEqual(partition.row_count, 0)
        self.assertIn("ts_code", partition.schema)
        self.assertIn("suspend_type", partition.schema)
        self.assertEqual(second.partition_status("suspend_d", "20260709"), "reused")

    def test_manifested_partition_integrity_failure_is_not_adopted_as_orphan(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        first = collect_full_market_raw(self.config, FakeTuShareClient(), self.temp_path, "probe")
        daily_path = self.temp_path / first.partition("daily", "20260709").path
        original_table = pq.ParquetFile(daily_path).read()
        pq.write_table(original_table.append_column("tampered", pa.array([True] * original_table.num_rows)), daily_path)
        unavailable_daily = FakeTuShareClient(always_fail={"daily"})

        with patch("app.evaluation.full_market_ml.collector.time.sleep"):
            resumed = collect_full_market_raw(self.config, unavailable_daily, self.temp_path, "probe")

        self.assertEqual(unavailable_daily.calls["daily"], 5)
        self.assertEqual(resumed.partition_status("daily", "20260709"), "failed")
        self.assertIn("daily_collection_failed", resumed.blocking_codes)
