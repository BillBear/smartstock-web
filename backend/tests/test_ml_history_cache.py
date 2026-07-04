import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.evaluation.ml_history_cache import MLHistoryCache


class FakeHistorySource:
    def __init__(self, frame=None, fail_symbols=None):
        self.frame = frame if frame is not None else pd.DataFrame()
        self.fail_symbols = set(fail_symbols or [])
        self.calls = []

    def get_history_data_range(self, symbol, start_date, end_date):
        self.calls.append((symbol, start_date, end_date))
        if symbol in self.fail_symbols:
            raise RuntimeError("source failed")
        return self.frame.copy()


def make_history():
    return pd.DataFrame(
        [
            {"date": "2026-05-31", "open": 9, "close": 9, "high": 9, "low": 9, "volume": 1, "amount": 1},
            {"date": "2026-06-01", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 2, "amount": 3},
            {"date": "2026-06-02", "open": 11, "close": 12, "high": 13, "low": 10, "volume": 4, "amount": 5},
            {"date": "2026-06-03", "open": 12, "close": 13, "high": 14, "low": 11, "volume": 6, "amount": 7},
            {"date": "2026-06-04", "open": 13, "close": 14, "high": 15, "low": 12, "volume": 8, "amount": 9},
        ]
    )


class MLHistoryCacheTests(unittest.TestCase):
    def test_cache_reuses_symbol_history_without_second_remote_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeHistorySource(make_history())
            cache = MLHistoryCache(source, cache_root=tmp, retry_count=0, prefer_parquet=False)

            first = cache.get_history_data_range("002415", "2026-06-01", "2026-06-03")
            second = cache.get_history_data_range("002415", "2026-06-01", "2026-06-03")

            self.assertEqual(len(first), 3)
            self.assertEqual(len(second), 3)
            self.assertEqual(len(source.calls), 1)
            self.assertEqual(cache.manifest()["cache_hits"], 1)

    @unittest.skipIf(importlib.util.find_spec("pyarrow") is None, "pyarrow not installed")
    def test_cache_uses_parquet_when_pyarrow_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeHistorySource(make_history())
            cache = MLHistoryCache(source, cache_root=tmp, retry_count=0, prefer_parquet=True)

            cache.get_history_data_range("002415", "2026-06-01", "2026-06-03")

            self.assertTrue(list(Path(tmp).glob("*.parquet")))
            self.assertEqual(cache.manifest()["format"], "parquet")

    def test_cache_can_fallback_to_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = FakeHistorySource(make_history())
            cache = MLHistoryCache(source, cache_root=tmp, retry_count=0, prefer_parquet=False)

            cache.get_history_data_range("002415", "2026-06-01", "2026-06-03")

            self.assertTrue(list(Path(tmp).glob("*.csv")))
            self.assertEqual(cache.manifest()["format"], "csv")

    def test_failed_symbols_are_recorded_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = MLHistoryCache(FakeHistorySource(make_history(), fail_symbols={"002415"}), cache_root=tmp, retry_count=0)

            result = cache.fetch_many(["002415"], "2026-06-01", "2026-06-03", workers=1)

            self.assertEqual(result["valid_symbols"], [])
            self.assertEqual(cache.manifest()["failed_symbols"][0]["symbol"], "002415")

    def test_cache_filters_to_explicit_requested_date_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = MLHistoryCache(FakeHistorySource(make_history()), cache_root=tmp, retry_count=0, prefer_parquet=False)

            result = cache.get_history_data_range("002415", "2026-06-02", "2026-06-03")

            self.assertEqual(result["date"].tolist(), ["2026-06-02", "2026-06-03"])


if __name__ == "__main__":
    unittest.main()
