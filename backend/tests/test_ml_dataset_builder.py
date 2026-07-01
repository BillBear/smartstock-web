import unittest

from app.services.ml_dataset_builder import MLDatasetBuilder


class FakeDataSource:
    def get_a_share_snapshot(self):
        return [
            {
                "symbol": f"{index:06d}",
                "name": f"股票{index}",
                "amount": 10_000_000_000 - index,
                "price": 10.0,
            }
            for index in range(1, 1601)
        ]

    def get_history_data(self, symbol, days=260):
        return None


class MLDatasetBuilderTests(unittest.TestCase):
    def test_default_symbol_selection_uses_expanded_full_market_sample(self):
        builder = MLDatasetBuilder(FakeDataSource())

        symbols = builder.select_symbols()

        self.assertEqual(len(symbols), 1500)
        self.assertEqual(symbols[0]["symbol"], "000001")

    def test_empty_dataset_still_reports_minimum_training_standard(self):
        builder = MLDatasetBuilder(FakeDataSource())

        dataset = builder.build_dataset({"max_symbols": 1500, "train_start": "2024-01-01", "train_end": "2026-01-01"})

        standard = dataset["meta"]["minimum_training_standard"]
        self.assertFalse(standard["passed"])
        self.assertEqual(standard["min_symbols"], 1500)
        self.assertGreaterEqual(standard["min_history_days"], 730)


if __name__ == "__main__":
    unittest.main()
