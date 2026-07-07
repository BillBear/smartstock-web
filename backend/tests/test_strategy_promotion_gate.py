import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StrategyPromotionGateTests(unittest.TestCase):
    def test_blocks_when_sample_too_small_even_if_return_is_high(self):
        from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

        result = evaluate_promotion_gate(
            {
                "complete_label_date_count": 13,
                "test_precision_at_5": 0.7,
                "test_top5_return_after_cost": 12,
                "baseline_top5_return_after_cost": 2,
                "closed_roundtrip_count": 0,
                "ml_v2_2_training_allowed": False,
                "ml_decision": "prefer_rule_baseline_over_ml_for_now",
            }
        )

        self.assertFalse(result["passed"])
        self.assertIn("complete_label_date_count_below_30", result["blocking_reasons"])
        self.assertIn("closed_roundtrip_count_below_required", result["blocking_reasons"])
        self.assertIn("ml_v2_2_training_not_allowed", result["blocking_reasons"])
        self.assertIn("ml_prefer_rule_baseline_over_ml", result["blocking_reasons"])

    def test_blocks_ml_even_when_rerank_metrics_pass(self):
        from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

        result = evaluate_promotion_gate(
            {
                "complete_label_date_count": 45,
                "test_precision_at_5": 0.66,
                "test_top5_return_after_cost": 5,
                "baseline_top5_return_after_cost": 2,
                "closed_roundtrip_count": 30,
                "max_drawdown_not_worse_than_baseline": True,
                "market_state_fail_count": 0,
                "ml_v2_2_training_allowed": False,
                "ml_decision": "prefer_rule_baseline_over_ml_for_now",
            }
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["production_action"], "do_not_change_strategy")

    def test_passes_only_when_all_gates_pass(self):
        from app.evaluation.strategy_promotion_gate import evaluate_promotion_gate

        result = evaluate_promotion_gate(
            {
                "complete_label_date_count": 45,
                "test_precision_at_5": 0.62,
                "test_top5_return_after_cost": 5,
                "baseline_top5_return_after_cost": 2,
                "closed_roundtrip_count": 30,
                "max_drawdown_not_worse_than_baseline": True,
                "market_state_fail_count": 0,
                "ml_v2_2_training_allowed": True,
                "ml_decision": "ml_or_rule_policy_beats_required_baseline",
            }
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["production_action"], "allow_strategy_change_plan")

    def test_cli_writes_gate_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metrics_path = root / "metrics.json"
            output_path = root / "gate.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "complete_label_date_count": 13,
                        "test_precision_at_5": 0.7,
                        "test_top5_return_after_cost": 12,
                        "baseline_top5_return_after_cost": 2,
                        "closed_roundtrip_count": 0,
                        "ml_v2_2_training_allowed": False,
                        "ml_decision": "prefer_rule_baseline_over_ml_for_now",
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "run_strategy_promotion_gate.py"),
                    "--metrics-json",
                    str(metrics_path),
                    "--output-json",
                    str(output_path),
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["passed"])
            self.assertIn("completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
