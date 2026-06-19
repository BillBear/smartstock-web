import math
import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.advice_service import AdviceService
from app.services.technical_analyzer import TechnicalAnalyzer


class TechnicalAnalyzerTests(unittest.TestCase):
    def test_analyze_all_indicators_adds_expected_columns(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=80).strftime("%Y-%m-%d"),
                "open": [10 + i * 0.1 for i in range(80)],
                "high": [10.5 + i * 0.1 for i in range(80)],
                "low": [9.5 + i * 0.1 for i in range(80)],
                "close": [10 + i * 0.1 for i in range(80)],
                "volume": [100000 + i for i in range(80)],
            }
        )

        result = TechnicalAnalyzer.analyze_all_indicators(df.copy())

        for column in ("ma5", "ma10", "ma20", "ma60", "macd", "rsi", "k", "d", "j", "boll_upper"):
            self.assertIn(column, result.columns)

        latest = TechnicalAnalyzer.get_latest_indicators(result)
        self.assertEqual(latest["date"], "2026-03-21")
        self.assertTrue(math.isfinite(latest["close"]))
        self.assertIsNotNone(latest["ma60"])

    def test_generate_signals_bounds_expected_bullish_case(self):
        indicators = {
            "close": 12.0,
            "ma5": 11.5,
            "ma10": 11.0,
            "ma20": 10.5,
            "ma60": 9.5,
            "macd": 0.5,
            "macd_signal": 0.2,
            "macd_hist": 0.3,
            "rsi": 55,
            "k": 65,
            "d": 55,
            "j": 85,
            "boll_upper": 13.0,
            "boll_lower": 9.0,
        }

        signal = TechnicalAnalyzer.generate_signals(indicators)

        self.assertGreater(signal["score"], 0)
        self.assertIn(signal["overall_signal"], {"谨慎买入", "买入", "强烈买入"})
        self.assertEqual(signal["trend"], "上升")


class AdviceServiceTests(unittest.TestCase):
    def test_generate_advice_includes_risk_controls(self):
        advice = AdviceService.generate_advice(
            symbol="000001",
            name="平安银行",
            price=10.0,
            signal_analysis={"score": 35, "overall_signal": "买入", "signals": []},
            holding_period="medium",
            risk_level="medium",
            target_return=15,
        )

        self.assertEqual(advice["symbol"], "000001")
        self.assertIn("entry", advice["advice"])
        self.assertIn("take_profit", advice["advice"])
        self.assertIn("stop_loss", advice["advice"])
        self.assertGreaterEqual(len(advice["risk_warning"]), 3)


if __name__ == "__main__":
    unittest.main()
