import json
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.evaluation.full_market_ml.config import load_full_market_ml_config
from app.evaluation.full_market_ml.preflight import run_preflight


class FakeProbeClient:
    def trade_cal(self, **kwargs):
        return [{"cal_date": "20260709", "is_open": 1}]

    def daily(self, **kwargs):
        return [{"ts_code": f"600{i:03d}.SH", "trade_date": "20260709"} for i in range(5000)]


class FullMarketMLPreflightTests(unittest.TestCase):
    def setUp(self):
        self.config = load_full_market_ml_config(
            Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml"
        )
        self.module_versions = {
            "numpy": "2.0.2",
            "pandas": "2.3.3",
            "pyarrow": "20.0.0",
            "scikit-learn": "1.6.1",
            "lightgbm": "4.6.0",
            "joblib": "1.5.3",
            "psutil": "7.0.0",
            "tushare": "1.4.21",
            "python-dotenv": "1.0.0",
        }

    def test_preflight_requires_token_without_exposing_it(self):
        result = run_preflight(
            self.config,
            env={},
            probe_client=None,
            module_versions=self.module_versions,
        )

        self.assertFalse(result["ready"])
        self.assertIn("tushare_token_missing", result["blocking_codes"])
        sanitized = str(result).lower().replace("tushare_token_missing", "")
        self.assertNotIn("secret", sanitized)

    def test_preflight_accepts_16gb_machine_and_full_market_probe(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = run_preflight(
                self.config,
                env={"TUSHARE_TOKEN": "secret"},
                probe_client=FakeProbeClient(),
                memory_bytes=16 * 1024**3,
                free_disk_bytes=100 * 1024**3,
                python_version=(3, 11, 9),
                module_versions=self.module_versions,
                runtime_root=Path(temporary_directory),
            )

        self.assertTrue(result["ready"])
        self.assertEqual(result["observed"]["daily_probe_count"], 5000)
        self.assertNotIn("secret", json.dumps(result))

    def test_preflight_persisted_json_never_contains_token_or_its_digest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "preflight.json"
            run_preflight(
                self.config,
                env={"TUSHARE_TOKEN": "secret"},
                probe_client=FakeProbeClient(),
                memory_bytes=16 * 1024**3,
                free_disk_bytes=100 * 1024**3,
                python_version=(3, 11, 9),
                module_versions=self.module_versions,
                runtime_root=output_path.parent,
            )

            persisted = output_path.read_text(encoding="utf-8")

        self.assertNotIn("secret", persisted)
        self.assertNotIn(sha256(b"secret").hexdigest(), persisted)
        self.assertTrue(json.loads(persisted)["observed"]["tushare_token_configured"])

    def test_preflight_creates_fresh_nested_runtime_root_before_disk_check(self):
        disk = SimpleNamespace(f_bavail=100 * 1024**3, f_frsize=1)
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime_root = Path(temporary_directory) / "fresh" / "nested" / "runtime"

            def statvfs_existing_directory(path):
                self.assertTrue(Path(path).is_dir())
                return disk

            with patch(
                "app.evaluation.full_market_ml.preflight.os.statvfs",
                side_effect=statvfs_existing_directory,
            ):
                result = run_preflight(
                    self.config,
                    env={"TUSHARE_TOKEN": "secret"},
                    probe_client=FakeProbeClient(),
                    memory_bytes=16 * 1024**3,
                    python_version=(3, 11, 9),
                    module_versions=self.module_versions,
                    runtime_root=runtime_root,
                )

        self.assertTrue(result["ready"])

    def test_preflight_enforces_daily_probe_floor_when_config_threshold_is_lower(self):
        class SmallDailyProbeClient(FakeProbeClient):
            def daily(self, **kwargs):
                return super().daily(**kwargs)[:4499]

        lower_threshold_config = replace(
            self.config,
            sample=replace(self.config.sample, minimum_daily_symbols=1),
        )
        result = run_preflight(
            lower_threshold_config,
            env={"TUSHARE_TOKEN": "secret"},
            probe_client=SmallDailyProbeClient(),
            memory_bytes=16 * 1024**3,
            free_disk_bytes=100 * 1024**3,
            python_version=(3, 11, 9),
            module_versions=self.module_versions,
        )

        self.assertFalse(result["ready"])
        self.assertIn("daily_probe_insufficient", result["blocking_codes"])

    def test_preflight_reports_failed_environment_checks_and_persists_atomically(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime_root = Path(temporary_directory) / "runtime"
            result = run_preflight(
                self.config,
                env={"TUSHARE_TOKEN": "secret"},
                probe_client=FakeProbeClient(),
                memory_bytes=14 * 1024**3,
                free_disk_bytes=39 * 1024**3,
                python_version=(3, 10, 14),
                module_versions={"numpy": "1.0.0"},
                runtime_root=runtime_root,
            )

            output_path = runtime_root / "preflight.json"
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), result)
            self.assertFalse(list(runtime_root.glob("*.tmp")))

        self.assertFalse(result["ready"])
        self.assertEqual(
            result["blocking_codes"],
            [
                "python_version_unsupported",
                "pinned_modules_missing_or_mismatched",
                "memory_insufficient",
                "free_disk_insufficient",
            ],
        )

    def test_preflight_blocks_calendar_and_small_daily_probe(self):
        class InsufficientProbeClient:
            def trade_cal(self, **kwargs):
                return []

            def daily(self, **kwargs):
                return []

        result = run_preflight(
            self.config,
            env={"TUSHARE_TOKEN": "secret"},
            probe_client=InsufficientProbeClient(),
            memory_bytes=16 * 1024**3,
            free_disk_bytes=100 * 1024**3,
            python_version=(3, 11, 9),
            module_versions=self.module_versions,
        )

        self.assertFalse(result["ready"])
        self.assertEqual(
            result["blocking_codes"],
            ["trade_calendar_unavailable", "daily_probe_insufficient"],
        )

    def test_preflight_blocks_daily_api_exception_after_calendar_succeeds(self):
        class DailyFailureProbeClient(FakeProbeClient):
            def daily(self, **kwargs):
                raise RuntimeError("daily unavailable")

        result = run_preflight(
            self.config,
            env={"TUSHARE_TOKEN": "secret"},
            probe_client=DailyFailureProbeClient(),
            memory_bytes=16 * 1024**3,
            free_disk_bytes=100 * 1024**3,
            python_version=(3, 11, 9),
            module_versions=self.module_versions,
        )

        self.assertEqual(result["blocking_codes"], ["daily_probe_insufficient"])

    def test_preflight_blocks_insufficient_daily_count_after_calendar_succeeds(self):
        class SmallDailyProbeClient(FakeProbeClient):
            def daily(self, **kwargs):
                return super().daily(**kwargs)[:4499]

        result = run_preflight(
            self.config,
            env={"TUSHARE_TOKEN": "secret"},
            probe_client=SmallDailyProbeClient(),
            memory_bytes=16 * 1024**3,
            free_disk_bytes=100 * 1024**3,
            python_version=(3, 11, 9),
            module_versions=self.module_versions,
        )

        self.assertEqual(result["blocking_codes"], ["daily_probe_insufficient"])


if __name__ == "__main__":
    unittest.main()
