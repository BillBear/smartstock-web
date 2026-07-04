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


class MLHistoryDataSourceStub(MLDataSourceStub):
    def get_a_share_snapshot(self):
        return [
            {"symbol": f"600{idx:03d}", "name": f"样本{idx}", "price": 10.0, "amount": 1000 - idx}
            for idx in range(12)
        ]

    def get_history_data(self, symbol, days=260):
        dates = pd.date_range(start="2024-01-01", periods=140, freq="D")
        return pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "close": [10.0 + idx * 0.01 for idx in range(len(dates))],
            }
        )


class MLExplicitRangeDataSourceStub(MLDataSourceStub):
    def __init__(self):
        self.range_calls = []

    def get_a_share_snapshot(self):
        return [
            {"symbol": "600001", "name": "样本1", "price": 10.0, "amount": 1000},
            {"symbol": "600002", "name": "样本2", "price": 10.0, "amount": 900},
        ]

    def get_history_data_range(self, symbol, start_date, end_date):
        self.range_calls.append((symbol, start_date, end_date))
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
        return pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "close": [10.0 + idx * 0.01 for idx in range(len(dates))],
            }
        )

    def get_history_data(self, symbol, days=260):
        raise AssertionError("ML dataset builder must prefer explicit history ranges when available")


class MLFeatureBuilderStub:
    FEATURE_NAMES = ["feature"]

    def build_feature_frame(self, history, market_state=None, news_factor=None):
        return pd.DataFrame(
            {
                "date": history["date"],
                "feature": range(len(history)),
            }
        )

    def add_forward_labels(self, features, horizon_days=15, target_return_pct=8.0, drawdown_pct=6.0):
        labeled = features.copy()
        labeled["future_return_pct"] = 1.0
        labeled["future_max_drawdown_pct"] = -1.0
        labeled["label_up"] = 1
        labeled["label_dd"] = 0
        labeled["label_risk_adjusted_return"] = 1.0
        return labeled


class MLLocalFeatureBuilderStub:
    FEATURE_NAMES = ["feature", "news_total_score", "market_state_score"]

    def build_feature_frame(self, history, market_state=None, news_factor=None):
        return pd.DataFrame(
            {
                "date": history["date"],
                "feature": range(len(history)),
                "news_total_score": 50.0,
                "market_state_score": 50.0,
            }
        )

    def add_forward_labels(self, features, horizon_days=15, target_return_pct=8.0, drawdown_pct=6.0):
        labeled = features.copy()
        labeled["future_return_pct"] = 1.0
        labeled["future_max_drawdown_pct"] = -1.0
        labeled["label_up"] = 1
        labeled["label_dd"] = 0
        labeled["label_risk_adjusted_return"] = 1.0
        return labeled


class MLCachedHistorySourceStub:
    def __init__(self):
        self.range_calls = []

    def get_history_data_range(self, symbol, start_date, end_date):
        self.range_calls.append((symbol, start_date, end_date))
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
        return pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "close": [10.0 + idx * 0.01 for idx in range(len(dates))],
            }
        )


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

    def test_successful_dataset_meta_includes_three_layer_split_plan(self):
        builder = MLDatasetBuilder(MLHistoryDataSourceStub(), feature_builder=MLFeatureBuilderStub())

        dataset = builder.build_dataset(
            {
                "train_start": "2024-01-01",
                "train_end": "2024-05-19",
                "max_symbols": 10,
                "sample_step": 10,
                "final_time_holdout_months": 1,
                "stock_holdout_ratio": 0.2,
                "walk_forward_splits": 3,
            }
        )

        split_plan = dataset["meta"]["split_plan"]
        self.assertEqual(split_plan["method"], "walk_forward_plus_final_time_and_stock_holdout")
        self.assertEqual(split_plan["stock_holdout"]["symbol_count"], 2)
        self.assertGreaterEqual(split_plan["final_holdout"]["date_count"], 1)
        self.assertTrue(set(split_plan["training_dates"]).isdisjoint(split_plan["final_holdout"]["dates"]))
        self.assertTrue(set(split_plan["training_symbols"]).isdisjoint(split_plan["stock_holdout"]["symbols"]))
        self.assertGreaterEqual(split_plan["walk_forward"]["split_count"], 1)

    def test_dataset_uses_explicit_history_range_for_train_window(self):
        source = MLExplicitRangeDataSourceStub()
        builder = MLDatasetBuilder(source, feature_builder=MLFeatureBuilderStub())

        dataset = builder.build_dataset(
            {
                "train_start": "2024-03-01",
                "train_end": "2024-04-30",
                "max_symbols": 2,
                "horizon_days": 5,
                "sample_step": 10,
                "feature_warmup_calendar_days": 30,
                "label_lookahead_calendar_days": 20,
            }
        )

        self.assertEqual(
            source.range_calls,
            [
                ("600001", "2024-01-31", "2024-05-20"),
                ("600002", "2024-01-31", "2024-05-20"),
            ],
        )
        self.assertEqual(dataset["meta"]["history_source"], "explicit_history_range")
        self.assertEqual(dataset["meta"]["history_start"], "2024-01-31")
        self.assertEqual(dataset["meta"]["history_end"], "2024-05-20")

    def test_dataset_can_use_injected_cached_history_source(self):
        cached_source = MLCachedHistorySourceStub()
        builder = MLDatasetBuilder(MLExplicitRangeDataSourceStub(), feature_builder=MLFeatureBuilderStub())

        dataset = builder.build_dataset(
            {
                "train_start": "2024-03-01",
                "train_end": "2024-04-30",
                "symbols": ["600001"],
                "history_source": cached_source,
                "sample_step": 10,
                "feature_warmup_calendar_days": 30,
                "label_lookahead_calendar_days": 20,
            }
        )

        self.assertEqual(cached_source.range_calls, [("600001", "2024-01-31", "2024-05-20")])
        self.assertEqual(dataset["meta"]["history_source"], "injected_history_source")
        self.assertGreater(dataset["meta"]["sample_count"], 0)

    def test_dataset_can_exclude_news_and_market_state_features(self):
        builder = MLDatasetBuilder(MLExplicitRangeDataSourceStub(), feature_builder=MLLocalFeatureBuilderStub())

        dataset = builder.build_dataset(
            {
                "train_start": "2024-03-01",
                "train_end": "2024-04-30",
                "symbols": ["600001"],
                "exclude_feature_names": ["news_total_score", "market_state_score"],
                "sample_step": 10,
                "feature_warmup_calendar_days": 30,
                "label_lookahead_calendar_days": 20,
            }
        )

        self.assertEqual(dataset["feature_names"], ["feature"])
        self.assertNotIn("news_total_score", dataset["df"].columns)
        self.assertNotIn("market_state_score", dataset["df"].columns)

    def test_dataset_can_skip_large_samples_payload(self):
        builder = MLDatasetBuilder(MLExplicitRangeDataSourceStub(), feature_builder=MLFeatureBuilderStub())

        dataset = builder.build_dataset(
            {
                "train_start": "2024-03-01",
                "train_end": "2024-04-30",
                "symbols": ["600001"],
                "include_samples": False,
                "sample_step": 10,
                "feature_warmup_calendar_days": 30,
                "label_lookahead_calendar_days": 20,
            }
        )

        self.assertEqual(dataset["samples"], [])
        self.assertGreater(dataset["meta"]["sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
