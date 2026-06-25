import math
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.advice_service import AdviceService
from app.services.ai_decision_service import AIDecisionEngine
from app.services.coach_service import CoachService
from app.services.coach_store import CoachStore
from app.services.ml_feature_builder import MLFeatureBuilder
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


class AIDecisionEngineTests(unittest.TestCase):
    def test_coach_aligned_decision_blocks_legacy_buy_when_symbol_is_not_in_pool(self):
        decision = AIDecisionEngine.make_coach_aligned_decision(
            symbol="000960",
            name="锡业股份",
            price=44.42,
            coach_context={
                "symbol": "000960",
                "available": False,
                "source": "not_in_current_strategy_pool",
                "reason": "该股不在当前智能选股输出池中，个股详情仅展示行情分析分。",
            },
            technical_signals={"score": 55, "trend": "上升", "signals": ["MACD金叉"]},
            money_flow_data={"available": True, "main_net_inflow": 1000000, "control_ratio": 1.0},
            user_profile={"risk_level": "medium", "holding_period": "short"},
        )

        self.assertEqual(decision["decision_source"], "coach_service")
        self.assertEqual(decision["decision"], "未入选候选池")
        self.assertEqual(decision["position_advice"]["action"], "未入选候选池")
        self.assertIsNone(decision["scores"]["technical"])
        self.assertIsNone(decision["scores"]["money_flow"])
        self.assertIsNone(decision["scores"]["total"])
        self.assertIsNone(decision["scores"]["adjusted"])
        self.assertIsNone(decision["position_advice"]["entry_price"])
        self.assertIsNone(decision["position_advice"]["stop_profit"])
        self.assertIsNone(decision["position_advice"]["stop_loss"])
        self.assertEqual(decision["legacy_scores"]["adjusted"], 29.6)
        self.assertIn("不在当前智能选股输出池", decision["action_plan"][0])

    def test_coach_aligned_decision_uses_current_smart_screen_action(self):
        decision = AIDecisionEngine.make_coach_aligned_decision(
            symbol="000001",
            name="平安银行",
            price=10.0,
            coach_context={
                "symbol": "000001",
                "available": True,
                "source": "today_smart_screen",
                "trade_date": "2026-06-25",
                "pick_id": "2026-06-25-000001-S1",
                "rank_no": 4,
                "action": "paper_validate",
                "paper_validation": True,
                "up_prob": 0.66,
                "dd_prob": 0.22,
                "expected_return_pct": 6.5,
                "expected_edge_pct": 2.1,
                "profit_factor_proxy": 1.4,
                "entry_range": [9.8, 10.1],
                "take_profit": 11.2,
                "stop_loss": 9.1,
                "position_pct": 3.0,
                "horizon_days": 15,
                "score_breakdown": {
                    "trend": 74.0,
                    "money_flow": 62.0,
                    "total": 72.5,
                    "ranking_score": 81.2,
                },
                "ranking_score": 81.2,
                "confidence_level": "B",
                "risks": ["仅限模拟验证：不作为实盘买入信号。"],
                "reasons": ["趋势评分较强"],
                "exclusion_reason": "模拟验证候选：未达到实盘买入证据闸门。",
            },
            technical_signals={"score": 10, "trend": "上升", "signals": []},
            money_flow_data={"available": False},
            user_profile={"risk_level": "medium", "holding_period": "medium"},
        )

        self.assertEqual(decision["decision_source"], "coach_service")
        self.assertEqual(decision["decision"], "模拟验证")
        self.assertEqual(decision["scores"]["total"], 72.5)
        self.assertEqual(decision["scores"]["adjusted"], 81.2)
        self.assertEqual(decision["position_advice"]["position_size"], "3.0%")
        self.assertEqual(decision["expected_return"]["probability"], "66%")
        self.assertEqual(decision["coach_context"]["pick_id"], "2026-06-25-000001-S1")


class CoachServiceObservabilityTests(unittest.TestCase):
    def test_coach_numeric_helpers_reject_nan_and_infinite_values(self):
        self.assertEqual(CoachService._safe_float(float("nan"), 7.0), 7.0)
        self.assertEqual(CoachService._safe_float(float("inf"), 7.0), 7.0)
        self.assertEqual(CoachService._safe_float(float("-inf"), 7.0), 7.0)
        self.assertEqual(CoachService._clamp(float("nan"), 0, 100), 0)
        self.assertEqual(CoachService._clamp(float("inf"), 0, 100), 0)
        self.assertEqual(CoachService._clamp(float("-inf"), 0, 100), 0)

    def test_market_news_exception_is_logged_and_marked_unavailable(self):
        class DataSourceStub:
            def get_realtime_quote(self, symbol):
                return None

        class NewsServiceStub:
            def get_market_news_summary(self):
                raise RuntimeError("news timeout")

        with tempfile.TemporaryDirectory() as tmpdir:
            service = CoachService(
                data_source_manager=DataSourceStub(),
                store=CoachStore(str(Path(tmpdir) / "coach.db")),
                news_service=NewsServiceStub(),
            )

            with self.assertLogs("app.services.coach_service", level="WARNING") as captured:
                market_state = service.get_market_state_today()

        self.assertEqual(market_state["news_context"]["source_status"], "unavailable")
        self.assertEqual(market_state["news_context"]["error"], "news_service_unavailable")
        self.assertIn("market news summary unavailable", "\n".join(captured.output))


class MLFeatureBuilderTests(unittest.TestCase):
    def test_forward_label_risk_adjusted_return_preserves_missing_future_window(self):
        feature_df = pd.DataFrame(
            {
                "close": [10.0, 11.0, 12.0, 13.0],
                "high": [10.5, 11.5, 12.5, 13.5],
                "low": [9.5, 10.5, 11.5, 12.5],
            }
        )

        labeled = MLFeatureBuilder.add_forward_labels(feature_df, horizon_days=2)

        self.assertTrue(pd.notna(labeled.loc[0, "label_risk_adjusted_return"]))
        self.assertTrue(pd.isna(labeled.loc[2, "label_risk_adjusted_return"]))
        self.assertTrue(pd.isna(labeled.loc[3, "label_risk_adjusted_return"]))


class CoachStoreTests(unittest.TestCase):
    def test_open_or_add_position_is_atomic_across_store_instances(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "coach.db")
            stores = [CoachStore(db_path) for _ in range(12)]

            def buy(index: int):
                return stores[index % len(stores)].open_or_add_position(
                    user_id="default",
                    symbol="600519",
                    name="贵州茅台",
                    pick_id=f"pick-{index}",
                    price=10 + (index % 3),
                    qty=100,
                    created_at=f"2026-06-25 10:{index:02d}:00",
                    reason="concurrency-test",
                )

            errors = []
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [executor.submit(buy, index) for index in range(60)]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        errors.append(repr(exc))

            positions = stores[0].list_open_positions("default")
            expected_cost = sum((10 + (index % 3)) * 100 for index in range(60))

            self.assertEqual(errors, [])
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0]["qty"], 6000)
            self.assertEqual(positions[0]["cost_amount"], expected_cost)
            self.assertAlmostEqual(positions[0]["avg_price"], expected_cost / 6000, places=6)


if __name__ == "__main__":
    unittest.main()
