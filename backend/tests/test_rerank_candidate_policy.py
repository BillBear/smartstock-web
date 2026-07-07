import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_candidates():
    rows = []
    for date in pd.date_range("2026-01-02", periods=6, freq="B").strftime("%Y-%m-%d"):
        for idx in range(10):
            strong = idx >= 7
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"600{idx:03d}",
                    "rank_no": idx + 1,
                    "score": 100 - idx,
                    "return_60d_rank": idx / 9,
                    "return_20d_rank": idx / 9,
                    "macd_hist": float(idx),
                    "amount_pct_rank": (9 - idx) / 9,
                    "return_10d_pct": 8 if strong else -2,
                    "strong_10d": strong,
                    "tradability_status": "tradable",
                    "incomplete_horizons": "[]",
                    "has_60d_lookback": True,
                }
            )
    return pd.DataFrame(rows)


class RerankCandidatePolicyTests(unittest.TestCase):
    def test_policy_scores_without_forward_label_leakage(self):
        from app.evaluation.rerank_candidate_policy import score_rerank_policy

        rows = pd.DataFrame(
            [
                {"symbol": "000001", "return_60d_rank": 0.9, "return_20d_rank": 0.8, "macd_hist_rank": 0.7, "return_10d_pct": -10},
                {"symbol": "000002", "return_60d_rank": 0.2, "return_20d_rank": 0.1, "macd_hist_rank": 0.1, "return_10d_pct": 20},
            ]
        )

        scored = score_rerank_policy(rows, policy_name="momentum_macd_v1")

        self.assertGreater(
            scored.loc[scored["symbol"] == "000001", "rerank_score"].iloc[0],
            scored.loc[scored["symbol"] == "000002", "rerank_score"].iloc[0],
        )
        self.assertNotIn("return_10d_pct", scored.attrs["feature_columns_used"])

    def test_run_policy_experiment_returns_policy_and_current_baselines(self):
        from app.evaluation.rerank_candidate_policy import run_rerank_policy_experiment

        summary = run_rerank_policy_experiment(make_candidates(), policies=["momentum_macd_v1"], horizon=10, train_ratio=0.5)

        self.assertEqual(summary["status"], "completed")
        self.assertFalse(summary["production_evidence"])
        self.assertIn("policy_momentum_macd_v1", summary["rules"])
        self.assertIn("current_smartstock_rank", summary["rules"])
        self.assertGreater(
            summary["rules"]["policy_momentum_macd_v1"]["test"]["top5_return_after_cost"],
            summary["rules"]["current_smartstock_rank"]["test"]["top5_return_after_cost"],
        )

    def test_cli_writes_rerank_policy_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = root / "candidate_features.csv"
            output_dir = root / "out"
            make_candidates().to_csv(candidate_path, index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_rerank_policy_experiment.py"),
                    "--candidate-features",
                    str(candidate_path),
                    "--policies",
                    "momentum_macd_v1,balanced_liquidity_v1",
                    "--output-dir",
                    str(output_dir),
                    "--horizon",
                    "10",
                    "--train-ratio",
                    "0.5",
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output_dir / "rerank_policy_experiment.json").exists())
            payload = json.loads((output_dir / "rerank_policy_experiment.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["production_evidence"])
            self.assertIn("policy_momentum_macd_v1", payload["rules"])
            self.assertIn("completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
