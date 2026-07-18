from __future__ import annotations

import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from app.evaluation.full_market_ml.market_industry_features import (
    INDUSTRY_FEATURE_NAMES,
    MARKET_FEATURE_NAMES,
    build_industry_state_features,
    build_market_state_features,
)


def state_fixture() -> pd.DataFrame:
    rows = []
    for date_index, date in enumerate(("2025-01-02", "2025-01-03")):
        for index, (symbol, industry) in enumerate((("000001", "bank"), ("000002", "bank"), ("000003", "tech"), ("000004", "tech"))):
            rows.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "industry_l1": industry,
                    "adjusted_return_1d": 0.01 * (index - 1),
                    "adjusted_return_5d": 0.02 * index + date_index * 0.001,
                    "adjusted_return_20d": 0.03 * index,
                    "price_to_sma_20d": 0.01 if index % 2 == 0 else -0.01,
                    "amount_ratio_5d": 1.0 + index * 0.1,
                    "turnover_rate": 2.0 + index,
                    "total_mv": 100.0 * (index + 1),
                    "at_up_limit": index == 3,
                    "at_down_limit": index == 0,
                }
            )
    return pd.DataFrame(rows)


class FullMarketMLMarketIndustryFeatureTests(unittest.TestCase):
    def test_market_features_have_one_value_per_trade_date(self):
        output = build_market_state_features(state_fixture())

        self.assertLessEqual(
            int(output.groupby("trade_date")[list(MARKET_FEATURE_NAMES)].nunique(dropna=True).max().max()),
            1,
        )

    def test_industry_strength_is_ranked_across_industries_not_within_industry(self):
        output = build_industry_state_features(state_fixture())
        day = output[output["trade_date"].eq("2025-01-02")]

        self.assertEqual(day.groupby("industry_l1")["industry_strength_rank_5d"].nunique().max(), 1)
        self.assertGreater(
            day.loc[day["industry_l1"].eq("tech"), "industry_strength_rank_5d"].iloc[0],
            day.loc[day["industry_l1"].eq("bank"), "industry_strength_rank_5d"].iloc[0],
        )

    def test_industry_features_are_recomputed_when_prior_date_columns_exist(self):
        rows = state_fixture()
        for name in INDUSTRY_FEATURE_NAMES:
            rows[name] = pd.NA

        output = build_industry_state_features(rows)

        self.assertTrue(set(INDUSTRY_FEATURE_NAMES).issubset(output.columns))
        self.assertFalse(output["industry_signal_return_median_5d"].isna().all())
        self.assertFalse(any(name.endswith("_x") or name.endswith("_y") for name in output.columns))

    def test_future_mutation_does_not_change_prior_signal_features(self):
        before = state_fixture()
        after = before.copy()
        after.loc[after["trade_date"].eq("2025-01-03"), "adjusted_return_5d"] = 99.0

        left = build_market_state_features(before).query("trade_date == '2025-01-02'").reset_index(drop=True)
        right = build_market_state_features(after).query("trade_date == '2025-01-02'").reset_index(drop=True)

        assert_frame_equal(left, right)


if __name__ == "__main__":
    unittest.main()
