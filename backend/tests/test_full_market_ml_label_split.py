from __future__ import annotations

import unittest

import pandas as pd

from app.evaluation.full_market_ml.label_split import add_return_only_labels
from tests.test_full_market_ml_collector import FullMarketMLTestCase


def return_label_fixture() -> pd.DataFrame:
    rows = []
    for index in range(20):
        rows.append(
            {
                "trade_date": "2025-01-02",
                "symbol": f"{index + 1:06d}",
                "eligible_for_training": True,
                "net_return_after_cost_10d": 0.20 - index * 0.02,
                "sl_before_tp_10d": index == 0,
                "label_severe_negative_10d": index == 0,
                "relevance_grade_10d": 0 if index == 0 else 1,
            }
        )
    return pd.DataFrame(rows)


class FullMarketMLLabelSplitTests(FullMarketMLTestCase):
    def test_return_only_label_uses_costed_return_rank_without_path_override(self):
        labeled = add_return_only_labels(return_label_fixture())

        top = labeled.iloc[0]
        tenth_percent = labeled.iloc[1]
        twentieth_percent = labeled.iloc[3]
        positive_outside_top_twenty = labeled.iloc[5]
        negative = labeled.iloc[-1]

        self.assertEqual(top["return_relevance_grade_10d"], 4)
        self.assertTrue(top["label_return_top10_10d"])
        self.assertTrue(top["sl_before_tp_10d"])
        self.assertEqual(top["relevance_grade_10d"], 0)
        self.assertEqual(tenth_percent["return_relevance_grade_10d"], 3)
        self.assertEqual(twentieth_percent["return_relevance_grade_10d"], 2)
        self.assertEqual(positive_outside_top_twenty["return_relevance_grade_10d"], 1)
        self.assertEqual(negative["return_relevance_grade_10d"], 0)

    def test_return_only_label_leaves_unavailable_or_ineligible_outcomes_null(self):
        rows = pd.DataFrame(
            [
                {
                    "trade_date": "2025-01-02",
                    "symbol": "000001",
                    "eligible_for_training": True,
                    "net_return_after_cost_10d": None,
                },
                {
                    "trade_date": "2025-01-02",
                    "symbol": "000002",
                    "eligible_for_training": False,
                    "net_return_after_cost_10d": 0.15,
                },
                {
                    "trade_date": "2025-01-02",
                    "symbol": "000003",
                    "eligible_for_training": True,
                    "net_return_after_cost_10d": 0.10,
                },
            ]
        )

        labeled = add_return_only_labels(rows)

        self.assertTrue(pd.isna(labeled.loc[0, "return_relevance_grade_10d"]))
        self.assertTrue(pd.isna(labeled.loc[1, "return_relevance_grade_10d"]))
        self.assertFalse(labeled.loc[0, "label_return_top10_10d"])
        self.assertFalse(labeled.loc[1, "label_return_top10_10d"])
        self.assertFalse(pd.isna(labeled.loc[2, "return_relevance_grade_10d"]))
