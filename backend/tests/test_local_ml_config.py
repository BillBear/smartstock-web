import unittest

from app.evaluation.local_ml_config import build_local_ml_config


class LocalMLConfigTests(unittest.TestCase):
    def test_default_config_targets_700_valid_symbols_and_runtime_outputs(self):
        cfg = build_local_ml_config(
            {
                "train_start": "2025-01-01",
                "train_end": "2026-07-03",
                "model_family": "local_core_v1",
            }
        )

        self.assertEqual(cfg["model_family"], "local_core_v1")
        self.assertEqual(cfg["target_valid_symbols"], 700)
        self.assertEqual(cfg["oversample_symbols"], 760)
        self.assertEqual(cfg["min_formal_model_symbols"], 700)
        self.assertEqual(cfg["sample_step"], 2)
        self.assertEqual(cfg["primary_horizon"], 10)
        self.assertEqual(cfg["auxiliary_horizons"], [5, 20])
        self.assertEqual(cfg["history_fetch_workers"], 1)
        self.assertGreater(cfg["history_inter_request_sleep_seconds"], 0)
        self.assertGreater(cfg["history_circuit_sleep_seconds"], 0)
        self.assertTrue(cfg["exclude_news_features"])
        self.assertTrue(cfg["exclude_market_state_features"])
        self.assertFalse(cfg["production_enabled"])
        self.assertEqual(cfg["status"], "paper_only")
        self.assertIn("runtime/ml_runs/local_core_v1", cfg["output_root"])
        self.assertIn("local_core_v1_", cfg["run_id"])


if __name__ == "__main__":
    unittest.main()
