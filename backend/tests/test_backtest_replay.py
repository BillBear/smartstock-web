import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coach_service import CoachService
from app.services.coach_store import CoachStore
from scripts.run_backtest_baseline import (
    build_backtest_payload,
    build_artifact,
    key_metrics_match,
    main as run_baseline_main,
    run_fixture_smoke,
    write_artifact,
)


class DummyDataSourceManager:
    allow_mock_fallback = False


class BacktestReplayTests(unittest.TestCase):
    def build_service(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "coach.sqlite3"
        store = CoachStore(str(db_path))
        service = CoachService(DummyDataSourceManager(), store=store)
        self.addCleanup(temp_dir.cleanup)
        return service

    def test_monthly_returns_use_last_equity_value_for_each_month(self):
        service = self.build_service()
        equity_curve = [
            {"date": "2026-01-02", "value": 100.0},
            {"date": "2026-01-30", "value": 110.0},
            {"date": "2026-02-27", "value": 121.0},
            {"date": "2026-03-31", "value": 108.9},
        ]

        returns = service._build_monthly_returns(equity_curve)

        self.assertEqual(len(returns), 2)
        self.assertAlmostEqual(returns[0], 0.10)
        self.assertAlmostEqual(returns[1], -0.10)

    def test_credibility_assessment_requires_sample_and_quality_gates(self):
        service = self.build_service()

        credibility = service._assess_backtest_credibility(
            metrics={
                "sharpe": 0.8,
                "max_drawdown": 0.24,
                "win_rate": 0.50,
                "profit_loss_ratio": 1.10,
                "annual_return": 0.08,
            },
            diagnostics={
                "closed_roundtrips": 12,
                "calendar_days": 90,
                "valid_history_symbols": 30,
                "universe_size": 140,
            },
            config={"slippage": 0.001, "commission": 0.0003},
            by_state=[
                {"state": "bull", "sample_count": 6, "win_rate": 0.55},
                {"state": "bear", "sample_count": 6, "win_rate": 0.45},
            ],
            equity_curve=[
                {"date": "2026-01-31", "value": 1.0},
                {"date": "2026-02-28", "value": 1.02},
                {"date": "2026-03-31", "value": 0.98},
            ],
        )

        failed_keys = {item["key"] for item in credibility["failed_checks"]}

        self.assertFalse(credibility["live_ready"])
        self.assertIn("closed_roundtrips", failed_keys)
        self.assertIn("calendar_days", failed_keys)
        self.assertIn("valid_history_symbols", failed_keys)
        self.assertIn("max_drawdown", failed_keys)
        self.assertEqual(credibility["assumptions"]["buy_execution_model"], "T+1 next_open_with_slippage")
        self.assertTrue(credibility["assumptions"]["mock_fallback_disabled"])


class BacktestBaselineHarnessTests(unittest.TestCase):
    def build_args(self, output=None):
        return SimpleNamespace(
            strategy_code="trend_breakout",
            test_start="2025-01-01",
            test_end="2025-12-31",
            risk_level="medium",
            universe_size=90,
            commission=0.0003,
            slippage=0.001,
            output=output or "baseline.json",
            fixture="smoke",
        )

    def build_cli_args(self, output):
        return [
            "--strategy-code",
            "trend_breakout",
            "--test-start",
            "2025-01-01",
            "--test-end",
            "2025-12-31",
            "--risk-level",
            "medium",
            "--universe-size",
            "90",
            "--commission",
            "0.0003",
            "--slippage",
            "0.001",
            "--output",
            str(output),
            "--fixture",
            "smoke",
        ]

    def test_build_backtest_payload_passes_explicit_cli_config(self):
        payload = build_backtest_payload(self.build_args())

        self.assertEqual(payload["strategy_code"], "trend_breakout")
        self.assertEqual(payload["test_start"], "2025-01-01")
        self.assertEqual(payload["test_end"], "2025-12-31")
        self.assertEqual(
            payload["config"],
            {
                "risk_level": "medium",
                "universe_size": 90,
                "commission": 0.0003,
                "slippage": 0.001,
            },
        )

    def test_smoke_fixture_artifact_is_labeled_non_investable(self):
        args = self.build_args()
        payload = build_backtest_payload(args)
        run_result = run_fixture_smoke(payload)
        artifact = build_artifact(
            run_result=run_result,
            payload=payload,
            args=args,
            mode="fixture_smoke",
            git_info={"sha": "abc123", "dirty": False},
            generated_at="2026-06-19T00:00:00+08:00",
            output_path="/tmp/baseline.json",
        )

        self.assertEqual(artifact["baseline_schema_version"], "1.0")
        self.assertEqual(artifact["evidence_mode"], "fixture_smoke")
        self.assertFalse(artifact["investable_evidence"])
        self.assertIn("non-investable", artifact["evidence_warning"])
        self.assertEqual(artifact["run_id"], run_result["run_id"])
        self.assertEqual(artifact["effective_config"], run_result["config"])
        self.assertEqual(artifact["execution_assumptions"]["commission"], 0.0003)
        self.assertEqual(artifact["execution_assumptions"]["slippage"], 0.001)
        self.assertEqual(artifact["data_coverage"]["calendar_days"], 244)
        self.assertEqual(artifact["data_coverage"]["valid_history_symbols"], 90)
        self.assertEqual(artifact["reproducibility"]["git_sha"], "abc123")
        self.assertEqual(artifact["reproducibility"]["baseline_schema_version"], "1.0")
        self.assertEqual(artifact["drawdown_curve_summary"]["points"], 4)
        self.assertIn("diagnostics", artifact)

    def test_smoke_fixture_key_metrics_are_deterministic(self):
        payload = build_backtest_payload(self.build_args())

        first = run_fixture_smoke(payload)
        second = run_fixture_smoke(payload)

        self.assertTrue(key_metrics_match(first["metrics"], second["metrics"], tolerance=0.0))
        self.assertEqual(first["diagnostics"], second["diagnostics"])
        self.assertEqual(first["drawdown_curve"], second["drawdown_curve"])

    def test_write_artifact_creates_parent_directory_and_json(self):
        args = self.build_args()
        payload = build_backtest_payload(args)
        artifact = build_artifact(
            run_result=run_fixture_smoke(payload),
            payload=payload,
            args=args,
            mode="fixture_smoke",
            git_info={"sha": "abc123", "dirty": False},
            generated_at="2026-06-19T00:00:00+08:00",
            output_path=None,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "nested" / "baseline.json"
            written_path = write_artifact(artifact, output_path)

            self.assertEqual(written_path, output_path)
            self.assertTrue(output_path.exists())
            self.assertIn('"baseline_schema_version": "1.0"', output_path.read_text(encoding="utf-8"))

    def test_cli_rejects_semantically_invalid_args_without_writing_artifact(self):
        invalid_cases = [
            (["--test-start", "2025/01/01"], "test-start must use YYYY-MM-DD"),
            (["--test-start", "2025-12-31", "--test-end", "2025-01-01"], "test-start must be on or before test-end"),
            (["--universe-size", "0"], "universe-size must be greater than 0"),
            (["--commission", "-0.0001"], "commission must be greater than or equal to 0"),
            (["--slippage", "-0.001"], "slippage must be greater than or equal to 0"),
        ]

        for overrides, expected_error in invalid_cases:
            with self.subTest(overrides=overrides):
                with tempfile.TemporaryDirectory() as temp_dir:
                    output_path = Path(temp_dir) / "invalid-baseline.json"
                    argv = self.build_cli_args(output_path)
                    for name, value in zip(overrides[0::2], overrides[1::2]):
                        argv[argv.index(name) + 1] = value
                    stderr = io.StringIO()

                    with contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as raised:
                            run_baseline_main(argv)

                    self.assertNotEqual(raised.exception.code, 0)
                    self.assertIn(expected_error, stderr.getvalue())
                    self.assertFalse(output_path.exists())

    def test_cli_returns_clean_error_when_output_path_is_existing_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = run_baseline_main(self.build_cli_args(output_dir))

            self.assertNotEqual(exit_code, 0)
            self.assertIn("failed to write artifact", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
