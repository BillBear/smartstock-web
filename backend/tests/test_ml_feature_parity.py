from __future__ import annotations

import unittest

import numpy as np

from app.evaluation.full_market_ml.feature_contract import (
    FeatureContractError,
    SourceFreshnessError,
    build_features_as_of,
    build_full_market_feature_contract,
)
from app.services.ml_online_feature_provider import OnlineFeatureProvider
from tests.test_full_market_ml_feature_contract import feature_contract_fixture


class MLFeatureParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = feature_contract_fixture()
        self.as_of_date = str(self.rows["trade_date"].max())
        self.contract = build_full_market_feature_contract(moneyflow_coverage=0.9492)

    def test_offline_and_online_features_match_exactly_within_contract_tolerance(self):
        offline = build_features_as_of(self.rows, as_of_date=self.as_of_date, contract=self.contract)
        online = OnlineFeatureProvider(self.contract).build_features_as_of(
            self.rows,
            as_of_date=self.as_of_date,
            source_as_of_dates={
                "daily": self.as_of_date,
                "daily+adj_factor": self.as_of_date,
                "daily_basic": self.as_of_date,
                "stock_basic+trade_cal": self.as_of_date,
                "index_member_all": self.as_of_date,
            },
            source_qualities={
                source: "valid-with-rows" for source in self.contract.registered_sources
            },
        )

        self.assertEqual(offline.columns.tolist(), online.columns.tolist())
        self.assertEqual(offline[["trade_date", "symbol"]].to_dict("records"), online[["trade_date", "symbol"]].to_dict("records"))
        np.testing.assert_allclose(
            offline[list(self.contract.feature_names)].to_numpy(dtype=float),
            online[list(self.contract.feature_names)].to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-8,
            equal_nan=True,
        )

    def test_online_provider_rejects_daily_inputs_older_than_one_session(self):
        previous_sessions = sorted(self.rows["trade_date"].unique())
        stale_date = str(previous_sessions[-3])
        with self.assertRaisesRegex(SourceFreshnessError, "daily"):
            OnlineFeatureProvider(self.contract).build_features_as_of(
                self.rows,
                as_of_date=self.as_of_date,
                source_as_of_dates={
                    "daily": stale_date,
                    "daily+adj_factor": stale_date,
                    "daily_basic": self.as_of_date,
                    "stock_basic+trade_cal": self.as_of_date,
                    "index_member_all": self.as_of_date,
                },
                source_qualities={
                    source: "valid-with-rows" for source in self.contract.registered_sources
                },
            )

    def test_online_provider_requires_explicit_source_quality_provenance(self):
        with self.assertRaisesRegex(FeatureContractError, "source quality"):
            OnlineFeatureProvider(self.contract).build_features_as_of(
                self.rows,
                as_of_date=self.as_of_date,
                source_as_of_dates={source: self.as_of_date for source in self.contract.registered_sources},
                source_qualities={},
            )


if __name__ == "__main__":
    unittest.main()
