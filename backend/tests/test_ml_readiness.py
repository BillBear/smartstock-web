import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.ml_readiness import assess_ml_readiness
from app.services.ml_model_service import MLModelService


class MLReadinessTests(unittest.TestCase):
    def test_small_legacy_model_is_not_production_ready(self):
        report = assess_ml_readiness(
            {
                "model_id": "ml_20260604_221428",
                "status": "live_ready",
                "train_start": "2026-05-01",
                "train_end": "2026-06-20",
                "sample_count": 1320,
                "train_config": {"max_symbols": 20},
                "metrics": {
                    "method": "walk_forward_timeseries_split",
                    "up_model": {"auc": 0.586, "brier_score": 0.24, "ece": 0.11},
                },
            }
        )

        self.assertFalse(report["production_ml_ready"])
        self.assertEqual(report["status"], "insufficient")
        self.assertEqual(report["role"], "weak_reference_only")
        self.assertIn("sample_count_below_100000", report["blocking_codes"])
        self.assertIn("symbol_count_below_1500", report["blocking_codes"])
        self.assertIn("time_span_below_24_months", report["blocking_codes"])
        self.assertIn("stock_holdout_missing", report["blocking_codes"])
        self.assertIn("final_time_holdout_missing", report["blocking_codes"])
        self.assertIn("模型训练证据不足", report["message"])

    def test_full_market_holdout_model_can_be_ready(self):
        report = assess_ml_readiness(
            {
                "model_id": "ml_full_market",
                "status": "paper_only",
                "train_start": "2024-01-01",
                "train_end": "2026-04-01",
                "sample_count": 160000,
                "train_config": {
                    "max_symbols": 1800,
                    "stock_holdout_ratio": 0.2,
                    "final_time_holdout_months": 3,
                },
                "metrics": {
                    "method": "walk_forward_timeseries_split",
                    "split_count": 5,
                    "final_holdout": {
                        "auc": 0.68,
                        "brier_score": 0.19,
                        "ece": 0.05,
                        "precision_at_3": 0.66,
                        "precision_at_5": 0.61,
                        "bucket_hit_rates": [{"bucket": "top", "hit_rate": 0.68, "sample_count": 120}],
                    },
                    "stock_holdout": {
                        "symbol_count": 360,
                        "auc": 0.64,
                        "precision_at_5": 0.6,
                    },
                    "coverage": {
                        "board_count": 3,
                        "liquidity_bucket_count": 3,
                        "industry_count": 25,
                        "market_state_count": 3,
                    },
                    "up_model": {"auc": 0.68, "brier_score": 0.19, "ece": 0.05},
                },
            }
        )

        self.assertTrue(report["production_ml_ready"])
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["role"], "ranking_confidence_factor")
        self.assertEqual(report["blocking_codes"], [])


class MLModelServiceReadinessTests(unittest.TestCase):
    def test_latest_model_response_includes_readiness_gate(self):
        class StoreStub:
            def get_latest_ml_model(self):
                return {
                    "model_id": "ml_small",
                    "status": "live_ready",
                    "train_start": "2026-05-01",
                    "train_end": "2026-06-20",
                    "sample_count": 1320,
                    "train_config": {"max_symbols": 20},
                    "metrics": {"method": "walk_forward_timeseries_split", "split_count": 2},
                }

            def list_ml_factor_importance(self, model_id, limit=30):
                return []

        service = MLModelService(data_source_manager=None, store=StoreStub())

        response = service.get_latest_model()

        self.assertTrue(response["available"])
        self.assertEqual(response["ml_readiness"]["status"], "insufficient")
        self.assertFalse(response["ml_readiness"]["production_ml_ready"])
        self.assertEqual(response["model_validation_status"], "insufficient")

    def test_latest_model_recomputes_stale_stored_readiness(self):
        class StoreStub:
            def get_latest_ml_model(self):
                return {
                    "model_id": "ml_stale",
                    "status": "live_ready",
                    "train_start": "2026-05-01",
                    "train_end": "2026-06-20",
                    "sample_count": 1320,
                    "train_config": {"max_symbols": 20},
                    "metrics": {
                        "method": "walk_forward_timeseries_split",
                        "split_count": 2,
                        "ml_readiness": {
                            "status": "ready",
                            "production_ml_ready": True,
                            "blocking_codes": [],
                        },
                    },
                }

            def list_ml_factor_importance(self, model_id, limit=30):
                return []

        service = MLModelService(data_source_manager=None, store=StoreStub())

        response = service.get_latest_model()

        self.assertEqual(response["ml_readiness"]["status"], "insufficient")
        self.assertFalse(response["ml_readiness"]["production_ml_ready"])
        self.assertIn("sample_count_below_100000", response["ml_readiness"]["blocking_codes"])

    def test_model_metrics_response_includes_readiness_gate(self):
        class StoreStub:
            def get_ml_model(self, model_id):
                return {
                    "model_id": model_id,
                    "status": "paper_only",
                    "train_start": "2024-01-01",
                    "train_end": "2026-04-01",
                    "sample_count": 160000,
                    "train_config": {
                        "max_symbols": 1800,
                        "stock_holdout_ratio": 0.2,
                        "final_time_holdout_months": 3,
                    },
                    "metrics": {
                        "method": "walk_forward_timeseries_split",
                        "split_count": 5,
                        "final_holdout": {
                            "auc": 0.68,
                            "brier_score": 0.19,
                            "ece": 0.05,
                            "precision_at_3": 0.66,
                            "precision_at_5": 0.61,
                            "bucket_hit_rates": [{"bucket": "top", "hit_rate": 0.68, "sample_count": 120}],
                        },
                        "stock_holdout": {"symbol_count": 360, "auc": 0.64},
                        "coverage": {
                            "board_count": 3,
                            "liquidity_bucket_count": 3,
                            "industry_count": 25,
                            "market_state_count": 3,
                        },
                    },
                }

            def list_ml_factor_importance(self, model_id, limit=50):
                return []

        service = MLModelService(data_source_manager=None, store=StoreStub())

        response = service.get_model_metrics("ml_full_market")

        self.assertTrue(response["available"])
        self.assertEqual(response["ml_readiness"]["status"], "ready")
        self.assertTrue(response["ml_readiness"]["production_ml_ready"])
        self.assertEqual(response["model_validation_status"], "ready")


if __name__ == "__main__":
    unittest.main()
