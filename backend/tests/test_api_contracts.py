import os
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings
from app.models.schemas import CoachBacktestRunRequest, TechnicalAnalysisRequest


class SettingsTests(unittest.TestCase):
    def test_secret_defaults_are_empty_and_local_frontend_is_allowed(self):
        env_backup = {key: os.environ.get(key) for key in ("TUSHARE_TOKEN", "USE_MOCK_DATA")}
        try:
            os.environ.pop("TUSHARE_TOKEN", None)
            os.environ.pop("USE_MOCK_DATA", None)
            settings = Settings(_env_file=None)
        finally:
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(settings.TUSHARE_TOKEN, "")
        self.assertFalse(settings.USE_MOCK_DATA)
        self.assertIn("http://localhost:3601", settings.CORS_ORIGINS)


class RequestSchemaContractTests(unittest.TestCase):
    def test_technical_analysis_request_bounds_days(self):
        request = TechnicalAnalysisRequest(symbol="000001", days=30)

        self.assertEqual(request.symbol, "000001")
        self.assertEqual(request.period, "daily")
        self.assertEqual(request.days, 30)
        with self.assertRaises(ValidationError):
            TechnicalAnalysisRequest(symbol="000001", days=29)
        with self.assertRaises(ValidationError):
            TechnicalAnalysisRequest(symbol="000001", days=366)

    def test_backtest_request_uses_isolated_default_config_dicts(self):
        first = CoachBacktestRunRequest()
        second = CoachBacktestRunRequest()

        first.config["risk_level"] = "medium"

        self.assertEqual(first.strategy_code, "trend_breakout")
        self.assertIsNone(first.strategy_version_id)
        self.assertEqual(second.config, {})


if __name__ == "__main__":
    unittest.main()
