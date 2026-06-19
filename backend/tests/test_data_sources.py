import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.data_source_manager import DataSourceManager


class DataSourceManagerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
