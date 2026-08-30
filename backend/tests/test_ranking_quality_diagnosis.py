import unittest
from pathlib import Path
import subprocess
import sys

import pandas as pd

from app.evaluation.ranking_quality_diagnosis import (
    build_ranking_quality_diagnosis,
    label_snapshot_rows,
)


class RankingQualityDiagnosisTests(unittest.TestCase):
    def test_cli_is_directly_runnable_from_backend_directory(self):
        backend_dir = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/analyze_ranking_quality.py", "--help"],
            cwd=backend_dir,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--database-url", result.stdout)

    def test_labels_use_first_post_snapshot_bar_and_apply_round_trip_costs(self):
        snapshots = [
            {
                "trade_date": "2026-07-01",
                "symbol": "000001",
                "name": "平安银行",
                "rank_no": 1,
                "action": "buy",
                "decision": {"executable": True},
                "score_breakdown": {"raw_total": 80, "total": 82},
                "up_prob": 0.7,
                "dd_prob": 0.2,
            }
        ]
        history = pd.DataFrame(
            [
                {"date": "2026-07-01", "open": 9.0, "high": 9.2, "low": 8.9, "close": 9.1, "volume": 1, "amount": 10},
                {"date": "2026-07-02", "open": 10.0, "high": 12.0, "low": 9.5, "close": 11.0, "volume": 1, "amount": 10},
                {"date": "2026-07-03", "open": 11.0, "high": 12.5, "low": 10.5, "close": 12.0, "volume": 1, "amount": 10},
                {"date": "2026-07-06", "open": 12.0, "high": 13.0, "low": 11.5, "close": 12.5, "volume": 1, "amount": 10},
            ]
        )

        rows, coverage = label_snapshot_rows(
            snapshots,
            history_fetcher=lambda symbol, start, end: (history, "fixture"),
            execution_config={"commission": 0.001, "slippage": 0.001, "take_profit_pct": 15.0, "stop_loss_pct": 8.0},
        )

        self.assertEqual(coverage["source_counts"], {"fixture": 1})
        self.assertEqual(rows[0]["entry_date"], "2026-07-02")
        self.assertAlmostEqual(rows[0]["entry_price"], 10.0)
        self.assertAlmostEqual(rows[0]["future_return_3d"], 24.500998, places=6)
        self.assertTrue(rows[0]["first_hit_take_profit"])
        self.assertFalse(rows[0]["first_hit_stop_loss"])
        self.assertEqual(rows[0]["tradable_label"], "tradable")

    def test_diagnosis_marks_no_model_counterfactual_unavailable_and_finds_ranking_errors(self):
        rows = [
            {
                "trade_date": "2026-07-01",
                "symbol": "000001",
                "name": "Top loser",
                "rank_no": 1,
                "future_return_10d": -12.0,
                "future_return_5d": -5.0,
                "future_return_20d": -10.0,
                "tradable_label": "tradable",
                "decision_executable": True,
                "raw_total": 90.0,
                "total": 90.0,
                "up_prob": 0.8,
                "dd_prob": 0.2,
            },
            {
                "trade_date": "2026-07-01",
                "symbol": "000002",
                "name": "Late winner",
                "rank_no": 12,
                "future_return_10d": 22.0,
                "future_return_5d": 10.0,
                "future_return_20d": 25.0,
                "tradable_label": "tradable",
                "decision_executable": False,
                "raw_total": 70.0,
                "total": 70.0,
                "up_prob": 0.6,
                "dd_prob": 0.1,
            },
        ]

        diagnosis = build_ranking_quality_diagnosis(rows)

        self.assertEqual(diagnosis["error_samples"]["top5_worst_10d"][0]["symbol"], "000001")
        self.assertEqual(diagnosis["error_samples"]["rank_gt_10_best_10d"][0]["symbol"], "000002")
        self.assertEqual(diagnosis["counterfactual"]["no_model_rule_rank"]["status"], "unavailable")
        self.assertIn("pre_model_rule_score", diagnosis["counterfactual"]["no_model_rule_rank"]["missing_fields"])
        self.assertEqual(diagnosis["funnel_assessment"]["recall"]["finding"], "暂无证据")


if __name__ == "__main__":
    unittest.main()
