import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.ml_dataset_builder import MLDatasetBuilder


class MLDataSourceStub:
    def get_a_share_snapshot(self):
        rows = []
        for idx in range(1600):
            if idx < 600:
                symbol = f"60{idx:04d}"
            elif idx < 1100:
                symbol = f"00{idx - 600:04d}"
            else:
                symbol = f"30{idx - 1100:04d}"
            rows.append(
                {
                    "symbol": symbol,
                    "name": f"样本{idx}",
                    "price": 10.0,
                    "amount": 1600 - idx,
                }
            )
        return rows

    def get_history_data(self, symbol, days=260):
        return pd.DataFrame()


class MLDatasetBuilderTests(unittest.TestCase):
    def test_build_dataset_allows_full_market_symbol_targets_above_legacy_300_cap(self):
        builder = MLDatasetBuilder(MLDataSourceStub())

        dataset = builder.build_dataset(
            {
                "train_start": "2024-01-01",
                "train_end": "2026-01-01",
                "max_symbols": 1500,
            }
        )

        self.assertEqual(dataset["meta"]["symbol_count"], 1500)
        self.assertEqual(dataset["meta"]["valid_symbol_count"], 0)
        self.assertEqual(dataset["meta"]["sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
