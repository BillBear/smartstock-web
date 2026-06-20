import copy
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coach_service import CoachService


class StrategyContractTests(unittest.TestCase):
    def test_strategy_presets_include_required_risk_and_execution_controls(self):
        required_config_keys = {
            "risk_level",
            "holding_days",
            "stop_profit_pct",
            "stop_loss_pct",
            "score_threshold",
            "commission",
            "slippage",
            "max_positions",
            "max_position_pct",
            "universe_size",
        }

        self.assertGreater(len(CoachService.STRATEGY_PRESET_LIBRARY), 0)
        for strategy_code, presets in CoachService.STRATEGY_PRESET_LIBRARY.items():
            with self.subTest(strategy_code=strategy_code):
                self.assertTrue(presets)
                profile_keys = [preset.get("profile_key") for preset in presets]
                self.assertEqual(len(profile_keys), len(set(profile_keys)))

            for preset in presets:
                config = preset.get("config") or {}
                with self.subTest(strategy_code=strategy_code, profile_key=preset.get("profile_key")):
                    self.assertTrue(preset.get("label"))
                    self.assertFalse(required_config_keys - set(config.keys()))
                    self.assertIn(config["risk_level"], {"low", "medium", "high"})
                    self.assertGreater(config["holding_days"], 0)
                    self.assertGreater(config["stop_profit_pct"], 0)
                    self.assertGreater(config["stop_loss_pct"], 0)
                    self.assertGreaterEqual(config["score_threshold"], 0)
                    self.assertGreater(config["commission"], 0)
                    self.assertGreater(config["slippage"], 0)
                    self.assertGreater(config["max_positions"], 0)
                    self.assertGreater(config["max_position_pct"], 0)
                    self.assertGreater(config["universe_size"], 0)

    def test_live_gate_rules_cover_backtest_readiness_dimensions_once(self):
        expected_keys = {
            "mock_fallback_disabled",
            "closed_roundtrips",
            "calendar_days",
            "valid_history_symbols",
            "sharpe",
            "max_drawdown",
            "win_rate",
            "profit_loss_ratio",
            "monthly_positive_ratio",
            "monthly_count",
            "credibility_score",
        }

        keys = [rule.get("key") for rule in CoachService.LIVE_GATE_RULES]

        self.assertEqual(set(keys), expected_keys)
        self.assertEqual(len(keys), len(set(keys)))
        for rule in CoachService.LIVE_GATE_RULES:
            self.assertTrue(rule.get("label"))
            self.assertTrue(rule.get("threshold"))

    def test_ranking_evaluation_modules_do_not_mutate_strategy_presets(self):
        before = copy.deepcopy(CoachService.STRATEGY_PRESET_LIBRARY)

        for module_name in (
            "app.evaluation.ranking_labels",
            "app.evaluation.ranking_metrics",
            "app.evaluation.ranking_replay",
            "app.evaluation.ranking_diagnostics",
            "app.evaluation.ranking_report",
            "app.evaluation.ranking_fixtures",
        ):
            with self.subTest(module_name=module_name):
                importlib.import_module(module_name)

        self.assertEqual(CoachService.STRATEGY_PRESET_LIBRARY, before)

    def test_ranking_evaluation_report_does_not_mutate_strategy_presets(self):
        before = copy.deepcopy(CoachService.STRATEGY_PRESET_LIBRARY)
        from app.evaluation.ranking_fixtures import smoke_fixture_rows
        from app.evaluation.ranking_labels import DEFAULT_STRONG_LABEL_CONFIG
        from app.evaluation.ranking_report import build_ranking_report

        horizons = [3, 5, 10, 20]
        rows, coverage = smoke_fixture_rows(horizons)
        label_config = dict(DEFAULT_STRONG_LABEL_CONFIG)
        label_config["horizons"] = horizons

        with tempfile.TemporaryDirectory() as output_dir:
            summary = build_ranking_report(
                candidate_rows=rows,
                strategy_code="trend_breakout",
                risk_level="medium",
                start_date="2026-01-02",
                end_date="2026-01-09",
                horizons=horizons,
                top_k_values=[3, 5, 10],
                output_dir=output_dir,
                label_config=label_config,
                coverage=coverage,
                execution_config={"fixture": "smoke"},
            )

        self.assertEqual(summary["coverage"]["coverage_status"], "complete")
        self.assertEqual(CoachService.STRATEGY_PRESET_LIBRARY, before)


if __name__ == "__main__":
    unittest.main()
