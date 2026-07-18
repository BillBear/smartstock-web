from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.evaluation.full_market_ml.feature_contract import (
    FeatureContractError,
    assert_contract_coverage,
    build_full_market_feature_contract,
    build_features_as_of,
)
from app.evaluation.full_market_ml.feature_stage import build_registered_feature_matrix


def feature_contract_fixture(*, sessions: int = 84, symbols: int = 5) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol_index in range(symbols):
        symbol = f"{symbol_index + 1:06d}"
        for offset, trade_date in enumerate(pd.bdate_range("2025-01-02", periods=sessions)):
            close = 10.0 + symbol_index + offset * (0.04 + symbol_index * 0.006)
            volume = 1_000_000 + symbol_index * 100_000 + offset * 1_500
            rows.append(
                {
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "symbol": symbol,
                    "adjusted_open": close * 0.995,
                    "adjusted_high": close * 1.016,
                    "adjusted_low": close * 0.984,
                    "adjusted_close": close,
                    "volume_shares": volume,
                    "amount_cny": close * volume,
                    "turnover_rate": 1.5 + symbol_index * 0.3 + (offset % 4) * 0.05,
                    "total_mv": 8_000_000_000 + symbol_index * 900_000_000,
                    "circ_mv": 6_000_000_000 + symbol_index * 700_000_000,
                    "pe": 10.0 + symbol_index,
                    "pb": 1.0 + symbol_index * 0.1,
                    "ps": 2.0 + symbol_index * 0.1,
                    "industry_l1": "Industry A" if symbol_index % 2 == 0 else "Industry B",
                    "listing_age_trade_days": 300 + offset,
                    "valid_ohlc": True,
                }
            )
    return pd.DataFrame(rows)


class FullMarketFeatureContractTests(unittest.TestCase):
    def test_contract_excludes_news_and_disables_low_coverage_moneyflow(self):
        contract = build_full_market_feature_contract(moneyflow_coverage=0.9492)

        self.assertIn("moneyflow", contract.disabled_groups)
        self.assertTrue(all("news" not in feature.name for feature in contract.features))
        self.assertTrue(all("moneyflow" not in feature.group for feature in contract.features))
        self.assertGreaterEqual(len(contract.required_feature_names), 60)
        self.assertEqual(contract.sha256(), build_full_market_feature_contract(moneyflow_coverage=0.9492).sha256())

    def test_contract_rejects_insufficient_observed_moneyflow_coverage(self):
        with self.assertRaisesRegex(FeatureContractError, "moneyflow coverage"):
            build_full_market_feature_contract(
                moneyflow_coverage=0.94,
                include_moneyflow=True,
            )

    def test_core_feature_coverage_is_checked_for_every_fold(self):
        rows = feature_contract_fixture()
        as_of_date = str(rows["trade_date"].max())
        contract = build_full_market_feature_contract(moneyflow_coverage=0.9492)
        matrix = build_features_as_of(rows, as_of_date=as_of_date, contract=contract)
        result = assert_contract_coverage(matrix, contract, folds={"fold-1": (as_of_date,)})

        self.assertTrue(result.passed)
        broken = matrix.copy()
        broken.loc[broken.index[:2], "adjusted_return_20d"] = np.nan
        with self.assertRaisesRegex(FeatureContractError, "adjusted_return_20d"):
            assert_contract_coverage(broken, contract, folds={"fold-1": (as_of_date,)})

    def test_feature_stage_rejects_features_outside_the_registered_contract(self):
        contract = build_full_market_feature_contract(moneyflow_coverage=0.9492)
        with self.assertRaisesRegex(FeatureContractError, "unregistered"):
            build_registered_feature_matrix(
                feature_contract_fixture(),
                ("news_total_score",),
                contract=contract,
            )


if __name__ == "__main__":
    unittest.main()
