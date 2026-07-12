from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq
import pyarrow as pa
import pandas as pd

from app.evaluation.full_market_ml.config import load_full_market_ml_config
from app.evaluation.full_market_ml import panel as panel_module
from app.evaluation.full_market_ml.panel import (
    build_full_market_panel,
    build_historical_universe,
    build_panel_from_frames,
)
from app.evaluation.full_market_ml.manifests import CollectionManifest, PartitionRecord, save_manifest
from tests.full_market_ml_fixtures import (
    delisted_daily_fixture,
    frame,
    historical_industry_fixture,
    historical_st_fixture,
    mixed_typed_suspension_interval_fixture,
    next_open_suspension_fixture,
    open_ended_suspension_fixture,
    pre_signal_st_fixture,
    suspension_interval_fixture,
    twenty_session_panel_fixture,
    two_day_split_fixture,
)


class FullMarketMLPanelTests(unittest.TestCase):
    def test_historical_universe_includes_delisted_stock_before_delist_date(self):
        basic = frame([{"symbol": "600001", "list_date": "20200101", "delist_date": "20250115", "list_status": "D"}])
        universe = build_historical_universe(basic, ["2025-01-10", "2025-01-20"])

        self.assertEqual(universe.query("trade_date == '2025-01-10'")["symbol"].tolist(), ["600001"])
        self.assertTrue(universe.query("trade_date == '2025-01-20'").empty)

    def test_full_build_excludes_daily_row_after_delist_date(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_raw_fixture(root, config, "delisted", delisted_daily_fixture())

            result = build_full_market_panel(
                replace(config, dates=replace(config.dates, signal_start="2025-01-02", signal_end="2025-01-03")), root, "delisted"
            )

            final_panel = self._read_shards(result.shard_paths)
            self.assertEqual(final_panel["trade_date"].tolist(), ["2025-01-02"])

    def test_full_build_blocks_tampered_manifested_raw_partition(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_raw_fixture(root, config, "tampered", two_day_split_fixture())
            daily_path = root / manifest.partition("daily", "20250102").path
            table = pq.ParquetFile(daily_path).read()
            pq.write_table(table.append_column("tampered", pa.array([True] * table.num_rows)), daily_path)

            with self.assertRaisesRegex(ValueError, "manifest partition integrity"):
                build_full_market_panel(
                    replace(config, dates=replace(config.dates, signal_start="2025-01-02", signal_end="2025-01-03")), root, "tampered"
                )

    def test_full_build_blocks_tampered_optional_manifest_partition(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = two_day_split_fixture()
            fixtures["moneyflow"] = frame(
                [{"ts_code": "000001.SZ", "trade_date": "20250102", "net_mf_amount": 1.0}]
            )
            manifest = self._write_raw_fixture(root, config, "tampered-optional", fixtures)
            moneyflow_path = root / manifest.partition("moneyflow", "20250102").path
            table = pq.ParquetFile(moneyflow_path).read()
            pq.write_table(table.append_column("tampered", pa.array([True] * table.num_rows)), moneyflow_path)

            with self.assertRaisesRegex(ValueError, "manifest partition integrity"):
                build_full_market_panel(
                    replace(config, dates=replace(config.dates, signal_start="2025-01-02", signal_end="2025-01-03")),
                    root,
                    "tampered-optional",
                )

    def test_full_build_excludes_failed_optional_manifest_partition(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._write_raw_fixture(root, config, "failed-optional", two_day_split_fixture())
            manifest.partitions.append(
                PartitionRecord("moneyflow", "20250102", "raw/endpoint=moneyflow/trade_date=20250102/data.parquet", 0, "", "", "failed")
            )
            save_manifest(root, manifest)

            result = build_full_market_panel(
                replace(config, dates=replace(config.dates, signal_start="2025-01-02", signal_end="2025-01-03")), root, "failed-optional"
            )

            self.assertEqual(result.row_count, 2)

    def test_full_build_joins_daily_basic_and_moneyflow_raw_fields_by_symbol_and_date(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        fixtures = two_day_split_fixture()
        fixtures["daily_basic"] = frame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250102", "turnover_rate": 2.5, "total_mv": 100.0, "circ_mv": 80.0, "pe": 10.0, "pb": 1.5, "ps": 2.0},
                {"ts_code": "000001.SZ", "trade_date": "20250103", "turnover_rate": 3.0, "total_mv": 110.0, "circ_mv": 85.0, "pe": 11.0, "pb": 1.6, "ps": 2.1},
            ]
        )
        fixtures["moneyflow"] = frame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250102", "net_mf_amount": 12.0, "net_mf_vol": 3.0},
                {"ts_code": "000001.SZ", "trade_date": "20250103", "net_mf_amount": -4.0, "net_mf_vol": -1.0},
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_raw_fixture(root, config, "joined-raw", fixtures)
            result = build_full_market_panel(
                replace(config, dates=replace(config.dates, signal_start="2025-01-02", signal_end="2025-01-03")), root, "joined-raw"
            )
            panel = self._read_shards(result.shard_paths)
            first = panel.loc[panel.trade_date.eq("2025-01-02")].iloc[0]
            self.assertEqual(first["turnover_rate"], 2.5)
            self.assertEqual(first["total_mv"], 100.0)
            self.assertEqual(first["net_mf_amount"], 12.0)
            self.assertEqual(first["net_mf_vol"], 3.0)

    def test_panel_joins_index_context_by_trade_date(self):
        fixtures = two_day_split_fixture()
        fixtures["index_daily"] = frame(
            [
                {"ts_code": "000001.SH", "trade_date": "20250102", "close": 100.0, "amount": 1000.0},
                {"ts_code": "000001.SH", "trade_date": "20250103", "close": 102.0, "amount": 1200.0},
            ]
        )

        panel = build_panel_from_frames(fixtures)

        first = panel.loc[panel.trade_date.eq("2025-01-02")].iloc[0]
        self.assertEqual(first["market_index_close"], 100.0)
        self.assertEqual(first["market_index_amount"], 1000.0)

    def test_conflicting_index_rows_for_one_date_block_panel_build(self):
        equivalent = two_day_split_fixture()
        equivalent["index_daily"] = frame(
            [
                {"ts_code": "000001.SH", "trade_date": "20250102", "close": 100.0, "amount": 1000.0},
                {"ts_code": "000001.SH", "trade_date": "20250102", "close": 100.0, "amount": 1000.0},
            ]
        )
        self.assertEqual(build_panel_from_frames(equivalent).loc[lambda rows: rows.trade_date == "2025-01-02", "market_index_close"].iloc[0], 100.0)

        fixtures = two_day_split_fixture()
        fixtures["index_daily"] = frame(
            [
                {"ts_code": "000001.SH", "trade_date": "20250102", "close": 100.0, "amount": 1000.0},
                {"ts_code": "000001.SH", "trade_date": "20250102", "close": 101.0, "amount": 1000.0},
            ]
        )

        with self.assertRaisesRegex(ValueError, "conflicting index_daily rows"):
            build_panel_from_frames(fixtures)

    def test_missing_or_nonpositive_adj_factor_invalidates_adjusted_rows_and_prior_entry(self):
        for name, factor in (("missing", None), ("zero", 0.0)):
            with self.subTest(name=name):
                panel = build_panel_from_frames(twenty_session_panel_fixture(final_adj_factor=factor))
                final_row = panel.iloc[-1]
                prior_row = panel.iloc[-2]

                self.assertFalse(bool(final_row["valid_ohlc"]))
                self.assertFalse(bool(final_row["eligible_signal_day"]))
                self.assertFalse(bool(prior_row["entry_tradeable"]))

    def test_full_build_reuses_one_calendar_lookup_across_daily_partitions(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        fixtures = twenty_session_panel_fixture(final_adj_factor=1.0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_raw_fixture(root, config, "calendar-lookup", fixtures)
            dates = fixtures["trade_cal"]["cal_date"].map(lambda value: f"{value[:4]}-{value[4:6]}-{value[6:8]}")
            config = replace(config, dates=replace(config.dates, signal_start=dates.iloc[0], signal_end=dates.iloc[-1]))

            with patch.object(panel_module, "_build_calendar_lookup", wraps=panel_module._build_calendar_lookup) as build_lookup:
                result = build_full_market_panel(config, root, "calendar-lookup")

            final_panel = self._read_shards(result.shard_paths)
            self.assertEqual(build_lookup.call_count, 1)
            self.assertEqual(final_panel["listing_age_trade_days"].tolist(), list(range(1, 21)))

    def test_suspend_interval_uses_suspend_and_resume_dates(self):
        panel = build_panel_from_frames(suspension_interval_fixture())

        self.assertTrue(bool(panel.loc[panel.trade_date == "2025-01-03", "is_suspended"].item()))
        self.assertFalse(bool(panel.loc[panel.trade_date == "2025-01-06", "is_suspended"].item()))
        self.assertFalse(bool(panel.loc[panel.trade_date == "2025-01-02", "entry_tradeable"].item()))

    def test_next_open_uses_exact_next_calendar_session_not_later_resume_row(self):
        panel = build_panel_from_frames(next_open_suspension_fixture())
        row = panel.loc[panel.trade_date == "2025-01-02"].iloc[0]

        self.assertEqual(row["next_open_date"], "2025-01-03")
        self.assertTrue(pd.isna(row["next_adjusted_open"]))
        self.assertFalse(bool(row["entry_tradeable"]))

    def test_suspend_interval_without_resume_last_through_available_calendar(self):
        panel = build_panel_from_frames(open_ended_suspension_fixture())

        self.assertTrue(bool(panel.loc[panel.trade_date == "2025-01-06", "is_suspended"].item()))

    def test_full_build_carries_suspend_interval_from_prior_raw_partition(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_raw_fixture(root, config, "open-ended-suspend", open_ended_suspension_fixture())

            result = build_full_market_panel(
                replace(config, dates=replace(config.dates, signal_start="2025-01-02", signal_end="2025-01-06")), root, "open-ended-suspend"
            )

            final_panel = self._read_shards(result.shard_paths)
            self.assertTrue(bool(final_panel.loc[final_panel.trade_date == "2025-01-06", "is_suspended"].item()))

    def test_conflicting_limit_rows_block_entry_tradeability_build(self):
        permissive = two_day_split_fixture()
        permissive["stk_limit"] = frame(
            [{"ts_code": "000001.SZ", "trade_date": "20250103", "up_limit": 11.0, "down_limit": 9.0}]
        )
        self.assertTrue(bool(build_panel_from_frames(permissive).loc[lambda rows: rows.trade_date == "2025-01-02", "entry_tradeable"].item()))

        equivalent = two_day_split_fixture()
        equivalent["stk_limit"] = frame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250103", "up_limit": 11.0, "down_limit": 9.0},
                {"ts_code": "000001.SZ", "trade_date": "20250103", "up_limit": 11.0, "down_limit": 9.0},
            ]
        )
        self.assertTrue(bool(build_panel_from_frames(equivalent).loc[lambda rows: rows.trade_date == "2025-01-02", "entry_tradeable"].item()))

        conflicting = two_day_split_fixture()
        conflicting["stk_limit"] = frame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250103", "up_limit": 10.0, "down_limit": 9.0},
                {"ts_code": "000001.SZ", "trade_date": "20250103", "up_limit": 11.0, "down_limit": 9.0},
            ]
        )
        with self.assertRaisesRegex(ValueError, "conflicting duplicate stk_limit"):
            build_panel_from_frames(conflicting)

    def test_end_of_day_limit_flags_use_close_while_entry_uses_open_flag(self):
        fixtures = two_day_split_fixture()
        fixtures["daily"].loc[0, ["open", "high", "low", "close"]] = [10.0, 11.0, 9.0, 11.0]
        fixtures["daily"].loc[1, ["open", "high", "low", "close"]] = [10.0, 11.0, 9.0, 9.0]
        fixtures["stk_limit"] = frame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250102", "up_limit": 11.0, "down_limit": 9.0},
                {"ts_code": "000001.SZ", "trade_date": "20250103", "up_limit": 11.0, "down_limit": 9.0},
            ]
        )

        panel = build_panel_from_frames(fixtures)
        up_close = panel.loc[panel.trade_date == "2025-01-02"].iloc[0]
        down_close = panel.loc[panel.trade_date == "2025-01-03"].iloc[0]

        self.assertTrue(bool(up_close["at_up_limit"]))
        self.assertFalse(bool(up_close["at_up_limit_open"]))
        self.assertTrue(bool(down_close["at_down_limit"]))
        self.assertFalse(bool(down_close["at_up_limit_open"]))

    def test_mixed_typed_dates_normalize_before_suspension_interval_comparison(self):
        panel = build_panel_from_frames(mixed_typed_suspension_interval_fixture())

        self.assertTrue(bool(panel.loc[panel.trade_date == "2025-01-03", "is_suspended"].item()))
        self.assertFalse(bool(panel.loc[panel.trade_date == "2025-01-06", "is_suspended"].item()))

    def test_adjusted_ohlc_and_next_open_tradeability_are_correct(self):
        panel = build_panel_from_frames(two_day_split_fixture())
        row = panel.query("trade_date == '2025-01-02'").iloc[0]

        self.assertEqual(row["adjusted_close"], 20.0)
        self.assertEqual(row["next_adjusted_open"], 20.0)
        self.assertTrue(bool(row["entry_tradeable"]))

    def test_historical_st_status_uses_namechange_interval_not_current_name(self):
        panel = build_panel_from_frames(historical_st_fixture())

        self.assertTrue(bool(panel.loc[panel.trade_date == "2025-01-02", "is_st"].item()))
        self.assertFalse(bool(panel.loc[panel.trade_date == "2025-03-03", "is_st"].item()))

    def test_st_interval_starting_before_signal_start_remains_active(self):
        panel = build_panel_from_frames(pre_signal_st_fixture())

        self.assertTrue(bool(panel.loc[panel.trade_date == "2025-01-02", "is_st"].item()))

    def test_historical_industry_uses_membership_interval(self):
        panel = build_panel_from_frames(historical_industry_fixture())

        self.assertEqual(panel.loc[panel.trade_date == "2024-12-31", "industry_l1"].item(), "基础化工")
        self.assertEqual(panel.loc[panel.trade_date == "2025-01-02", "industry_l1"].item(), "有色金属")

    def test_overlapping_historical_industry_intervals_block_panel_build(self):
        fixtures = historical_industry_fixture()
        fixtures["index_member_all"] = frame(
            [
                {"l1_code": "801010.SI", "con_code": "000001.SZ", "in_date": "20200101", "out_date": "20250131"},
                {"l1_code": "801020.SI", "con_code": "000001.SZ", "in_date": "20250101", "out_date": ""},
            ]
        )

        with self.assertRaisesRegex(ValueError, "overlapping historical industry intervals"):
            build_panel_from_frames(fixtures)

    def test_units_are_converted_once_and_conflicting_market_duplicates_block_build(self):
        panel = build_panel_from_frames(two_day_split_fixture())
        row = panel.query("trade_date == '2025-01-02'").iloc[0]
        self.assertEqual(row["volume_shares"], 200.0)
        self.assertEqual(row["amount_cny"], 3000.0)

        conflicting = two_day_split_fixture()
        conflicting["daily"] = pd.concat(
            [
                conflicting["daily"],
                pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20250102", "open": 99.0, "high": 11.0, "low": 9.0, "close": 10.0, "vol": 2.0, "amount": 3.0}]),
            ],
            ignore_index=True,
        )
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            build_panel_from_frames(conflicting)

    def test_industry_disabled_keeps_industry_null(self):
        panel = build_panel_from_frames(historical_industry_fixture(), industry_relative_enabled=False)
        self.assertTrue(panel["industry_l1"].isna().all())
        self.assertFalse(panel["industry_relative_enabled"].any())

    def test_full_build_writes_all_deterministic_symbol_shards(self):
        config = load_full_market_ml_config(Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_raw_fixture(root, config, "panel-test", two_day_split_fixture())

            result = build_full_market_panel(replace(config, dates=replace(config.dates, signal_start="2025-01-02", signal_end="2025-01-03")), root, "panel-test")

            self.assertEqual(result.row_count, 2)
            self.assertEqual(len(result.shard_paths), 64)
            self.assertTrue(all(path.is_file() for path in result.shard_paths))
            contract = json.loads(result.feature_contract_path.read_text(encoding="utf-8"))
            self.assertTrue(contract["allowed_feature_columns"])
            self.assertFalse(any(column.startswith("next_") or column == "entry_tradeable" for column in contract["allowed_feature_columns"]))
            future_columns = {
                column
                for column in self._read_shards(result.shard_paths).columns
                if column.startswith("next_") or column == "entry_tradeable"
            }
            self.assertTrue(future_columns)
            self.assertTrue(future_columns.issubset(set(contract["excluded_future_execution_columns"])))

    def _write_raw_fixture(self, root, config, stage, fixtures):
        manifest = CollectionManifest(stage, config.sha256, config.collection.request_pacing_seconds)
        static_endpoints = {"stock_basic", "namechange", "index_classify", "index_member_all"}
        for endpoint, values in fixtures.items():
            if endpoint in static_endpoints:
                path = root / "raw" / f"endpoint={endpoint}" / "data.parquet"
                key = "static" if endpoint == "namechange" else ("L" if endpoint == "stock_basic" else "SW2021-L1")
                self._write_manifest_partition(root, manifest, endpoint, key, path, values)
                continue
            date_column = next((name for name in ("trade_date", "cal_date", "suspend_date") if name in values), None)
            for partition_date, rows in values.groupby(values[date_column] if date_column else lambda _: "static"):
                normalized = str(partition_date).replace("-", "")
                path = root / "raw" / f"endpoint={endpoint}" / f"trade_date={normalized}" / "data.parquet"
                self._write_manifest_partition(root, manifest, endpoint, normalized, path, rows)
        save_manifest(root, manifest)
        return manifest

    def _write_manifest_partition(self, root, manifest, endpoint, key, path, values):
        path.parent.mkdir(parents=True, exist_ok=True)
        values.to_parquet(path, index=False)
        manifest.partitions.append(
            PartitionRecord(
                endpoint,
                key,
                str(path.relative_to(root)),
                len(values),
                str(pq.ParquetFile(path).read().schema),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )

    def _read_shards(self, paths):
        return pd.concat([pq.ParquetFile(path).read().to_pandas() for path in paths], ignore_index=True).sort_values(
            ["symbol", "trade_date"], kind="stable"
        ).reset_index(drop=True)


if __name__ == "__main__":
    unittest.main()
