import unittest

from app.evaluation.production_gate import evaluate_ranking_production_gate


def _summary(**overrides):
    payload = {
        "coverage": {"coverage_status": "complete"},
        "metrics": {
            "precision_at_3": 0.7,
            "precision_at_5": 0.62,
            "top_5_avg_return_pct": 3.4,
            "max_drawdown": 0.08,
        },
        "benchmarks": {
            "market_median_return_pct": 1.2,
            "baseline_top_5_avg_return_pct": 1.8,
            "baseline_max_drawdown": 0.1,
        },
        "market_state_validation": {
            "validated_state_count": 3,
            "failed_state_count": 0,
        },
        "holdout_validation": {
            "recent_holdout_precision_at_5": 0.55,
            "walk_forward_precision_at_5": 0.62,
        },
    }
    payload.update(overrides)
    return payload


class ProductionReadinessGateTests(unittest.TestCase):
    def test_passes_when_all_minimum_requirements_are_met(self):
        gate = evaluate_ranking_production_gate(_summary())

        self.assertTrue(gate["ready"])
        self.assertEqual(gate["status"], "passed")
        self.assertEqual(gate["failed_checks"], [])

    def test_fails_when_precision_is_below_threshold(self):
        gate = evaluate_ranking_production_gate(
            _summary(metrics={"precision_at_3": 0.61, "precision_at_5": 0.62, "top_5_avg_return_pct": 3.4, "max_drawdown": 0.08})
        )

        self.assertFalse(gate["ready"])
        self.assertIn("precision_at_3", {item["key"] for item in gate["failed_checks"]})

    def test_fails_when_benchmarks_are_missing(self):
        gate = evaluate_ranking_production_gate(_summary(benchmarks={}))

        self.assertFalse(gate["ready"])
        failed = {item["key"] for item in gate["failed_checks"]}
        self.assertIn("market_median_return_pct", failed)
        self.assertIn("baseline_top_5_avg_return_pct", failed)
        self.assertIn("baseline_max_drawdown", failed)

    def test_fails_when_recent_holdout_deteriorates_too_much(self):
        gate = evaluate_ranking_production_gate(
            _summary(holdout_validation={"recent_holdout_precision_at_5": 0.45, "walk_forward_precision_at_5": 0.62})
        )

        self.assertFalse(gate["ready"])
        self.assertIn("recent_holdout_vs_walk_forward", {item["key"] for item in gate["failed_checks"]})


if __name__ == "__main__":
    unittest.main()
