import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.evaluation.full_market_ml import config as config_module
from app.evaluation.full_market_ml.config import load_full_market_ml_config
from tests.full_market_ml_fixtures import full_market_ml_config_data


class FullMarketMLConfigTests(unittest.TestCase):
    def test_fixed_contract_loads_and_hashes_exact_file(self):
        path = Path(__file__).parents[1] / "config" / "ml_full_market_v1.toml"
        config = load_full_market_ml_config(path)
        self.assertEqual(config.dates.signal_start, "2024-06-03")
        self.assertEqual(config.dates.signal_end, "2026-06-05")
        self.assertEqual(config.sample.minimum_daily_symbols, 4500)
        self.assertEqual(config.splits.embargo_trade_days, 20)
        self.assertEqual(config.training.seeds, (17, 42, 73))
        self.assertEqual(config.collection.request_pacing_seconds, 0.01)
        self.assertEqual(config.collection.namechange_history_start, "1990-01-01")
        self.assertEqual(config.sha256, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_hashes_the_validated_byte_snapshot_when_file_changes_after_parse(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.toml"
            path.write_text(_to_toml(full_market_ml_config_data()), encoding="utf-8")
            validated_bytes = path.read_bytes()
            replacement_bytes = validated_bytes.replace(b"minimum_daily_symbols = 4500", b"minimum_daily_symbols = 4501")
            hook_called = {"value": False}
            original_require_sections = config_module._require_sections

            def replace_file_after_parse(raw_config):
                hook_called["value"] = True
                path.write_bytes(replacement_bytes)
                original_require_sections(raw_config)

            with patch.object(config_module, "_require_sections", side_effect=replace_file_after_parse):
                config = load_full_market_ml_config(path)

            later_file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(hook_called["value"])
            self.assertEqual(config.sample.minimum_daily_symbols, 4500)
            self.assertEqual(config.sha256, hashlib.sha256(validated_bytes).hexdigest())
            self.assertNotEqual(config.sha256, later_file_sha256)

    def test_rejects_missing_sections(self):
        data = full_market_ml_config_data()
        data.pop("training")
        self._assert_invalid(data, "missing required section: training")

    def test_rejects_invalid_date_ordering(self):
        data = full_market_ml_config_data()
        data["dates"]["signal_end"] = "2024-06-02"
        self._assert_invalid(data, "signal_start must be before signal_end")

    def test_rejects_holdout_shorter_than_one_month(self):
        data = full_market_ml_config_data()
        data["dates"]["holdout_end"] = "2026-05-31"
        self._assert_invalid(data, "holdout period must be at least one calendar month")

    def test_rejects_fewer_than_five_walk_forward_folds(self):
        data = full_market_ml_config_data()
        data["splits"]["walk_forward_folds"] = 4
        self._assert_invalid(data, "walk_forward_folds must be at least 5")

    def test_rejects_memory_limit_above_twelve_gb(self):
        data = full_market_ml_config_data()
        data["resources"]["memory_limit_gb"] = 13
        self._assert_invalid(data, "memory_limit_gb must not exceed 12")

    def test_rejects_zero_or_negative_request_pacing(self):
        data = full_market_ml_config_data()
        data["collection"]["request_pacing_seconds"] = 0
        self._assert_invalid(data, "request_pacing_seconds must be greater than zero")

    def _assert_invalid(self, data, message):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.toml"
            path.write_text(_to_toml(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                load_full_market_ml_config(path)


def _to_toml(data):
    lines = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            if isinstance(value, str):
                rendered = f'"{value}"'
            elif isinstance(value, list):
                rendered = "[" + ", ".join(str(item) for item in value) + "]"
            else:
                rendered = str(value)
            lines.append(f"{key} = {rendered}")
        lines.append("")
    return "\n".join(lines)
