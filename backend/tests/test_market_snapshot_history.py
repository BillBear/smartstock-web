import tempfile
import unittest
from pathlib import Path

from app.evaluation.market_snapshot_history import MarketSnapshotHistoryProvider
from app.services.coach_store import CoachStore


class MarketSnapshotHistoryProviderTests(unittest.TestCase):
    def test_reads_explicit_history_range_from_persisted_market_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            store.save_market_snapshot(
                trade_date="2026-01-02",
                source="test",
                min_reliable_count=1,
                items=[
                    {
                        "symbol": "000001",
                        "name": "平安银行",
                        "price": 10.2,
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.9,
                        "volume": 1200000,
                        "amount": 180000000,
                        "pct_chg": 2.0,
                    },
                    {
                        "symbol": "000002",
                        "name": "万科A",
                        "price": 8.0,
                        "amount": 90000000,
                    },
                ],
            )
            store.save_market_snapshot(
                trade_date="2026-01-05",
                source="test",
                min_reliable_count=1,
                items=[
                    {
                        "symbol": "000001",
                        "name": "平安银行",
                        "price": 10.8,
                        "open": 10.3,
                        "high": 11.0,
                        "low": 10.1,
                        "volume": 1300000,
                        "amount": 210000000,
                        "pct_chg": 5.88,
                    },
                ],
            )

            provider = MarketSnapshotHistoryProvider(store=store, min_count=1)
            history = provider.get_history_data_range("000001", "2026-01-01", "2026-01-06")

            self.assertEqual(history["date"].tolist(), ["2026-01-02", "2026-01-05"])
            self.assertEqual(history["symbol"].tolist(), ["000001", "000001"])
            self.assertEqual(history["close"].tolist(), [10.2, 10.8])
            self.assertEqual(history["pct_change"].tolist(), [2.0, 5.88])
            self.assertEqual(history["amount"].tolist(), [180000000.0, 210000000.0])

    def test_falls_back_to_remote_provider_only_when_snapshot_history_missing(self):
        class Fallback:
            def __init__(self):
                self.calls = []

            def get_history_data_range(self, symbol, start_date, end_date):
                self.calls.append((symbol, start_date, end_date))
                import pandas as pd

                return pd.DataFrame([{"date": "2026-01-03", "close": 11.0}])

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CoachStore(str(Path(tmpdir) / "coach.db"))
            fallback = Fallback()
            provider = MarketSnapshotHistoryProvider(store=store, fallback=fallback, min_count=1)

            history = provider.get_history_data_range("000001", "2026-01-01", "2026-01-06")

            self.assertEqual(fallback.calls, [("000001", "2026-01-01", "2026-01-06")])
            self.assertEqual(history["date"].tolist(), ["2026-01-03"])


if __name__ == "__main__":
    unittest.main()
