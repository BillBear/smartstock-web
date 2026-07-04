import json
import tempfile
import unittest
from pathlib import Path

from app.evaluation.ml_training_reviewer import review_local_ml_run


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class MLTrainingReviewerTests(unittest.TestCase):
    def test_reviewer_writes_review_and_next_run_recommendations(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_json(run_dir / "dataset_meta.json", {"valid_symbol_count": 700, "sample_count": 120000})
            write_json(run_dir / "feature_audit.json", {"leakage_violations": [], "features": {"feature_strength": {"classification": "core_candidate"}}})
            write_json(
                run_dir / "model_comparison.json",
                {
                    "best_model": "sklearn_hist_gradient_boosting",
                    "models": {
                        "logistic_baseline": {"final_holdout": {"precision_at_5": 0.4}, "stock_holdout": {"precision_at_5": 0.38}},
                        "sklearn_hist_gradient_boosting": {
                            "final_holdout": {"precision_at_5": 0.6},
                            "stock_holdout": {"precision_at_5": 0.58},
                        },
                    },
                },
            )

            review = review_local_ml_run(run_dir)

            self.assertEqual(review["recommendation"], "promote_to_observation")
            self.assertTrue((run_dir / "post_run_review.md").exists())
            self.assertTrue((run_dir / "post_run_review.json").exists())
            self.assertTrue((run_dir / "next_run_recommendations.json").exists())

    def test_reviewer_blocks_when_symbols_below_required_or_leakage_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_json(run_dir / "dataset_meta.json", {"valid_symbol_count": 699, "sample_count": 120000})
            write_json(run_dir / "feature_audit.json", {"leakage_violations": ["future_return_10d_pct"], "features": {}})
            write_json(run_dir / "model_comparison.json", {"best_model": "logistic_baseline", "models": {}})

            review = review_local_ml_run(run_dir)

            self.assertEqual(review["recommendation"], "blocked")
            self.assertIn("valid_symbols_below_700", review["blocking_reasons"])
            self.assertIn("feature_leakage_detected", review["blocking_reasons"])

    def test_reviewer_uses_run_specific_required_symbol_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_json(
                run_dir / "dataset_meta.json",
                {"valid_symbol_count": 19, "required_valid_symbol_count": 20, "sample_count": 1000},
            )
            write_json(run_dir / "feature_audit.json", {"leakage_violations": [], "features": {}})
            write_json(run_dir / "model_comparison.json", {"best_model": "logistic_baseline", "models": {}})

            review = review_local_ml_run(run_dir)

            self.assertEqual(review["recommendation"], "blocked")
            self.assertIn("valid_symbols_below_20", review["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
