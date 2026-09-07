import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.data_source_manager import DataSourceManager


class DataSourceManagerTests(unittest.TestCase):
    def test_a_share_snapshot_uses_tushare_basic_map_and_tencent_before_slow_akshare(self):
        class FakeTuShare:
            def get_stock_basic_map(self):
                return {
                    f"000{i:03d}": {
                        "symbol": f"000{i:03d}",
                        "name": f"测试{i}",
                        "industry": "测试行业",
                    }
                    for i in range(1, 601)
                }

        class FakeTencent:
            def get_realtime_quotes_batch(self, symbols):
                return {
                    symbol: {
                        "name": f"测试{index}",
                        "price": 10 + index / 100,
                        "change": 0.1,
                        "pct_change": 1.0,
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "volume": 100000,
                        "amount": 300000000,
                        "turnover_rate": 3.0,
                        "update_time": "2026-07-01 10:00:00",
                    }
                    for index, symbol in enumerate(symbols, start=1)
                }

        class SlowAKShare:
            called = False

            def get_a_share_spot_snapshot(self):
                self.called = True
                return []

        slow_akshare = SlowAKShare()
        manager = DataSourceManager(
            tushare_service=FakeTuShare(),
            tencent_service=FakeTencent(),
            akshare_service=slow_akshare,
        )

        snapshot = manager.get_a_share_snapshot()

        self.assertGreaterEqual(len(snapshot), 600)
        self.assertFalse(slow_akshare.called)
        self.assertEqual(snapshot[0]["symbol"], "000001")
        self.assertEqual(snapshot[0]["industry"], "测试行业")

    def test_search_uses_minimal_basic_map_when_remote_sources_are_unavailable(self):
        manager = DataSourceManager()

        results = manager.search_stocks("平安", limit=5)
        symbols = {item["symbol"] for item in results}

        self.assertIn("000001", symbols)
        self.assertIn("601318", symbols)

    def test_normalize_history_data_renames_source_columns_and_sorts_dates(self):
        manager = DataSourceManager()
        raw = pd.DataFrame(
            {
                "日期": ["2026-01-03", "2026-01-01", "2026-01-02"],
                "开盘": [10.2, 10.0, 10.1],
                "最高": [10.6, 10.4, 10.5],
                "最低": [9.9, 9.7, 9.8],
                "收盘": [10.3, 10.2, 10.4],
                "成交量": [1200, 1000, 1100],
                "成交额": [123000, 101000, 115000],
            }
        )

        normalized = manager._normalize_history_data(raw)

        self.assertEqual(list(normalized["date"]), ["2026-01-01", "2026-01-02", "2026-01-03"])
        for column in ("date", "open", "high", "low", "close", "volume"):
            self.assertIn(column, normalized.columns)
        self.assertEqual(normalized.loc[0, "open"], 10.0)

    def test_normalize_history_data_maps_pct_chg_and_yyyymmdd_dates(self):
        manager = DataSourceManager()
        raw = pd.DataFrame(
            {
                "date": ["20260103", "20260102"],
                "open": [10.2, 11.0],
                "high": [10.6, 11.0],
                "low": [9.9, 11.0],
                "close": [10.3, 11.0],
                "volume": [1200, 1000],
                "amount": [123000000, 200000000],
                "pct_chg": [1.2, 10.0],
            }
        )

        normalized = manager._normalize_history_data(raw)

        self.assertEqual(list(normalized["date"]), ["2026-01-02", "2026-01-03"])
        self.assertIn("pct_change", normalized.columns)
        self.assertEqual(normalized.loc[0, "pct_change"], 10.0)

    def test_normalize_money_flow_converts_wan_yuan_to_yuan(self):
        manager = DataSourceManager()

        normalized = manager._normalize_money_flow(
            {
                "main_net_inflow": 12.5,
                "super_large_net": 2,
                "large_net": 3,
                "medium_net": -1,
                "small_net": -4,
                "amount_unit": "万元",
                "control_ratio": 1.8,
                "trend": "主力流入",
                "strength": "中",
            },
            symbol="000001",
        )

        self.assertEqual(normalized["symbol"], "000001")
        self.assertEqual(normalized["main_net_inflow"], 125000.0)
        self.assertEqual(normalized["super_large_net"], 20000.0)
        self.assertEqual(normalized["large_net"], 30000.0)
        self.assertEqual(normalized["medium_net"], -10000.0)
        self.assertEqual(normalized["small_net"], -40000.0)

    def test_snapshot_marks_missing_invalid_and_reported_zero_numeric_fields(self):
        manager = DataSourceManager()

        normalized = manager._normalize_market_snapshot(
            [
                {
                    "symbol": "000001",
                    "price": 0,
                    "change": None,
                    "pct_change": "",
                    "open": "not-a-number",
                    "high": float("nan"),
                    "low": float("inf"),
                    "volume": 100,
                    "amount": 200,
                    "turnover_rate": -1.5,
                }
            ]
        )[0]

        self.assertEqual(normalized["price"], 0)
        self.assertEqual(normalized["volume"], 100)
        self.assertEqual(normalized["amount"], 200)
        self.assertEqual(normalized["turnover_rate"], -1.5)
        self.assertEqual(
            normalized["field_status"],
            {
                "price": "reported",
                "change": "missing",
                "pct_change": "missing",
                "open": "invalid",
                "high": "invalid_non_finite",
                "low": "invalid_non_finite",
                "volume": "reported",
                "amount": "reported",
                "turnover_rate": "reported",
                "pe": "missing",
                "pb": "missing",
                "total_mv": "missing",
                "circ_mv": "missing",
            },
        )
        for field in ("open", "high", "low"):
            self.assertEqual(normalized[field], 0)

    def test_tushare_tencent_snapshot_preserves_legacy_values_and_marks_omitted_fields(self):
        class FakeTuShare:
            def get_stock_basic_map(self):
                return {
                    f"{index:06}": {"name": f"测试{index}", "industry": "测试行业"}
                    for index in range(1, 501)
                }

        class FakeTencent:
            def get_realtime_quotes_batch(self, symbols):
                return {
                    symbol: {
                        "name": f"测试{index}",
                        "price": 10,
                        "change": 0.1,
                        "pct_change": 1,
                        "open": 9.9,
                        "high": 10.2,
                        "low": 9.8,
                        "volume": 100,
                        "amount": 1000,
                        "update_time": "2026-09-07 10:00:00",
                    }
                    for index, symbol in enumerate(symbols, start=1)
                }

        snapshot = DataSourceManager(
            tushare_service=FakeTuShare(), tencent_service=FakeTencent()
        ).get_a_share_snapshot()

        self.assertEqual(len(snapshot), 500)
        first = snapshot[0]
        self.assertEqual(
            {field: first[field] for field in ("price", "amount", "volume", "turnover_rate", "circ_mv")},
            {"price": 10.0, "amount": 1000.0, "volume": 100.0, "turnover_rate": 0.0, "circ_mv": 0.0},
        )
        self.assertEqual(first["field_status"]["price"], "reported")
        self.assertEqual(first["field_status"]["amount"], "reported")
        self.assertEqual(first["field_status"]["volume"], "reported")
        self.assertEqual(first["field_status"]["turnover_rate"], "missing")
        self.assertEqual(first["field_status"]["circ_mv"], "missing")


if __name__ == "__main__":
    unittest.main()
