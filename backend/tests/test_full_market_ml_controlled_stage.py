from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from app.evaluation.full_market_ml.controlled_stage import run_controlled_evaluation_stage
from app.evaluation.full_market_ml.research_contract import RankingResearchContract


def _contract() -> RankingResearchContract:
    return RankingResearchContract(
        dataset_id="fixture-dataset",
        run_id="fixture-run",
        feature_blocks=(("risk_path", ("risk_feature",)),),
    )


def _baseline_rows() -> pd.DataFrame:
    rows = []
    for date_index, trade_date in enumerate(("2025-01-02", "2025-01-03", "2025-01-06")):
        for symbol_index, symbol in enumerate(("000001", "000002")):
            outcome = 0.10 if symbol_index == 0 else -0.05
            row = {
                "trade_date": trade_date,
                "symbol": symbol,
                "fold": 1,
                "quadrant": "A",
                "industry_l1": "fixture",
                "market_state": "balanced",
                "alpha_relevance_grade_10d": 4 if outcome > 0 else 0,
                "alpha_top10_10d": outcome > 0,
                "net_return_after_cost_10d": outcome,
                "mae_10d": -0.02 if outcome > 0 else -0.10,
                "severe_negative_10d": outcome < 0,
            }
            for name in (
                "adjusted_return_20d",
                "adjusted_return_60d",
                "amount_ascending",
                "amount_descending",
                "random",
                "registered_single_feature",
            ):
                row[f"score__{name}"] = float(2 - symbol_index + date_index * 0.01)
            rows.append(row)
    return pd.DataFrame(rows)


class FullMarketMLControlledStageTests(unittest.TestCase):
    def test_stage_compares_every_baseline_on_identical_raw_and_gated_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_root = root / "run"
            asset_root = root / "assets"
            baseline = _baseline_rows()
            baseline_path = run_root / "artifacts/baseline-oof/baseline_predictions.parquet"
            baseline_path.parent.mkdir(parents=True)
            baseline.to_parquet(baseline_path, index=False)
            risk = baseline[["trade_date", "symbol", "fold", "quadrant"]].copy()
            risk["risk_probability"] = [0.1, 0.9] * 3
            risk["risk_eligible"] = [True, False] * 3
            risk_path = run_root / "artifacts/risk-oof/risk_predictions.parquet"
            risk_path.parent.mkdir(parents=True)
            risk.to_parquet(risk_path, index=False)

            panel_rows = []
            for trade_date in pd.bdate_range("2025-01-02", periods=16):
                for symbol_index, symbol in enumerate(("000001", "000002")):
                    panel_rows.append(
                        {
                            "trade_date": trade_date.strftime("%Y-%m-%d"),
                            "symbol": symbol,
                            "adjusted_open": 100.0,
                            "adjusted_close": 101.0 if symbol_index == 0 else 99.0,
                            "is_suspended": False,
                            "at_up_limit_open": False,
                            "mfe_10d": 0.12 if symbol_index == 0 else 0.01,
                            "mae_10d": -0.02 if symbol_index == 0 else -0.10,
                            "future_limit_up_count_10d": 0,
                            "future_limit_down_count_10d": 0,
                            "tp_before_sl_10d": symbol_index == 0,
                            "sl_before_tp_10d": symbol_index == 1,
                            "total_mv": 1_000_000 + symbol_index,
                        }
                    )
            panel_path = (
                asset_root
                / "datasets/fixture-dataset/artifacts/full-build/dataset-v3/shard=00/data.parquet"
            )
            panel_path.parent.mkdir(parents=True)
            pd.DataFrame(panel_rows).to_parquet(panel_path, index=False)

            artifacts = run_controlled_evaluation_stage(_contract(), run_root, asset_root)
            report = json.loads(Path(artifacts["controlled_report"]).read_text(encoding="utf-8"))

            self.assertFalse(report["alpha_model_available"])
            self.assertEqual(set(report["comparisons"]["A"]), set(_contract().required_baselines))
            for comparison in report["comparisons"]["A"].values():
                self.assertEqual(comparison["raw"]["date_count"], 3)
                self.assertEqual(comparison["same_risk_gated"]["date_count"], 3)
            self.assertGreater(report["portfolios"]["A"]["amount_descending"]["raw"]["opened_trade_count"], 0)
            self.assertTrue(Path(artifacts["equity_curves"]).is_file())

    def test_stage_rejects_risk_predictions_with_different_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "run/artifacts/baseline-oof/baseline_predictions.parquet"
            baseline_path.parent.mkdir(parents=True)
            _baseline_rows().to_parquet(baseline_path, index=False)
            risk_path = root / "run/artifacts/risk-oof/risk_predictions.parquet"
            risk_path.parent.mkdir(parents=True)
            risk = _baseline_rows()[["trade_date", "symbol", "fold", "quadrant"]].iloc[:-1].copy()
            risk["risk_probability"] = 0.2
            risk["risk_eligible"] = True
            risk.to_parquet(risk_path, index=False)

            with self.assertRaisesRegex(ValueError, "identical OOF rows"):
                run_controlled_evaluation_stage(_contract(), root / "run", root / "assets")


if __name__ == "__main__":
    unittest.main()
