import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.recall_experiments import (
    DEFAULT_EXPERIMENTS,
    build_recall_experiment_report,
)


def _write_summary(root: Path, experiment_key: str, metrics=None, coverage=None):
    run_dir = root / experiment_key
    run_dir.mkdir(parents=True)
    payload = {
        "experiment_key": experiment_key,
        "candidate_row_count": 300,
        "coverage": coverage or {"coverage_status": "complete", "covered_date_count": 32},
        "metrics": metrics or {
            "precision_at_3": 0.7,
            "precision_at_5": 0.62,
            "ndcg_at_10": 0.55,
            "top_5_avg_return_10d": 0.08,
            "max_drawdown": 0.06,
        },
        "evidence_readiness": {
            "status": "ready",
            "production_evidence": True,
            "blocking_reasons": [],
            "covered_date_count": 32,
            "required_covered_date_count": 30,
        },
        "production_evidence": True,
    }
    (run_dir / "ranking_summary.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_dir


class RecallExperimentReportTests(unittest.TestCase):
    def test_default_experiment_matrix_includes_required_variants(self):
        keys = [item["key"] for item in DEFAULT_EXPERIMENTS]

        self.assertEqual(
            keys,
            [
                "baseline",
                "recall_220_deep_150",
                "recall_300_deep_300",
                "recall_500_deep_500",
                "multi_channel_union",
            ],
        )

    def test_missing_variant_reports_block_production_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_summary(root, "baseline")

            report = build_recall_experiment_report(root)

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["production_switch_ready"])
        self.assertIn("missing_experiment_reports", report["blocking_reasons"])
        self.assertEqual(report["summary"]["available_experiment_count"], 1)

    def test_experiment_is_ready_only_when_candidate_beats_baseline_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_summary(
                root,
                "baseline",
                metrics={
                    "precision_at_3": 0.65,
                    "precision_at_5": 0.60,
                    "ndcg_at_10": 0.50,
                    "top_5_avg_return_10d": 0.05,
                    "max_drawdown": 0.08,
                },
            )
            _write_summary(root, "recall_220_deep_150")
            _write_summary(root, "recall_300_deep_300")
            _write_summary(root, "recall_500_deep_500")
            _write_summary(
                root,
                "multi_channel_union",
                metrics={
                    "precision_at_3": 0.72,
                    "precision_at_5": 0.66,
                    "ndcg_at_10": 0.59,
                    "top_5_avg_return_10d": 0.09,
                    "max_drawdown": 0.07,
                },
            )

            report = build_recall_experiment_report(root)

        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["production_switch_ready"])
        self.assertEqual(report["winner"]["key"], "multi_channel_union")
        self.assertGreater(report["winner"]["deltas"]["precision_at_3"], 0)
        self.assertGreater(report["winner"]["deltas"]["ndcg_at_10"], 0)

    def test_reads_current_ranking_summary_topk_return_metric_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_summary(
                root,
                "baseline",
                metrics={
                    "precision_at_3": 0.10,
                    "precision_at_5": 0.12,
                    "ndcg_at_10": 0.20,
                    "top_5_avg_return_pct": -0.55,
                    "max_drawdown": 0.08,
                },
            )

            report = build_recall_experiment_report(root)

        baseline = report["experiments"][0]
        self.assertEqual(baseline["key"], "baseline")
        self.assertEqual(baseline["metrics"]["top_5_avg_return_pct"], -0.55)


if __name__ == "__main__":
    unittest.main()
