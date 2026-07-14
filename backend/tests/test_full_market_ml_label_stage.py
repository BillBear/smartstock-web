from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
import tempfile

import pandas as pd

from app.evaluation.full_market_ml.label_stage import build_ranking_label_input, validate_dataset_registry
from app.evaluation.full_market_ml.research_contract import RankingResearchContract


def contract() -> RankingResearchContract:
    return RankingResearchContract(
        dataset_id="fixture",
        run_id="fixture-run",
        feature_blocks=(("momentum", ("adjusted_return_20d",)),),
    )


class FullMarketMLLabelStageTests(unittest.TestCase):
    def test_stage_recomputes_contract_eligibility_and_execution_costs(self):
        rows = pd.DataFrame(
            {
                "trade_date": ["2025-01-02", "2025-01-02"],
                "symbol": ["000001", "000002"],
                "industry_l1": ["A", "A"],
                "listing_age_trade_days": [119, 120],
                "valid_ohlc": [True, True],
                "is_st": [False, False],
                "is_suspended": [False, False],
                "median_amount_20d": [100.0, 100.0],
                "entry_tradeable": [True, True],
                "horizon_available_10d": [True, True],
                "entry_price": [10.0, 10.0],
                "exit_price": [11.0, 11.0],
                "mae_10d": [-0.02, -0.02],
                "sl_before_tp_10d": [False, False],
                "future_limit_down_count_10d": [0, 0],
            }
        )

        prepared = build_ranking_label_input(rows, contract())

        self.assertEqual(prepared["eligible_for_training"].tolist(), [False, True])
        expected = ((11.0 * (1 - 0.001)) / (10.0 * (1 + 0.001))) * (1 - 0.0003) ** 2 - 1
        self.assertAlmostEqual(prepared.loc[1, "net_return_after_cost_10d"], expected)

    def test_stage_rejects_missing_path_or_execution_columns(self):
        with self.assertRaisesRegex(ValueError, "label stage rows missing columns"):
            build_ranking_label_input(pd.DataFrame({"trade_date": ["2025-01-02"]}), contract())

    def test_dataset_registry_must_match_frozen_contract_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "datasets" / "fixture" / "artifacts" / "full-build" / "dataset_registry_v3.json"
            registry.parent.mkdir(parents=True)
            registry.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "dataset registry hash"):
                validate_dataset_registry(root, replace(contract(), dataset_registry_sha256="a" * 64))


if __name__ == "__main__":
    unittest.main()
