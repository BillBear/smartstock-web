"""Online adapter for the frozen full-market research feature contract.

This provider is intentionally not wired into CoachService yet.  It exists to
prove parity before a future, separately-approved production integration.
"""
from __future__ import annotations

from typing import Mapping

import pandas as pd

from app.evaluation.full_market_ml.feature_contract import (
    FeatureContract,
    build_features_as_of,
    validate_online_provenance,
)


class OnlineFeatureProvider:
    def __init__(self, contract: FeatureContract):
        self.contract = contract

    def build_features_as_of(
        self,
        rows: pd.DataFrame,
        *,
        as_of_date: str,
        source_as_of_dates: Mapping[str, str],
        source_qualities: Mapping[str, str],
    ) -> pd.DataFrame:
        validate_online_provenance(
            rows,
            as_of_date=as_of_date,
            contract=self.contract,
            source_as_of_dates=source_as_of_dates,
            source_qualities=source_qualities,
        )
        return build_features_as_of(rows, as_of_date=as_of_date, contract=self.contract)
